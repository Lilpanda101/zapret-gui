#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Stage 5.1: curl_cffi Chrome TLS probe selection & graceful fallback.
"""
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

import main
from main import Zapret2App
from orchestra.targets import (
    Target,
    http_probe,
    make_curl_cffi_probe,
    select_probe,
    select_http_transport,
    get_probe_transport_name,
)
from dpi_classifier import DPIClassifier, classify_domains, make_curl_cffi_transport


def test_select_probe_when_curl_cffi_available():
    """When curl_cffi is installed, select_probe returns curl_cffi probe with Chrome UA."""
    probe = select_probe()
    assert probe is not http_probe
    assert callable(probe)
    assert getattr(probe, "is_curl_cffi", False) is True
    assert get_probe_transport_name(probe) == "Chrome (curl_cffi)"


def test_select_probe_fallback_when_curl_cffi_missing(monkeypatch):
    """When curl_cffi raises ImportError, select_probe gracefully falls back to http_probe."""
    import builtins
    orig_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "curl_cffi" or name.startswith("curl_cffi."):
            raise ImportError("Simulated missing curl_cffi")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)

    probe = select_probe()
    assert probe is http_probe
    assert getattr(probe, "is_curl_cffi", False) is False
    assert get_probe_transport_name(probe) == "urllib (fallback)"


def test_curl_cffi_probe_user_agent_is_chrome():
    """make_curl_cffi_probe must use Chrome User-Agent matching chrome124, not Firefox."""
    captured_headers = {}

    class FakeCurlRequests:
        @staticmethod
        def get(url, headers=None, impersonate=None, timeout=None):
            captured_headers.update(headers or {})
            res = SimpleNamespace(status_code=200, text="OK")
            return res

    with patch.dict("sys.modules", {"curl_cffi": SimpleNamespace(requests=FakeCurlRequests), "curl_cffi.requests": FakeCurlRequests}):
        probe = make_curl_cffi_probe("chrome124")
        assert probe is not None
        target = Target("yt", "YouTube", "https://www.youtube.com")
        res = probe(target, timeout=2.0)
        assert res.ok is True
        ua = captured_headers.get("User-Agent", "")
        assert "Chrome/124" in ua
        assert "Firefox" not in ua


def test_select_http_transport_available_and_missing(monkeypatch):
    """select_http_transport returns a callable when curl_cffi is available, None on ImportError."""
    transport = select_http_transport()
    assert callable(transport)

    import builtins
    orig_import = builtins.__import__

    def mock_import(name, *args, **kwargs):
        if name == "curl_cffi" or name.startswith("curl_cffi."):
            raise ImportError("Simulated missing curl_cffi")
        return orig_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", mock_import)
    assert select_http_transport() is None


def test_classify_domains_with_injected_transport():
    """classify_domains and DPIClassifier forward to the injected transport."""
    calls = []

    def fake_transport(url, headers=None, timeout=3.5):
        calls.append((url, headers))
        return 200, {"content-type": "text/html"}, "<html>Clean</html>"

    report = classify_domains(["example.com"], timeout=2.0, http_transport=fake_transport)
    assert len(calls) == 1
    assert "example.com" in calls[0][0]
    assert report is not None
    assert len(report.results) == 1


def test_on_classify_tspu_passes_selected_transport(monkeypatch):
    """Zapret2App.on_classify_tspu passes select_http_transport to classify_domains."""
    captured_transport = []

    def mock_classify(domains, timeout=3.0, mode="auto", http_transport=None):
        captured_transport.append(http_transport)
        from dpi_classifier import DiagnosticReport, ClassificationResult, BlockType
        res = ClassificationResult("rutracker.org", BlockType.PASS, "1.2.3.4", "Clean", 20)
        return DiagnosticReport(results=[res], duration_ms=20)

    monkeypatch.setattr(main, "classify_domains", mock_classify)

    app = SimpleNamespace(
        entry_tspu_domain=SimpleNamespace(get_text=lambda: "rutracker.org"),
        btn_tspu_classify=MagicMock(),
        update_check_badge=MagicMock(),
        tspu_badge=MagicMock(),
        tspu_diag_buffer=MagicMock(),
    )

    fake_transport = MagicMock()
    monkeypatch.setattr(main, "select_http_transport", lambda: fake_transport)

    # Call method
    Zapret2App.on_classify_tspu(app)

    # Wait for background thread
    _cnt = 0
    while GLib.main_context_default().pending() and _cnt < 50:
        GLib.main_context_default().iteration(False)
        _cnt += 1

    import time
    time.sleep(0.1)

    _cnt = 0
    while GLib.main_context_default().pending() and _cnt < 50:
        GLib.main_context_default().iteration(False)
        _cnt += 1

    assert len(captured_transport) == 1
    assert captured_transport[0] is fake_transport


def test_create_orchestra_page_wires_selected_probe(monkeypatch):
    """create_orchestra_page passes select_probe() to OrchestraWidget."""
    fake_probe = MagicMock()
    monkeypatch.setattr(main, "select_probe", lambda: fake_probe)
    monkeypatch.setattr(main, "run_engine", lambda *a: SimpleNamespace(returncode=0))

    fake_app = SimpleNamespace(
        active_preset="general",
        engine_mode="nfqws2",
        zapret2_preset="Default (circular)",
        apply_orchestra_preset=MagicMock(),
        on_orchestra_winner_applied=MagicMock(),
    )

    scrolled = Zapret2App.create_orchestra_page(fake_app)
    assert fake_app.orchestra_widget.probe_fn is fake_probe

    if fake_app.orchestra_widget.network_monitor:
        fake_app.orchestra_widget.network_monitor.stop_monitoring()


def test_get_probe_transport_name_labels():
    """Verify human-readable names for both curl_cffi and urllib."""
    assert get_probe_transport_name(http_probe) == "urllib (fallback)"

    mock_curl = MagicMock()
    mock_curl.is_curl_cffi = True
    assert get_probe_transport_name(mock_curl) == "Chrome (curl_cffi)"

    mock_fallback = MagicMock()
    mock_fallback.is_curl_cffi = False
    mock_fallback.transport_name = "urllib (fallback)"
    assert get_probe_transport_name(mock_fallback) == "urllib (fallback)"
