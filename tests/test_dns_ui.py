#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for DNS Provider Picker UI, latency probing, sorting, and engine validation.
"""

from unittest.mock import MagicMock, patch
import pytest
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from dns_providers import ENGINE_SUPPORTED_DNS, list_providers
from engine_params import EngineParams
from main import Zapret2App


@pytest.fixture(autouse=True)
def check_gtk():
    initialized = Gtk.init_check([])[0]
    if not initialized:
        pytest.skip("GTK display unavailable, run under xvfb-run")


@pytest.fixture
def mock_app(tmp_path):
    with patch("main.MirrorHealthMonitor"), \
         patch("main.get_healer") as mock_healer, \
         patch("main.subprocess.run") as mock_subp, \
         patch("main.GLib.timeout_add"), \
         patch("main.GLib.timeout_add_seconds"):

        fake_healer = MagicMock()
        fake_healer.status = "OK"
        fake_healer.is_running = False
        mock_healer.return_value = fake_healer
        mock_subp.return_value = MagicMock(returncode=0, stdout="INACTIVE\n", stderr="")

        app = Zapret2App(minimized=True)
        app.app_dir = str(tmp_path)
        yield app
        app.destroy()


def test_dns_ui_unsupported_providers_disabled(mock_app):
    """
    Verifies providers not in engine.sh (e.g. mullvad, comss, nextdns)
    are rendered as insensitive (disabled) and cannot be selected.
    """
    app = mock_app
    all_providers = list_providers(include_system=True)

    for prov in all_providers:
        pid = prov.id
        assert pid in app.dns_radios, f"Provider {pid} missing from dns_radios"
        radio = app.dns_radios[pid]

        if pid in ENGINE_SUPPORTED_DNS:
            assert radio.get_sensitive() is True, f"Supported provider {pid} should be sensitive"
        else:
            assert radio.get_sensitive() is False, f"Unsupported provider {pid} must be insensitive"

    # Attempting to toggle radio for an unsupported provider must not set active_dns
    initial_dns = app.active_dns
    unsupported_radio = app.dns_radios["mullvad"]
    app.on_dns_radio_toggled(unsupported_radio, "mullvad")
    assert app.active_dns == initial_dns


def test_dns_engine_params_rejects_unsupported():
    """
    EngineParams must never pass an unsupported provider silently to engine.sh.
    """
    params = EngineParams(dns="mullvad")
    argv = params.to_argv("start")
    # Must fallback to cloudflare
    assert argv[3] == "cloudflare"

    dict_params = EngineParams.from_dict({"dns": "nextdns"})
    assert dict_params.dns == "cloudflare"


def test_dns_ui_probe_all_rtt_and_sorting(mock_app):
    """
    Tests mock probe_all_rtt results, UI latency badge updates, and RTT sorting.
    """
    app = mock_app

    # Canned probe results
    mock_rtts = {
        "google": 45.0,
        "cloudflare": 15.2,
        "quad9": 10.5,
        "adguard": 80.0,
        "system": 5.1,
        "dns_ai": 60.0,
        "geohide": 70.0,
        "mullvad": 2.0,       # Fast, but unsupported -> must be sorted after supported!
        "comss": None,        # Unreachable & unsupported
        "nextdns": 100.0,     # Unsupported
    }

    # Deliver probe completion callback directly to UI handler
    app._on_probe_dns_completed(mock_rtts)

    # Check that labels were updated
    assert app.dns_rtt_labels["quad9"].get_text() == "10.5 мс"
    assert app.dns_rtt_labels["cloudflare"].get_text() == "15.2 мс"
    assert app.dns_rtt_labels["comss"].get_text() == "Недоступен"

    # Verify sorting order in Gtk.Box
    children = app.dns_cards_box.get_children()
    child_pids = []
    for child in children:
        for pid, card in app.dns_cards.items():
            if card == child:
                child_pids.append(pid)
                break

    # 1. System (5.1 ms) should come before Quad9 (10.5 ms)
    assert child_pids.index("system") < child_pids.index("quad9")
    # 2. Quad9 (10.5 ms) before Cloudflare (15.2 ms)
    assert child_pids.index("quad9") < child_pids.index("cloudflare")
    # 3. Cloudflare (15.2 ms) before Google (45.0 ms)
    assert child_pids.index("cloudflare") < child_pids.index("google")
    # 4. Google (45.0 ms) before AdGuard (80.0 ms)
    assert child_pids.index("google") < child_pids.index("adguard")
    # 5. All supported providers must come before unsupported providers (like mullvad)
    supported_indices = [child_pids.index(p) for p in ENGINE_SUPPORTED_DNS if p in child_pids]
    unsupported_indices = [child_pids.index(p) for p in ["mullvad", "comss", "nextdns"] if p in child_pids]

    assert max(supported_indices) < min(unsupported_indices)


def test_dns_ui_save_active_dns(mock_app, tmp_path):
    """
    Tests selecting a supported provider updates active_dns and engine_command.
    """
    app = mock_app
    app.active_dns = "cloudflare"

    quad9_radio = app.dns_radios["quad9"]
    quad9_radio.set_active(True)
    app.on_dns_radio_toggled(quad9_radio, "quad9")

    assert app.active_dns == "quad9"
    cmd = app.engine_command("start")
    assert cmd[3] == "quad9"
