#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Preset orchestrator: tries candidates, scores them, rolls back on total failure.

apply_preset(preset_id) and probe(target) are injected, so tests run fully
with fakes: no root, no nft, no network.
"""
from __future__ import annotations
import threading
import time
from dataclasses import dataclass, field
from typing import Tuple

from .history import RunRecord
from .targets import default_targets


@dataclass(frozen=True)
class TargetResult:
    target_key: str
    attempts: int
    successes: int
    stable: bool
    avg_latency_ms: int


@dataclass(frozen=True)
class PresetResult:
    preset_id: str
    ok_count: int
    total_targets: int
    avg_latency_ms: int
    per_target: Tuple[TargetResult, ...] = ()
    error: str = ''

    @property
    def stable_ratio(self):
        return (self.ok_count / self.total_targets) if self.total_targets else 0.0

    @property
    def score(self):
        return (self.ok_count, self.stable_ratio, -self.avg_latency_ms)


@dataclass
class OrchestratorResult:
    winner: str | None
    best: PresetResult | None
    results: list = field(default_factory=list)
    completed: bool = False
    stopped: bool = False
    rolled_back: bool = False
    reason: str = ''


def _normalize_probe(raw):
    if hasattr(raw, 'ok'):
        return bool(raw.ok), int(getattr(raw, 'latency_ms', 9999))
    if isinstance(raw, (tuple, list)) and len(raw) >= 2:
        return bool(raw[0]), int(raw[1])
    if isinstance(raw, bool):
        return raw, 0 if raw else 9999
    return False, 9999


class Orchestrator:
    def __init__(self, apply_preset, probe, targets=None, attempts=3, required_successes=2, batch_size=12, time_budget_s=None, settle_s=0.0, history=None, on_progress=None, time_fn=time.time, sleep_fn=time.sleep):
        if attempts < 1:
            raise ValueError('attempts must be >= 1')
        if not 1 <= required_successes <= attempts:
            raise ValueError('required_successes must be within 1..attempts')
        self.apply_preset = apply_preset
        self.probe = probe
        self.targets = list(targets) if targets is not None else default_targets()
        self.attempts = attempts
        self.required_successes = required_successes
        self.batch_size = max(1, int(batch_size))
        self.time_budget_s = time_budget_s
        self.settle_s = settle_s
        self.history = history
        self.on_progress = on_progress
        self._time_fn = time_fn
        self._sleep_fn = sleep_fn
        self._stop = threading.Event()
        self._pause = threading.Event()

    def stop(self):
        self._stop.set()
        self._pause.clear()

    def pause(self):
        self._pause.set()

    def resume(self):
        self._pause.clear()

    @property
    def is_paused(self):
        return self._pause.is_set()

    @property
    def is_stopped(self):
        return self._stop.is_set()

    def _wait_if_paused(self):
        while self._pause.is_set() and not self._stop.is_set():
            self._sleep_fn(0.05)

    def _budget_exceeded(self, started):
        return self.time_budget_s is not None and (self._time_fn() - started) > self.time_budget_s

    def _test_preset(self, preset_id):
        per_target = []
        ok_count = 0
        latencies = []
        for target in self.targets:
            successes = 0
            target_latencies = []
            for _ in range(self.attempts):
                if self._stop.is_set():
                    break
                try:
                    ok, latency = _normalize_probe(self.probe(target))
                except Exception:
                    ok, latency = False, 9999
                if ok:
                    successes += 1
                    target_latencies.append(latency)
            stable = successes >= self.required_successes
            if stable:
                ok_count += 1
                latencies.extend(target_latencies)
            avg_target = int(sum(target_latencies) / len(target_latencies)) if target_latencies else 9999
            per_target.append(TargetResult(target.key, self.attempts, successes, stable, avg_target))
        avg_latency = int(sum(latencies) / len(latencies)) if latencies else 9999
        return PresetResult(preset_id, ok_count, len(self.targets), avg_latency, tuple(per_target), '')

    def run(self, candidates, previous_preset=None):
        candidates = list(candidates or [])
        started = self._time_fn()
        results = []
        self.results = results
        self.last_preset_result = None
        best = None
        stopped = False
        reason = ''
        for index, preset_id in enumerate(candidates):
            if self._stop.is_set():
                stopped = True
                reason = 'stopped'
                break
            self._wait_if_paused()
            if self._stop.is_set():
                stopped = True
                reason = 'stopped'
                break
            if self._budget_exceeded(started):
                reason = 'budget'
                break
            try:
                applied = self.apply_preset(preset_id)
                if applied is False:
                    result = PresetResult(preset_id, 0, len(self.targets), 9999, (), 'apply returned False')
                else:
                    if self.settle_s:
                        self._sleep_fn(self.settle_s)
                    result = self._test_preset(preset_id)
            except Exception as exc:
                result = PresetResult(preset_id, 0, len(self.targets), 9999, (), str(exc))
            results.append(result)
            self.last_preset_result = result
            if self.history is not None:
                try:
                    self.history.append(RunRecord.from_result(result))
                except Exception:
                    pass
            if best is None or result.score > best.score:
                best = result
            if self.on_progress is not None:
                try:
                    self.on_progress(index + 1, len(candidates), preset_id, best)
                except Exception:
                    pass
        winner = best.preset_id if best is not None and best.ok_count > 0 else None
        rolled_back = False
        if winner is None:
            if previous_preset:
                try:
                    self.apply_preset(previous_preset)
                    rolled_back = True
                except Exception:
                    rolled_back = False
                reason = reason or 'all_failed_rolled_back' if rolled_back else 'all_failed'
            else:
                reason = reason or 'all_failed'
        elif results and results[-1].preset_id != winner:
            try:
                self.apply_preset(winner)
            except Exception:
                pass
        completed = (not stopped) and reason != 'budget' and len(results) == len(candidates)
        return OrchestratorResult(winner, best, results, completed, stopped, rolled_back, reason)
