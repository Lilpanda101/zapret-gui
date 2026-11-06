#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Tests for orchestra/ (Stage 4): fully fake apply/probe, no root, no nft, no network."""
import json

import pytest

from orchestra.history import HistoryStore
from orchestra.orchestrator import Orchestrator, PresetResult
from orchestra.targets import DEFAULT_TARGETS, ProbeResult, Target, targets_from_domains


def make_targets():
    return [
        Target('youtube', 'YouTube', 'https://example.test/yt'),
        Target('discord', 'Discord', 'https://example.test/dc'),
    ]


class FakeEnv:
    """script: {preset_id: {target_key: [(ok, latency_ms), ...]}}; last outcome repeats."""

    def __init__(self, script):
        self.script = {pid: {k: list(v) for k, v in tmap.items()} for pid, tmap in script.items()}
        self.current = None
        self.applied = []

    def apply(self, preset_id):
        self.applied.append(preset_id)
        self.current = preset_id
        return True

    def probe(self, target):
        outcomes = self.script.get(self.current, {}).get(target.key, [])
        if not outcomes:
            return ProbeResult(False, 9999)
        ok, latency = outcomes.pop(0) if len(outcomes) > 1 else outcomes[0]
        return ProbeResult(bool(ok), int(latency))


def all_ok(latency):
    return {'youtube': [(True, latency)], 'discord': [(True, latency)]}


def all_fail():
    return {'youtube': [(False, 9999)], 'discord': [(False, 9999)]}


def test_winner_by_ok_count_then_latency():
    env = FakeEnv({'slow': all_ok(200), 'fast': all_ok(50), 'bad': all_fail()})
    orch = Orchestrator(env.apply, env.probe, targets=make_targets())
    result = orch.run(['slow', 'fast', 'bad'])
    assert result.winner == 'fast'
    assert result.best.ok_count == 2
    assert result.best.avg_latency_ms == 50
    assert result.completed is True
    assert result.stopped is False
    assert result.rolled_back is False
    # winner was not tested last, so it is re-applied at the end
    assert env.applied == ['slow', 'fast', 'bad', 'fast']


def test_stability_requires_two_of_three():
    env = FakeEnv({
        'flaky': {
            'youtube': [(True, 10), (False, 9999), (False, 9999)],
            'discord': [(True, 10), (True, 10), (False, 9999)],
        },
        'stable': {
            'youtube': [(True, 20), (True, 20), (False, 9999)],
            'discord': [(True, 20), (True, 20), (False, 9999)],
        },
    })
    orch = Orchestrator(env.apply, env.probe, targets=make_targets(), attempts=3, required_successes=2)
    result = orch.run(['flaky', 'stable'])
    by_id = {r.preset_id: r for r in result.results}
    assert by_id['flaky'].ok_count == 1
    yt = by_id['flaky'].per_target[0]
    assert (yt.attempts, yt.successes, yt.stable) == (3, 1, False)
    assert by_id['stable'].ok_count == 2
    assert result.winner == 'stable'
    # winner tested last: no extra re-apply
    assert env.applied == ['flaky', 'stable']


def test_stop_via_progress_callback():
    env = FakeEnv({'a': all_ok(10), 'b': all_ok(10), 'c': all_ok(10)})
    holder = {}

    def on_progress(done, total, preset_id, best):
        holder['orch'].stop()

    orch = Orchestrator(env.apply, env.probe, targets=make_targets(), on_progress=on_progress)
    holder['orch'] = orch
    result = orch.run(['a', 'b', 'c'])
    assert result.stopped is True
    assert result.reason == 'stopped'
    assert result.completed is False
    assert len(result.results) == 1
    assert result.winner == 'a'


def test_time_budget_respected():
    env = FakeEnv({'a': all_ok(10), 'b': all_ok(10)})
    times = iter([0, 0, 100])
    orch = Orchestrator(env.apply, env.probe, targets=make_targets(), time_budget_s=10, time_fn=lambda: next(times, 1000))
    result = orch.run(['a', 'b'])
    assert result.reason == 'budget'
    assert result.completed is False
    assert len(result.results) == 1
    assert result.winner == 'a'


def test_rollback_on_total_failure():
    env = FakeEnv({'a': all_fail(), 'b': all_fail()})
    orch = Orchestrator(env.apply, env.probe, targets=make_targets())
    result = orch.run(['a', 'b'], previous_preset='prev')
    assert result.winner is None
    assert result.rolled_back is True
    assert result.reason == 'all_failed_rolled_back'
    assert env.applied == ['a', 'b', 'prev']


def test_total_failure_without_previous():
    env = FakeEnv({'a': all_fail()})
    orch = Orchestrator(env.apply, env.probe, targets=make_targets())
    result = orch.run(['a'])
    assert result.winner is None
    assert result.rolled_back is False
    assert result.reason == 'all_failed'
    assert env.applied == ['a']


