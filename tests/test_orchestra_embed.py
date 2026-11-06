#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for OrchestraWidget embedding into Zapret GUI main window (Stage 4 / Prompt 4).

Verifies:
- Creation of the orchestra page container with fake app and real Zapret2App instance
- Forwarding of apply_preset (using EngineParams.from_app + run_engine) and probe (http_probe)
- Safe operation in absence of root privileges and absence of network / D-Bus
- UI state updates on winner application (top_tile_preset, pill_preset, combo_engine_mode, config, status)
- Navigation from BlockCheck to Orchestra page
"""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

import main
from main import Zapret2App
from orchestra_ui import (
    OrchestraWidget,
    create_orchestra_page,
    NetworkManagerMonitor,
    NetworkConnectionInfo,
    http_probe,
)
from orchestra.orchestrator import OrchestratorResult, PresetResult
from orchestra.targets import Target, ProbeResult


@pytest.fixture
def fake_app():
    """Builds a lightweight fake app matching Zapret2App attributes."""
    app = SimpleNamespace(
        active_preset="general",
        active_iface="any",
        active_dns="cloudflare",
        enable_ai_hosts=True,
        enable_quic=True,
        enable_discord_voice=True,
        conntrack_limit=12,
        hostlist_mode="all_except_exclude",
        engine_mode="nfqws2",
        custom_params="",
        zapret2_preset="Default (circular)",
        enable_youtube=True,
        enable_discord_tcp=True,
        enable_general_https=True,
        top_tile_preset=MagicMock(),
        pill_preset=MagicMock(),
        combo_engine_mode=MagicMock(),
        save_config=MagicMock(),
        refresh_status=MagicMock(),
        update_top_tile_mode=MagicMock(),
        persistent_bar=MagicMock(),
        zapret2_page=SimpleNamespace(preset_id="Default (circular)", refresh_catalog=MagicMock()),
    )
    return app


def test_create_orchestra_page_with_fake_app(fake_app, tmp_path):
    """Checks create_orchestra_page factory with a fake app."""
    dummy_history = tmp_path / "test_history.jsonl"
    scrolled, widget = create_orchestra_page(
        app=fake_app,
        settle_s=0.0,
    )

    assert isinstance(scrolled, Gtk.ScrolledWindow)
    assert isinstance(widget, OrchestraWidget)
    assert widget.app is fake_app
    assert callable(widget.apply_preset_fn)
    assert widget.probe_fn == http_probe

    # Cleanup timer
    if widget.network_monitor:
        widget.network_monitor.stop_monitoring()


def test_app_create_orchestra_page_embed_and_navigation(fake_app, monkeypatch):
    """Checks Zapret2App.create_orchestra_page method and navigation wiring."""
    captured_runs = []
    monkeypatch.setattr(main, "run_engine", lambda *args: captured_runs.append(args) or SimpleNamespace(returncode=0))

    scrolled = Zapret2App.create_orchestra_page(fake_app)
    assert isinstance(scrolled, Gtk.ScrolledWindow)
    assert hasattr(fake_app, "orchestra_widget")
    assert isinstance(fake_app.orchestra_widget, OrchestraWidget)
    assert fake_app.orchestra_widget.probe_fn == http_probe

    # Check apply_preset_fn forwards to apply_orchestra_preset using EngineParams
    ok = fake_app.orchestra_widget.apply_preset_fn("test_winner_preset")
    assert ok is True
    assert len(captured_runs) == 1
    argv = captured_runs[0]
    assert argv[0] == "start"
    assert argv[9] == "nfqws2"
    assert argv[11] == "test_winner_preset"

    # Test open_orchestra_page navigation
    mock_nav_btn = MagicMock()
    fake_app.nav_buttons = {"orchestra": mock_nav_btn}
    Zapret2App.open_orchestra_page(fake_app)
    mock_nav_btn.set_active.assert_called_with(True)

    # Cleanup timer
    if fake_app.orchestra_widget.network_monitor:
        fake_app.orchestra_widget.network_monitor.stop_monitoring()


def test_apply_orchestra_preset_legacy_nfqws(fake_app, monkeypatch):
    """Verifies apply_orchestra_preset when engine_mode is legacy nfqws."""
    fake_app.engine_mode = "nfqws"
    fake_app.active_preset = "general"
    captured_runs = []
    monkeypatch.setattr(main, "run_engine", lambda *args: captured_runs.append(args) or SimpleNamespace(returncode=0))

    ok = Zapret2App.apply_orchestra_preset(fake_app, "youtube_discord")
    assert ok is True
    assert len(captured_runs) == 1
    argv = captured_runs[0]
    assert argv[0] == "start"
    assert argv[1] == "youtube_discord"
    assert argv[9] == "nfqws"


def test_on_orchestra_winner_applied_updates_ui_and_config(fake_app):
    """Verifies that on_orchestra_winner_applied refreshes all UI components."""
    fake_app.engine_mode = "nfqws2"
    Zapret2App.on_orchestra_winner_applied(fake_app, "winner_zapret2_preset")

    assert fake_app.zapret2_preset == "winner_zapret2_preset"
    assert fake_app.engine_mode == "nfqws2"
    fake_app.top_tile_preset.set_text.assert_called_with("winner_zapret2_preset")
    fake_app.pill_preset.set_text.assert_called_with("⚡ winner_zapret2_preset")
    fake_app.combo_engine_mode.set_active_id.assert_called_with("nfqws2")
    assert fake_app.zapret2_page.preset_id == "winner_zapret2_preset"
    fake_app.zapret2_page.refresh_catalog.assert_called()
    fake_app.save_config.assert_called()
    fake_app.refresh_status.assert_called()
    fake_app.update_top_tile_mode.assert_called()
    fake_app.persistent_bar.update_preset.assert_called_with("winner_zapret2_preset")


def test_widget_apply_winner_triggers_app_updates(fake_app, monkeypatch):
    """Tests that OrchestraWidget.apply_winner calls app notification handler."""
    captured_runs = []
    monkeypatch.setattr(main, "run_engine", lambda *args: captured_runs.append(args) or SimpleNamespace(returncode=0))

    fake_app.apply_orchestra_preset = lambda pid: Zapret2App.apply_orchestra_preset(fake_app, pid)
    fake_app.on_orchestra_winner_applied = lambda wid: Zapret2App.on_orchestra_winner_applied(fake_app, wid)

    scrolled = Zapret2App.create_orchestra_page(fake_app)
    widget = fake_app.orchestra_widget

    # Set mock outcome
    widget.latest_result = OrchestratorResult(
        winner="winner_preset_xyz",
        best=PresetResult(preset_id="winner_preset_xyz", ok_count=3, total_targets=3, avg_latency_ms=42),
    )

    applied = widget.apply_winner()
    assert applied is True
    assert fake_app.zapret2_preset == "winner_preset_xyz"
    fake_app.top_tile_preset.set_text.assert_called_with("winner_preset_xyz")
    fake_app.pill_preset.set_text.assert_called_with("⚡ winner_preset_xyz")
    fake_app.save_config.assert_called()

    # Cleanup timer
    if widget.network_monitor:
        widget.network_monitor.stop_monitoring()


def test_absence_of_network_and_root(tmp_path, fake_app):
    """
    Checks that OrchestraWidget and NetworkManagerMonitor function properly
    without root privileges and when network / D-Bus is completely absent.
    """
    # 1. Ensure non-root execution safety
    assert os.geteuid() != 0, "Test should run in non-root user mode"

    # 2. Simulate empty / missing /proc/net/route and failed D-Bus
    empty_route_file = tmp_path / "empty_route"
    empty_route_file.write_text("Iface\tDestination\tGateway\n", encoding="utf-8")

    with patch("orchestra_ui.HAS_GIO", False), patch("orchestra_ui.HAS_DBUS", False):
        mon = NetworkManagerMonitor(route_file=str(empty_route_file))
        info = mon.get_active_connection()
        assert info.is_connected is False
        assert info.interface == ""
        assert info.gateway == ""
        assert info.summary() == "Нет подключения"

        # Create widget with this disconnected monitor
        targets = [Target("test", "Test", "http://fake.test")]
        widget = OrchestraWidget(
            app=fake_app,
            network_monitor=mon,
            apply_preset=lambda pid: True,
            probe=lambda tgt: ProbeResult(target_key=tgt.key, ok=False, latency_ms=0, error="Network is unreachable"),
            targets=targets,
            settle_s=0.0,
        )

        assert widget.is_running is False
        assert widget.network_banner_box.get_visible() is False

        # Run autotune when all probes fail (no network)
        candidates = ["preset_fail1"]
        widget.start_autotune(candidates)

        assert widget._worker_thread is not None
        widget._worker_thread.join(timeout=3.0)

        while GLib.main_context_default().pending():
            GLib.main_context_default().iteration(False)

        assert widget.is_running is False
        assert widget.latest_result is not None
        assert widget.latest_result.winner is None
        assert widget.btn_apply_winner.get_sensitive() is False
        assert "Все пресеты провалили проверку" in widget.lbl_status.get_text() or "провалили" in widget.lbl_status.get_label()

        mon.stop_monitoring()


def test_stack_contains_orchestra_page_in_real_app(monkeypatch):
    """Smoke test ensuring Zapret2App stack has 'orchestra' registered."""
    monkeypatch.setattr("main.MirrorHealthMonitor", MagicMock())
    monkeypatch.setattr("main.get_healer", MagicMock())
    monkeypatch.setattr("main.subprocess.run", lambda *a, **k: MagicMock(returncode=0, stdout="INACTIVE\n"))

    app = Zapret2App(minimized=True)
    child = app.stack.get_child_by_name("orchestra")
    assert child is not None, "orchestra page not found in Zapret2App stack"
    assert isinstance(child, Gtk.Widget)
    assert "orchestra" in app.nav_buttons

    if hasattr(app, "orchestra_widget") and app.orchestra_widget.network_monitor:
        app.orchestra_widget.network_monitor.stop_monitoring()
    if hasattr(app, "mirror_monitor"):
        try:
            app.mirror_monitor.stop()
        except Exception:
            pass
    app.destroy()
