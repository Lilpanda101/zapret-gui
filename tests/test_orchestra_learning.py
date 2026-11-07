#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Orchestra Circular Learning system:
- Strategy lock on target after 3 successes in a row
- Strategy unlock after 2 failures in a row
- Blocked strategies handling
- Subdomain grouping (e.g. *.googlevideo.com -> googlevideo.com)
- Russian white domains filter (*.ru, vk.com, etc. are not intercepted)
- Stop and time budget do not corrupt learning statistics
- Reset learning clears locks/blocks while preserving HistoryStore run history
- Learned preset generation does not touch built-in presets/
- OrchestraWidget integration: display of locked/blocked counts and reset button
"""
import os
from pathlib import Path
import threading
import time

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
import pytest

from orchestra.learning import (
    LearningStore,
    TargetStrategyStat,
    group_subdomains,
    is_russian_white_domain,
    is_ignored_target,
    DEFAULT_IGNORED_TARGETS,
)
from orchestra.history import HistoryStore, RunRecord
from orchestra.orchestrator import Orchestrator, TargetResult, PresetResult
from orchestra.targets import Target
from orchestra_ui import OrchestraWidget


def test_subdomain_grouping():
    assert group_subdomains("rr1---sn-xxx.googlevideo.com") == "googlevideo.com"
    assert group_subdomains("https://i.ytimg.com/vi/123/hqdefault.jpg") == "youtube.com"
    assert group_subdomains("youtu.be") == "youtube.com"
    assert group_subdomains("sub.discord.gg") == "discord.com"
    assert group_subdomains("gateway.discord.gg") == "discord.com"
    assert group_subdomains("sub.example.com") == "example.com"
    assert group_subdomains("rutracker.org") == "rutracker.org"


def test_russian_white_domains_filter():
    # Russian TLDs and major portals are white-listed
    assert is_russian_white_domain("ya.ru") is True
    assert is_russian_white_domain("yandex.ru") is True
    assert is_russian_white_domain("vk.com") is True
    assert is_russian_white_domain("https://sub.vk.com/feed") is True
    assert is_russian_white_domain("gosuslugi.ru") is True
    assert is_russian_white_domain("site.xn--p1ai") is True
    assert is_russian_white_domain("community.su") is True
    assert is_russian_white_domain("rutube.ru") is True

    # International / blocked targets are not white-listed
    assert is_russian_white_domain("rutracker.org") is False
    assert is_russian_white_domain("youtube.com") is False
    assert is_russian_white_domain("googlevideo.com") is False
    assert is_russian_white_domain("discord.com") is False


def test_ignored_targets():
    for relay in DEFAULT_IGNORED_TARGETS:
        assert is_ignored_target(relay) is True
    assert is_ignored_target("youtube.com") is False
    assert is_ignored_target("custom.relay.local", custom_ignored={"custom.relay.local"}) is True


def test_strategy_lock_after_three_successes(tmp_path):
    store = LearningStore(tmp_path / "learning.json")

    # Attempt 1: success
    s1 = store.record_attempt("sub.googlevideo.com", "strategy_a", success=True)
    assert s1.consecutive_successes == 1
    assert s1.locked is False

    # Attempt 2: success
    s2 = store.record_attempt("rr2---sn.googlevideo.com", "strategy_a", success=True)
    assert s2.consecutive_successes == 2
    assert s2.locked is False

    # Attempt 3: success -> LOCK
    s3 = store.record_attempt("googlevideo.com", "strategy_a", success=True)
    assert s3.consecutive_successes == 3
    assert s3.locked is True

    locked = store.get_locked_strategies()
    assert locked.get("googlevideo.com") == "strategy_a"


def test_strategy_unlock_after_two_failures(tmp_path):
    store = LearningStore(tmp_path / "learning.json")

    # Lock strategy_a with 3 successes
    for _ in range(3):
        store.record_attempt("googlevideo.com", "strategy_a", success=True)
    assert store.get_locked_strategies().get("googlevideo.com") == "strategy_a"

    # Failure 1: still locked
    f1 = store.record_attempt("googlevideo.com", "strategy_a", success=False)
    assert f1.consecutive_failures == 1
    assert f1.locked is True
    assert store.get_locked_strategies().get("googlevideo.com") == "strategy_a"

    # Failure 2: UNLOCK
    f2 = store.record_attempt("googlevideo.com", "strategy_a", success=False)
    assert f2.consecutive_failures == 2
    assert f2.locked is False
    assert "googlevideo.com" not in store.get_locked_strategies()


def test_blocked_strategy_handling(tmp_path):
    store = LearningStore(tmp_path / "learning.json")

    store.block_strategy("youtube.com", "pass_v1")
    assert store.is_strategy_blocked("youtube.com", "pass_v1") is True
    assert store.is_strategy_blocked("i.ytimg.com", "pass_v1") is True
    assert store.is_strategy_blocked("youtube.com", "alt_v2") is False

    # Unblock strategy
    store.unblock_strategy("youtube.com", "pass_v1")
    assert store.is_strategy_blocked("youtube.com", "pass_v1") is False


def test_stop_and_budget_do_not_corrupt_stats(tmp_path):
    store = LearningStore(tmp_path / "learning.json")

    # Pre-lock strategy_a on googlevideo.com
    for _ in range(3):
        store.record_attempt("googlevideo.com", "strategy_a", success=True)
    assert store.get_locked_strategies().get("googlevideo.com") == "strategy_a"

    # Set up orchestrator with early stop
    targets = [Target("gv", "GoogleVideo", "https://googlevideo.com")]
    
    def fake_apply(pid):
        return True

    def slow_probe(t):
        time.sleep(0.01)
        return False, 9999

    orc = Orchestrator(
        apply_preset=fake_apply,
        probe=slow_probe,
        targets=targets,
        attempts=5,
        required_successes=3,
        learning_store=store,
    )

    # Trigger stop immediately
    orc.stop()
    outcome = orc.run(["strategy_a"])
    assert outcome.stopped is True

    # Check that mid-run stop did not register as 2 consecutive failures and did not unlock!
    stat = store.get_stats().get(("googlevideo.com", "strategy_a"))
    assert stat is not None
    assert stat.locked is True
    assert stat.consecutive_failures < 2


def test_reset_learning_preserves_history_store(tmp_path):
    history_file = tmp_path / "history.jsonl"
    learning_file = tmp_path / "learning.json"
    learned_preset_file = tmp_path / "learned_preset.conf"

    history = HistoryStore(history_file)
    for i in range(5):
        history.append(RunRecord(preset_id=f"preset_{i}", ok_count=2, total_targets=3, avg_latency_ms=100))
    assert len(history.load(limit=0)) == 5

    learning = LearningStore(learning_file, learned_preset_path=learned_preset_file)
    for _ in range(3):
        learning.record_attempt("googlevideo.com", "strat_lock", success=True)
    learning.block_strategy("discord.com", "bad_strat")
    learning.save()
    learning.export_learned_preset()

    assert len(learning.get_locked_strategies()) == 1
    assert learned_preset_file.exists()

    # Reset learning
    learning.reset_learning()

    # Learning is reset
    assert len(learning.get_locked_strategies()) == 0
    assert len(learning.get_blocked_strategies()) == 0

    # HistoryStore run records are PRESERVED!
    assert len(history.load(limit=0)) == 5


def test_learned_preset_does_not_touch_builtin_presets(tmp_path):
    builtin_dir = Path(__file__).parent.parent / "zapret2" / "presets"
    before_mtimes = {}
    if builtin_dir.exists():
        for p in builtin_dir.rglob("*.txt"):
            before_mtimes[p] = p.stat().st_mtime

    learned_conf = tmp_path / "user_learned.conf"
    store = LearningStore(tmp_path / "learn.json", learned_preset_path=learned_conf)
    for _ in range(3):
        store.record_attempt("googlevideo.com", "flowseal_alt3", success=True)
    for _ in range(3):
        store.record_attempt("discord.com", "multidisorder_voice", success=True)

    out = store.export_learned_preset()
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "target: googlevideo.com => strategy: flowseal_alt3" in content
    assert "target: discord.com => strategy: multidisorder_voice" in content
    assert "Встроенные пресеты не изменены" in content

    # Verify builtin presets untouched
    if builtin_dir.exists():
        for p, mtime in before_mtimes.items():
            assert p.stat().st_mtime == mtime, f"Preset {p} was modified!"


def test_orchestra_widget_learning_ui(tmp_path):
    store = LearningStore(tmp_path / "ui_learning.json")
    for _ in range(3):
        store.record_attempt("googlevideo.com", "locked_test", success=True)
    store.block_strategy("discord.com", "blocked_test")

    widget = OrchestraWidget(
        learning_store=store,
        targets=[Target("gv", "GV", "https://googlevideo.com")],
    )

    assert "Зафиксировано (Locked): 1" in widget.lbl_locked_strategies.get_text()
    assert "Заблокировано (Blocked): 1" in widget.lbl_blocked_strategies.get_text()

    # Click reset learning
    widget.reset_learning()
    assert "Зафиксировано (Locked): 0" in widget.lbl_locked_strategies.get_text()
    assert "Заблокировано (Blocked): 0" in widget.lbl_blocked_strategies.get_text()
    assert len(store.get_locked_strategies()) == 0


def test_auto_blocking_after_consecutive_failures(tmp_path):
    store = LearningStore(tmp_path / "learning.json")

    # 4 failures: not blocked yet
    for _ in range(4):
        store.record_attempt("youtube.com", "broken_strategy", success=False)
    assert store.is_strategy_blocked("youtube.com", "broken_strategy") is False
    assert len(store.get_blocked_strategies("youtube.com")["youtube.com"]) == 0

    # 5th failure: triggers BLOCK_FAILURE_THRESHOLD (5)
    store.record_attempt("youtube.com", "broken_strategy", success=False)
    assert store.is_strategy_blocked("youtube.com", "broken_strategy") is True
    assert "broken_strategy" in store.get_blocked_strategies("youtube.com")["youtube.com"]

    # Subdomains of youtube.com also consider it blocked
    assert store.is_strategy_blocked("i.ytimg.com", "broken_strategy") is True

    # Reset learning clears auto-blocked strategies
    store.reset_learning()
    assert store.is_strategy_blocked("youtube.com", "broken_strategy") is False


def test_single_learning_store_shared_between_widget_and_app(tmp_path):
    import main

    class FakeAppWithLearning(Gtk.Window):
        def __init__(self):
            super().__init__()
            self.learning_store = LearningStore(tmp_path / "shared_learning.json")
            self.engine_mode = "nfqws2"
            self.zapret2_preset = "general"
            self.active_iface = "any"

        def create_orchestra_page(self, **kwargs):
            return main.Zapret2App.create_orchestra_page(self, **kwargs)

    app = FakeAppWithLearning()
    scrolled = app.create_orchestra_page()
    assert hasattr(app, "orchestra_widget")

    # Verify that widget uses the exact same instance (is check)
    assert app.orchestra_widget.learning_store is app.learning_store

    # Test that recording in app learning_store reflects in widget without restart
    for _ in range(3):
        app.learning_store.record_attempt("googlevideo.com", "flowseal_win", success=True)
    app.orchestra_widget.update_learning_ui()

    assert "Зафиксировано (Locked): 1" in app.orchestra_widget.lbl_locked_strategies.get_text()
    assert "Карта обучения: learned_rules.conf" in app.orchestra_widget.lbl_learned_rules.get_text()


def test_learned_rules_export_file_and_ui_naming(tmp_path):
    store = LearningStore(tmp_path / "learning.json")
    for _ in range(3):
        store.record_attempt("googlevideo.com", "strategy_win", success=True)

    out = store.export_learned_rules()
    assert out.name == "learned_rules.conf"
    assert out.exists()
    content = out.read_text(encoding="utf-8")
    assert "Карта стратегий обучения (Target => Strategy)" in content
    assert "target: googlevideo.com => strategy: strategy_win" in content