def test_apply_false_and_exception_are_recorded():
    env = FakeEnv({'good': all_ok(30)})

    def apply(preset_id):
        if preset_id == 'bad_apply':
            return False
        if preset_id == 'boom':
            raise RuntimeError('boom')
        return env.apply(preset_id)

    orch = Orchestrator(apply, env.probe, targets=make_targets())
    result = orch.run(['bad_apply', 'boom', 'good'])
    by_id = {r.preset_id: r for r in result.results}
    assert by_id['bad_apply'].ok_count == 0
    assert by_id['bad_apply'].error == 'apply returned False'
    assert 'boom' in by_id['boom'].error
    assert result.winner == 'good'


def test_history_written_and_best_ids(tmp_path):
    path = tmp_path / 'nested' / 'history.jsonl'
    store = HistoryStore(path)
    env = FakeEnv({
        'p1': {'youtube': [(True, 100)], 'discord': [(False, 9999)]},
        'p2': all_ok(50),
    })
    orch = Orchestrator(env.apply, env.probe, targets=make_targets(), history=store)
    result = orch.run(['p1', 'p2'])
    assert result.winner == 'p2'
    lines = path.read_text(encoding='utf-8').strip().splitlines()
    assert len(lines) == 2
    for line in lines:
        json.loads(line)
    records = store.load()
    assert [r.preset_id for r in records] == ['p1', 'p2']
    assert records[1].ok_count == 2
    assert records[1].per_target['youtube']['successes'] == 3
    assert store.best_preset_ids() == ['p2', 'p1']


def test_history_load_tolerates_broken_lines(tmp_path):
    path = tmp_path / 'history.jsonl'
    store = HistoryStore(path)
    path.write_text('not json\n{"preset_id": "x", "ok_count": 1, "total_targets": 2, "avg_latency_ms": 10, "timestamp": 1}\n', encoding='utf-8')
    records = store.load()
    assert len(records) == 1
    assert records[0].preset_id == 'x'
    assert HistoryStore(tmp_path / 'missing.jsonl').load() == []


def test_default_targets_match_engine_contract_markers():
    urls = [t.url for t in DEFAULT_TARGETS]
    assert 'https://www.youtube.com/generate_204' in urls
    assert 'https://redirector.googlevideo.com/report_mapping' in urls
    assert 'https://discord.com/api/v10/gateway' in urls
    assert 'https://rutracker.org' in urls
    assert not any('openai' in u for u in urls)


def test_targets_from_domains():
    targets = targets_from_domains(['youtube.com', 'https://discord.com/app', '', '  rutracker.org/forum '])
    assert [t.url for t in targets] == ['https://youtube.com', 'https://discord.com/app', 'https://rutracker.org/forum']
    assert [t.key for t in targets] == ['youtube_com', 'discord_com', 'rutracker_org']
    assert targets_from_domains(None) == []
    assert targets_from_domains([]) == []


def test_probe_tuple_and_bool_are_normalized():
    targets = [Target('only', 'Only', 'https://example.test')]
    orch = Orchestrator(lambda pid: True, lambda target: (True, 42), targets=targets, attempts=2, required_successes=2)
    result = orch.run(['x'])
    assert result.winner == 'x'
    assert result.best.avg_latency_ms == 42
    orch2 = Orchestrator(lambda pid: True, lambda target: False, targets=targets)
    assert orch2.run(['x']).winner is None


def test_invalid_parameters_raise():
    with pytest.raises(ValueError):
        Orchestrator(lambda p: True, lambda t: True, attempts=0)
    with pytest.raises(ValueError):
        Orchestrator(lambda p: True, lambda t: True, attempts=3, required_successes=0)
    with pytest.raises(ValueError):
        Orchestrator(lambda p: True, lambda t: True, attempts=3, required_successes=4)


def test_pause_resume_stop_flags():
    orch = Orchestrator(lambda p: True, lambda t: True, targets=make_targets())
    assert not orch.is_paused and not orch.is_stopped
    orch.pause()
    assert orch.is_paused
    orch.resume()
    assert not orch.is_paused
    orch.pause()
    orch.stop()
    assert orch.is_stopped
    assert not orch.is_paused


def test_preset_result_score_ordering():
    more_ok = PresetResult('a', 2, 2, 500)
    fewer_ok = PresetResult('b', 1, 2, 10)
    faster = PresetResult('c', 2, 2, 50)
    assert more_ok.score > fewer_ok.score
    assert faster.score > more_ok.score
    assert more_ok.stable_ratio == 1.0
    assert fewer_ok.stable_ratio == 0.5
