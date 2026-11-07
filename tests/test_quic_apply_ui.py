#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Headless UI tests for QUIC analyzer and ApplyChecker integration:
- Domain inspection tab: on_quic_test_clicked launches QuicAnalyzer in background,
  computes latency penalty, formats verdict and price of refusal, and posts via GLib.idle_add.
- Apply preset flow: verify_connectivity_after_apply checks target connectivity,
  presents suggestion dialog on failure, and enables 1-click fallback preset application.
"""
import os
import threading
import time
from unittest.mock import MagicMock, patch

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib
import pytest

from diagnostics.quic_analyzer import QuicVerdict
from diagnostics.apply_checker import ApplyCheckOutcome
import main


def _drain_glib():
    ctx = GLib.main_context_default()
    while ctx.iteration(False):
        pass


class FakeAppQuicApply(Gtk.Window):
    """Minimal fake app for testing QUIC and ApplyChecker UI flows."""
    def __init__(self):
        super().__init__()
        self.entry_inspect_domain = Gtk.Entry()
        self.inspect_buffer = Gtk.TextBuffer()
        self.btn_quic_test = Gtk.Button(label="Замерить QUIC")
        self.engine_mode = "nfqws2"
        self.zapret2_preset = "general"
        self.active_preset = "general"
        self.restarted = False
        self.dialog_shown = False
        self.saved_config = False

    def on_quic_test_clicked(self, _=None):
        main.Zapret2App.on_quic_test_clicked(self, _)

    def verify_connectivity_after_apply(self):
        main.Zapret2App.verify_connectivity_after_apply(self)

    def _show_apply_suggestion_dialog(self, outcome):
        self.dialog_shown = True
        main.Zapret2App._show_apply_suggestion_dialog(self, outcome)

    def apply_suggested_preset(self, preset_name):
        main.Zapret2App.apply_suggested_preset(self, preset_name)

    def save_config(self):
        self.saved_config = True

    def restart_engine(self, check_after=False):
        self.restarted = True


def test_on_quic_test_clicked_headless():
    app = FakeAppQuicApply()
    app.entry_inspect_domain.set_text("youtube.com")

    fake_verdict = QuicVerdict(
        domain="youtube.com",
        quic_available=False,
        tcp_available=True,
        quic_rtt_ms=None,
        tcp_rtt_ms=25.0,
        penalty_ms=45.0,
        verdict_text="QUIC блокируется ТСПУ на UDP 443",
        recommendation="Отключить QUIC в браузере или использовать fake-quic",
        price_of_refusal="Отказ от QUIC увеличивает задержку старта видеопотоков на ~45.0 ms",
    )

    with patch("main.QuicAnalyzer") as MockAnalyzer:
        mock_inst = MagicMock()
        mock_inst.analyze.return_value = fake_verdict
        MockAnalyzer.return_value = mock_inst

        app.on_quic_test_clicked()

        # Let background thread and GLib idle tasks run
        time.sleep(0.15)
        _drain_glib()

    output = app.inspect_buffer.get_text(
        app.inspect_buffer.get_start_iter(),
        app.inspect_buffer.get_end_iter(),
        True,
    )

    assert "=== ЗАМЕР QUIC / HTTP/3: youtube.com ===" in output
    assert "QUIC (UDP 443): Блокируется ТСПУ (Blackhole)" in output
    assert "TCP 443: Доступен (25.0 ms)" in output
    assert "Разница в задержке: 45.0 ms" in output
    assert "ЦЕНА ОТКАЗА ОТ QUIC: Отказ от QUIC увеличивает задержку" in output
    assert app.btn_quic_test.get_sensitive() is True


def test_on_quic_test_clicked_empty_domain():
    app = FakeAppQuicApply()
    app.entry_inspect_domain.set_text("")

    app.on_quic_test_clicked()
    output = app.inspect_buffer.get_text(
        app.inspect_buffer.get_start_iter(),
        app.inspect_buffer.get_end_iter(),
        True,
    )
    assert "Ошибка: введите домен" in output


def test_apply_checker_failure_shows_dialog_and_switches_preset():
    app = FakeAppQuicApply()
    app.zapret2_preset = "general"

    fake_outcome = ApplyCheckOutcome(
        success=False,
        status_code=None,
        rtt_ms=None,
        error="Таймаут соединения или сброс RST",
        suggested_preset="general ALT",
        suggestion_reason="Высокая агрессивность TLS сплита в general ALT помогает обойти жесткий ТСПУ drop",
    )

    with patch("main.ApplyChecker") as MockChecker, \
         patch.object(Gtk.MessageDialog, "run", return_value=Gtk.ResponseType.OK), \
         patch.object(Gtk.MessageDialog, "destroy"):
        mock_inst = MagicMock()
        mock_inst.check.return_value = fake_outcome
        MockChecker.return_value = mock_inst

        app.verify_connectivity_after_apply()

        time.sleep(0.15)
        _drain_glib()

    assert app.dialog_shown is True
    assert app.zapret2_preset == "general ALT"
    assert app.saved_config is True
    assert app.restarted is True


def test_apply_checker_success_does_not_show_dialog():
    app = FakeAppQuicApply()

    fake_outcome = ApplyCheckOutcome(
        success=True,
        status_code=200,
        rtt_ms=45.0,
        error=None,
        suggested_preset=None,
        suggestion_reason=None,
    )

    with patch("main.ApplyChecker") as MockChecker:
        mock_inst = MagicMock()
        mock_inst.check.return_value = fake_outcome
        MockChecker.return_value = mock_inst

        app.verify_connectivity_after_apply()

        time.sleep(0.15)
        _drain_glib()

    assert app.dialog_shown is False
    assert app.restarted is False
