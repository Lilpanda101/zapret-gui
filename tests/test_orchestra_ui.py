#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Unit tests for orchestra_ui module:
- NetworkConnectionInfo and summary
- /proc/net/route parser and safe fallback
- NetworkManagerMonitor (D-Bus, Gio, fallback, change detection)
- Preset recommendation and extraction helpers
- Target metric formatting
- OrchestraWidget UI, state transitions, auto-tuning workflow, pause/resume, stop,
  apply winner, network change alert banner, cache reset
- OrchestraDialog and create_orchestra_page
"""

from __future__ import annotations
import os
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

import orchestra_ui
from orchestra_ui import (
    NetworkConnectionInfo,
    NetworkManagerMonitor,
    OrchestraWidget,
    OrchestraDialog,
    create_orchestra_page,
    read_proc_net_route,
    get_wifi_ssid_fallback,
    get_top_recommended_presets,
    get_all_catalog_presets,
    format_target_status,
    extract_target_metrics,
    clear_history_store,
    is_display_available,
)
from orchestra.targets import Target, ProbeResult
from orchestra.orchestrator import PresetResult, TargetResult, OrchestratorResult
from orchestra.history import HistoryStore
from catalog.preset_catalog import PresetCatalog, PresetEntry


# ============================================================================
# 1. NetworkConnectionInfo & Network Helpers Tests
# ============================================================================

def test_network_connection_info_defaults_and_summary():
    empty_info = NetworkConnectionInfo()
    assert empty_info.id == ""
    assert empty_info.is_connected is False
    assert empty_info.summary() == "Нет подключения"

    wifi_info = NetworkConnectionInfo(
        id="Home_Network",
        uuid="1111-2222-3333",
        conn_type="802-11-wireless",
        ssid="Home_WiFi",
        gateway="192.168.1.1",
        interface="wlan0",
        is_connected=True,
    )
    assert wifi_info.is_connected is True
    summary = wifi_info.summary()
    assert "Home_WiFi" in summary
    assert "wlan0" in summary
    assert "192.168.1.1" in summary

    eth_info = NetworkConnectionInfo(
        id="Ethernet 1",
        interface="eth0",
        gateway="10.0.0.1",
        is_connected=True,
    )
    assert eth_info.summary() == "Ethernet 1 (eth0) шлюз: 10.0.0.1"


def test_read_proc_net_route_success(tmp_path):
    route_file = tmp_path / "route"
    # Destination 00000000, Gateway 0102A8C0 -> 192.168.2.1
    route_content = (
        "Iface\tDestination\tGateway \tFlags\tRefCnt\tUse\tMetric\tMask\t\tMTU\tWindow\tIRTT\n"
        "enp5s0\t00000000\t0102A8C0\t0003\t0\t0\t100\t00000000\t0\t0\t0\n"
        "enp5s0\t0002A8C0\t00000000\t0001\t0\t0\t100\t00FFFFFF\t0\t0\t0\n"
    )
    route_file.write_text(route_content, encoding="utf-8")

    iface, gw = read_proc_net_route(str(route_file))
    assert iface == "enp5s0"
    assert gw == "192.168.2.1"


def test_read_proc_net_route_no_default_or_missing(tmp_path):
    # Non-existent file
    iface, gw = read_proc_net_route(str(tmp_path / "non_existent"))
    assert iface == ""
    assert gw == ""

    # File without default route
    no_default = tmp_path / "route_no_def"
    no_default.write_text(
        "Iface\tDestination\tGateway \neth0\t0002A8C0\t00000000\n",
        encoding="utf-8",
    )
    iface, gw = read_proc_net_route(str(no_default))
    assert iface == ""
    assert gw == ""


def test_get_wifi_ssid_fallback():
    with patch("orchestra_ui.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="MyHomeSSID\n")
        assert get_wifi_ssid_fallback("wlan0") == "MyHomeSSID"
        mock_run.assert_called_once_with(["iwgetid", "-r", "wlan0"], capture_output=True, text=True, timeout=1.0)

    # Subprocess failure
    with patch("orchestra_ui.subprocess.run", side_effect=Exception("command not found")):
        assert get_wifi_ssid_fallback("wlan0") == ""


# ============================================================================
# 2. NetworkManagerMonitor Tests
# ============================================================================

def test_nm_monitor_has_changed():
    mon = NetworkManagerMonitor(route_file="/nonexistent")

    # None handling
    assert mon.has_changed(None, None) is False
    c1 = NetworkConnectionInfo(id="NetA", ssid="NetA", gateway="192.168.1.1", is_connected=True)
    assert mon.has_changed(c1, None) is False
    assert mon.has_changed(None, c1) is False

    # Identical
    c2 = NetworkConnectionInfo(id="NetA", ssid="NetA", gateway="192.168.1.1", is_connected=True)
    assert mon.has_changed(c1, c2) is False

    # SSID changed
    c3 = NetworkConnectionInfo(id="NetB", ssid="NetB", gateway="192.168.1.1", is_connected=True)
    assert mon.has_changed(c1, c3) is True

    # Gateway changed
    c4 = NetworkConnectionInfo(id="NetA", ssid="NetA", gateway="10.0.0.1", is_connected=True)
    assert mon.has_changed(c1, c4) is True

    # Connection status changed
    c5 = NetworkConnectionInfo(id="NetA", ssid="NetA", gateway="192.168.1.1", is_connected=False)
    assert mon.has_changed(c1, c5) is True


def test_nm_monitor_gio_mocked():
    with patch("orchestra_ui.HAS_GIO", True), \
         patch("orchestra_ui.Gio.bus_get_sync") as mock_bus_sync, \
         patch("orchestra_ui.Gio.DBusProxy.new_sync") as mock_proxy_sync:

        mock_nm_proxy = MagicMock()
        mock_nm_proxy.get_cached_property.return_value.unpack.return_value = "/org/freedesktop/NetworkManager/ActiveConnection/1"

        mock_conn_proxy = MagicMock()
        def conn_cached(prop):
            val = MagicMock()
            if prop == "Id":
                val.unpack.return_value = "Test_WiFi"
            elif prop == "Uuid":
                val.unpack.return_value = "uuid-1234"
            elif prop == "Type":
                val.unpack.return_value = "802-11-wireless"
            elif prop == "Devices":
                val.unpack.return_value = ["/org/freedesktop/NetworkManager/Devices/1"]
            elif prop == "Ip4Config":
                val.unpack.return_value = "/org/freedesktop/NetworkManager/IP4Config/1"
            return val
        mock_conn_proxy.get_cached_property.side_effect = conn_cached

        mock_dev_proxy = MagicMock()
        mock_dev_proxy.get_cached_property.return_value.unpack.return_value = "wlan0"

        mock_ip4_proxy = MagicMock()
        mock_ip4_proxy.get_cached_property.return_value.unpack.return_value = "192.168.1.1"

        def proxy_factory(bus, flags, info, name, path, iface, cancel):
            if path == "/org/freedesktop/NetworkManager":
                return mock_nm_proxy
            elif "ActiveConnection" in path:
                return mock_conn_proxy
            elif "Devices" in path:
                return mock_dev_proxy
            elif "IP4Config" in path:
                return mock_ip4_proxy
            return MagicMock()

        mock_proxy_sync.side_effect = proxy_factory

        mon = NetworkManagerMonitor(route_file="/nonexistent")
        info = mon._get_gio_nm_connection()

        assert info is not None
        assert info.ssid == "Test_WiFi"
        assert info.uuid == "uuid-1234"
        assert info.interface == "wlan0"
        assert info.gateway == "192.168.1.1"
        assert info.is_connected is True


def test_nm_monitor_fallback_on_dbus_failure(tmp_path):
    route_file = tmp_path / "route"
    route_file.write_text(
        "Iface\tDestination\tGateway \neth0\t00000000\t0101A8C0\n",
        encoding="utf-8",
    )

    with patch("orchestra_ui.HAS_GIO", True), \
         patch("orchestra_ui.Gio.bus_get_sync", side_effect=Exception("DBus connection failed")):

        mon = NetworkManagerMonitor(route_file=str(route_file))
        info = mon.get_active_connection()

        assert info.is_connected is True
        assert info.interface == "eth0"
        assert info.gateway == "192.168.1.1"


def test_nm_monitor_check_for_change_invokes_callback():
    callback_calls = []
    def on_change(old, new):
        callback_calls.append((old, new))

    mon = NetworkManagerMonitor(on_network_changed=on_change, route_file="/nonexistent")
    mon.current_connection = NetworkConnectionInfo(id="NetOld", gateway="192.168.1.1", is_connected=True)

    # Simulate get_active_connection returning new connection
    with patch.object(mon, "get_active_connection") as mock_get:
        new_conn = NetworkConnectionInfo(id="NetNew", gateway="10.0.0.1", is_connected=True)
        mock_get.return_value = new_conn

        res = mon.check_for_change()
        assert res is not None
        assert len(callback_calls) == 1
        assert callback_calls[0][0].id == "NetOld"
        assert callback_calls[0][1].id == "NetNew"
        assert mon.current_connection == new_conn


def test_nm_monitor_start_and_stop():
    mon = NetworkManagerMonitor(route_file="/nonexistent")
    with patch("orchestra_ui.GLib.timeout_add_seconds", return_value=42) as mock_timeout, \
         patch("orchestra_ui.GLib.source_remove") as mock_remove:

        mon.start_monitoring()
        assert mon._monitoring is True
        assert mon._timer_id == 42

        mon.stop_monitoring()
        assert mon._monitoring is False
        assert mon._timer_id is None
        mock_remove.assert_called_once_with(42)


# ============================================================================
# 3. Preset Selection & Formatting Tests
# ============================================================================

def test_get_top_recommended_and_all_presets():
    entries = [
        PresetEntry("general ALT.txt", "general ALT", None, False, ("recommended",), "general ALT"),
        PresetEntry("Default (circular) v2.txt", "Default (circular)", "v2", False, ("recommended", "circular"), "Default (circular) v2"),
        PresetEntry("general FAKE TLS AUTO v2.txt", "general FAKE TLS AUTO", "v2", False, ("recommended",), "general FAKE TLS AUTO v2"),
        PresetEntry("ALL TCP & UDP hostfakesplit.txt", "ALL TCP & UDP hostfakesplit", None, False, ("recommended",), "ALL TCP & UDP hostfakesplit"),
        PresetEntry("extra1.txt", "extra1", None, False, ("recommended",), "extra1"),
        PresetEntry("extra2.txt", "extra2", None, False, (), "extra2"),
    ]
    catalog = PresetCatalog(entries)

    top_presets = get_top_recommended_presets(catalog, limit=5)
    assert len(top_presets) == 5
    assert "general ALT.txt" in top_presets
    assert "extra1.txt" in top_presets

    all_presets = get_all_catalog_presets(catalog)
    assert len(all_presets) == 6

    # None catalog handling
    assert get_top_recommended_presets(None) == []
    assert get_all_catalog_presets(None) == []


def test_format_target_status_and_metrics():
    t_stable = TargetResult("youtube", attempts=3, successes=3, stable=True, avg_latency_ms=45)
    t_warn = TargetResult("discord", attempts=3, successes=1, stable=False, avg_latency_ms=120)
    t_fail = TargetResult("rutracker", attempts=3, successes=0, stable=False, avg_latency_ms=9999)

    assert format_target_status(t_stable) == "✓ 45 ms"
    assert format_target_status(t_warn) == "⚠ 120 ms"
    assert format_target_status(t_fail) == "✗ Сбой"
    assert format_target_status(None) == "—"

    yt, dc, rt = extract_target_metrics((t_stable, t_warn, t_fail))
    assert yt == "✓ 45 ms"
    assert dc == "⚠ 120 ms"
    assert rt == "✗ Сбой"


def test_clear_history_store(tmp_path):
    hist_file = tmp_path / "history.jsonl"
    hist_file.write_text("{\"test\": 1}\n")
    store = HistoryStore(hist_file)

    assert clear_history_store(store) is True
    assert not hist_file.exists()

    # None handling
    assert clear_history_store(None) is False


# ============================================================================
# 4. OrchestraWidget UI Tests
# ============================================================================

@pytest.fixture
def fake_environment(tmp_path):
    applied = []
    def fake_apply(preset_id):
        applied.append(preset_id)
        return True

    def fake_probe(target):
        if target.key == "rutracker":
            return False, 9999
        return True, 40

    targets = [
        Target("youtube", "YouTube", "http://fake.test/yt"),
        Target("discord", "Discord", "http://fake.test/dc"),
        Target("rutracker", "RuTracker", "http://fake.test/rt"),
    ]

    hist_file = tmp_path / "test_hist.jsonl"
    hist_store = HistoryStore(hist_file)

    return {
        "apply": fake_apply,
        "probe": fake_probe,
        "targets": targets,
        "applied": applied,
        "history": hist_store,
    }


def test_orchestra_widget_init(fake_environment):
    widget = OrchestraWidget(
        apply_preset=fake_environment["apply"],
        probe=fake_environment["probe"],
        targets=fake_environment["targets"],
        history=fake_environment["history"],
        settle_s=0.0,
    )

    assert isinstance(widget, Gtk.Box)
    assert widget.btn_run.get_sensitive() is True
    assert widget.btn_quick.get_sensitive() is True
    assert widget.btn_full.get_sensitive() is True
    assert widget.btn_pause_resume.get_sensitive() is False
    assert widget.btn_stop.get_sensitive() is False
    assert widget.btn_apply_winner.get_sensitive() is False
    assert widget.network_banner_box.get_visible() is False
    assert len(widget.tree_view.get_columns()) == 7


def test_orchestra_widget_autotune_workflow(fake_environment):
    widget = OrchestraWidget(
        apply_preset=fake_environment["apply"],
        probe=fake_environment["probe"],
        targets=fake_environment["targets"],
        history=fake_environment["history"],
        settle_s=0.0,
    )

    candidates = ["preset_a.txt", "preset_b.txt"]
    widget.start_autotune(candidates)

    # Wait for background thread
    assert widget._worker_thread is not None
    widget._worker_thread.join(timeout=5.0)

    # Flush GTK main loop idle handlers
    while GLib.main_context_default().pending():
        GLib.main_context_default().iteration(False)

    assert widget.is_running is False
    assert widget.latest_result is not None
    assert widget.latest_result.winner in candidates

    # Winner button enabled and can be applied
    assert widget.btn_apply_winner.get_sensitive() is True
    applied_ok = widget.apply_winner()
    assert applied_ok is True
    assert widget.latest_result.winner in fake_environment["applied"]

    # Check ListStore populated
    assert len(widget.list_store) == 2
    row0 = list(widget.list_store[0])
    # Columns: [name, yt, dc, rt, lat, targets_ok, verdict, id, score]
    assert row0[0] in candidates
    assert "✓ 40 ms" in row0[1] # YouTube
    assert "✓ 40 ms" in row0[2] # Discord
    assert "✗ Сбой" in row0[3]  # RuTracker


def test_orchestra_widget_pause_resume_stop(fake_environment):
    widget = OrchestraWidget(
        apply_preset=fake_environment["apply"],
        probe=fake_environment["probe"],
        targets=fake_environment["targets"],
        settle_s=0.0,
    )

    # Fake orchestrator
    mock_orchestrator = MagicMock()
    mock_orchestrator.is_paused = False
    widget.orchestrator = mock_orchestrator

    # Pause
    widget.toggle_pause()
    mock_orchestrator.pause.assert_called_once()
    assert widget.btn_pause_resume.get_label() == "▶ Продолжить"

    # Resume
    mock_orchestrator.is_paused = True
    widget.toggle_pause()
    mock_orchestrator.resume.assert_called_once()
    assert widget.btn_pause_resume.get_label() == "⏸ Пауза"

    # Stop
    widget.stop_autotune()
    mock_orchestrator.stop.assert_called_once()


def test_orchestra_widget_network_change_alert():
    widget = OrchestraWidget(settle_s=0.0)

    old_c = NetworkConnectionInfo(id="Office", ssid="Office", gateway="192.168.1.1", is_connected=True)
    new_c = NetworkConnectionInfo(id="Cafe", ssid="Cafe", gateway="10.0.0.1", is_connected=True)

    widget.on_network_changed(old_c, new_c)

    while GLib.main_context_default().pending():
        GLib.main_context_default().iteration(False)

    assert widget.network_banner_box.get_visible() is True
    assert "Cafe" in widget.lbl_net_notice.get_text()
    assert "10.0.0.1" in widget.lbl_net_notice.get_text()


def test_orchestra_widget_reset_cache(fake_environment):
    widget = OrchestraWidget(
        apply_preset=fake_environment["apply"],
        probe=fake_environment["probe"],
        targets=fake_environment["targets"],
        history=fake_environment["history"],
        settle_s=0.0,
    )

    widget.list_store.append(["p1", "✓", "✓", "✓", "40 ms", "3/3", "🏆", "p1", 100])
    assert len(widget.list_store) == 1

    widget.reset_cache()
    assert len(widget.list_store) == 0
    assert "сброшен" in widget.lbl_status.get_text()
    assert widget.btn_apply_winner.get_sensitive() is False


def test_orchestra_dialog_and_page_factory(fake_environment):
    dialog = OrchestraDialog(
        apply_preset=fake_environment["apply"],
        probe=fake_environment["probe"],
        settle_s=0.0,
    )
    assert isinstance(dialog, Gtk.Dialog)
    assert isinstance(dialog.orchestra_widget, OrchestraWidget)
    dialog.destroy()

    scrolled, widget = create_orchestra_page(
        apply_preset=fake_environment["apply"],
        probe=fake_environment["probe"],
        settle_s=0.0,
    )
    assert isinstance(scrolled, Gtk.ScrolledWindow)
    assert isinstance(widget, OrchestraWidget)
    child = scrolled.get_child()
    actual_widget = child.get_child() if isinstance(child, Gtk.Viewport) else child
    assert actual_widget == widget
