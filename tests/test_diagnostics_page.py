#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for TSPU diagnostics card on the BlockCheck page (Stage 5).

No real network, root privileges, or nftables are used.
All diagnostics operations are mocked with deterministic DiagnosticReport fixtures.
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from dpi_classifier import (
    BlockType,
    ClassificationResult,
    DiagnosticReport,
    DPIClassifier,
    get_block_verdict,
    make_curl_cffi_transport,
)
from orchestra.targets import make_curl_cffi_probe, http_probe, Target, ProbeResult
from main import Zapret2App


@pytest.fixture(autouse=True)
def check_gtk():
    """Ensure a GTK display is available (e.g. under xvfb-run)."""
    initialized = Gtk.init_check([])[0]
    if not initialized:
        pytest.skip("GTK display unavailable, run under xvfb-run")


@pytest.fixture
def mock_app():
    """Creates a Zapret2App instance with background subsystems safely mocked."""
    with (
        patch("main.MirrorHealthMonitor"),
        patch("main.get_healer") as mock_healer,
        patch("main.subprocess.run") as mock_subp,
        patch("main.TrayManager"),
        patch.object(Zapret2App, "refresh_status"),
    ):
        mock_subp.return_value = MagicMock(returncode=0, stdout="INACTIVE\n", stderr="")
        fake_healer = MagicMock()
        fake_healer.status = "OK"
        mock_healer.return_value = fake_healer

        app = Zapret2App(minimized=True)
        yield app

        if hasattr(app, "orchestra_widget") and app.orchestra_widget and app.orchestra_widget.network_monitor:
            try:
                app.orchestra_widget.network_monitor.stop_monitoring()
            except Exception:
                pass
        if hasattr(app, "mirror_monitor") and app.mirror_monitor:
            try:
                app.mirror_monitor.stop()
            except Exception:
                pass
        app.destroy()


def flush_glib(max_iterations: int = 100):
    """Flushes pending idle callbacks on the default GLib context."""
    ctx = GLib.main_context_default()
    count = 0
    while ctx.pending() and count < max_iterations:
        ctx.iteration(False)
        count += 1


def wait_and_flush(app: Zapret2App):
    """Waits for TSPU thread to finish and flushes GLib event queue."""
    if hasattr(app, "_tspu_thread") and app._tspu_thread:
        app._tspu_thread.join(timeout=2.0)
    flush_glib()


def get_buffer_text(buffer: Gtk.TextBuffer) -> str:
    """Helper to extract full text from a Gtk.TextBuffer."""
    start = buffer.get_start_iter()
    end = buffer.get_end_iter()
    return buffer.get_text(start, end, True)


# ============================================================================
# 1. Page & Card Creation Tests
# ============================================================================

def test_blockcheck_page_structure_and_preservation(mock_app):
    """Проверяет наличие карточки «Глубокая диагностика ТСПУ» и сохранность экспресс-проверки."""
    app = mock_app

    # Экспресс-проверка бейджей не сломана
    assert hasattr(app, "check_targets") and len(app.check_targets) >= 8
    assert hasattr(app, "check_badges") and len(app.check_badges) >= 8
    assert hasattr(app, "btn_run_check")
    assert hasattr(app, "btn_auto_preset")
    assert "rutracker" in app.check_badges
    assert "youtube" in app.check_badges

    # Карточка «Глубокая диагностика ТСПУ» создана
    assert hasattr(app, "entry_tspu_domain")
    assert hasattr(app, "btn_tspu_classify")
    assert hasattr(app, "tspu_badge")
    assert hasattr(app, "tspu_diag_buffer")
    assert hasattr(app, "tspu_output")

    # Начальные значения элементов UI
    assert app.entry_tspu_domain.get_text() == "rutracker.org"
    assert app.btn_tspu_classify.get_sensitive() is True
    assert app.tspu_badge.get_text() == "Не проверялось"
    assert app.tspu_badge.get_style_context().has_class("badge-neutral")

    # Monospace TextBuffer
    assert app.tspu_output.get_monospace() is True
    assert app.tspu_output.get_editable() is False


# ============================================================================
# 2. Diagnostics Classification Tests for all BlockTypes
# ============================================================================

def test_diagnostics_classification_pass(mock_app):
    """Проверка прогона для статуса PASS (трафик проходит чисто)."""
    app = mock_app
    report = DiagnosticReport(
        results=[
            ClassificationResult(
                target="rutracker.org",
                block_type=BlockType.PASS,
                ip="104.21.32.1",
                details="Traffic passes cleanly without censorship",
                rtt_ms=32,
            )
        ],
        duration_ms=45,
    )

    fake_classifier = MagicMock()
    fake_classifier.run_diagnostics.return_value = report
    app.dpi_classifier = fake_classifier

    app.on_classify_tspu()
    wait_and_flush(app)

    fake_classifier.run_diagnostics.assert_called_once_with(["rutracker.org"], mode="auto")
    assert app.btn_tspu_classify.get_sensitive() is True

    # Бейдж: badge-ok, текст PASS
    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-ok")
    assert not ctx.has_class("badge-bad")
    assert not ctx.has_class("badge-warn")
    assert "PASS" in app.tspu_badge.get_text()

    # Текст в буфере: BlockType, описание, рекомендация, summary_text, to_json
    text = get_buffer_text(app.tspu_diag_buffer)
    assert "BlockType): PASS" in text
    assert "Уровень угрозы: PASS" in text
    assert "Цензура и фильтрация ТСПУ не обнаружены" in text
    assert "Специальные правила обхода и desync не требуются" in text
    assert "DPI CLASSIFIER DIAGNOSTIC REPORT" in text
    assert '"block_type": "PASS"' in text


def test_diagnostics_classification_critical_sni_drop(mock_app):
    """Проверка сброса TLS SNI (CRITICAL -> badge-bad)."""
    app = mock_app
    report = DiagnosticReport(
        results=[
            ClassificationResult(
                target="rutracker.org",
                block_type=BlockType.TLS_SNI_DROP,
                ip="104.21.32.1",
                details="Timeout awaiting ServerHello; packet dropped by DPI for SNI",
                rtt_ms=3000,
            )
        ],
        duration_ms=3020,
    )

    fake_classifier = MagicMock()
    fake_classifier.run_diagnostics.return_value = report
    app.dpi_classifier = fake_classifier

    app.on_classify_tspu()
    wait_and_flush(app)

    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-bad")
    assert "CRITICAL" in app.tspu_badge.get_text()

    text = get_buffer_text(app.tspu_diag_buffer)
    assert "BlockType): TLS_SNI_DROP" in text
    assert "Уровень угрозы: CRITICAL" in text
    assert "TLS SNI" in text
    assert "split2" in text or "фрагментацию" in text


def test_diagnostics_classification_critical_dns_spoofing(mock_app):
    """Проверка подмены DNS (CRITICAL -> badge-bad)."""
    app = mock_app
    report = DiagnosticReport(
        results=[
            ClassificationResult(
                target="rutracker.org",
                block_type=BlockType.DNS_SPOOFING,
                ip="127.0.0.1",
                details="DNS returned bogon/loopback IP",
                rtt_ms=10,
            )
        ],
        duration_ms=15,
    )

    fake_classifier = MagicMock()
    fake_classifier.run_diagnostics.return_value = report
    app.dpi_classifier = fake_classifier

    app.on_classify_tspu()
    wait_and_flush(app)

    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-bad")
    assert "CRITICAL" in app.tspu_badge.get_text()

    text = get_buffer_text(app.tspu_diag_buffer)
    assert "BlockType): DNS_SPOOFING" in text
    assert "DoH" in text or "DNS" in text


def test_diagnostics_classification_critical_tcp_rst(mock_app):
    """Проверка активного инжекта TCP RST (CRITICAL -> badge-bad)."""
    app = mock_app
    report = DiagnosticReport(
        results=[
            ClassificationResult(
                target="youtube.com",
                block_type=BlockType.TCP_RST_INJECTION,
                ip="142.250.74.206",
                details="TCP RST injected after TLS ClientHello",
                rtt_ms=28,
            )
        ],
        duration_ms=30,
    )

    fake_classifier = MagicMock()
    fake_classifier.run_diagnostics.return_value = report
    app.dpi_classifier = fake_classifier

    app.entry_tspu_domain.set_text("youtube.com")
    app.on_classify_tspu()
    wait_and_flush(app)

    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-bad")
    assert "CRITICAL" in app.tspu_badge.get_text()

    text = get_buffer_text(app.tspu_diag_buffer)
    assert "BlockType): TCP_RST_INJECTION" in text
    assert "десинхронизацией TCP" in text or "fake" in text


def test_diagnostics_classification_warning_http_blockpage(mock_app):
    """Проверка страницы-заглушки HTTP (WARNING -> badge-warn)."""
    app = mock_app
    report = DiagnosticReport(
        results=[
            ClassificationResult(
                target="rutracker.org",
                block_type=BlockType.HTTP_BLOCKPAGE,
                ip="195.82.146.120",
                details="HTTP 302 redirect to eais.rkn.gov.ru",
                rtt_ms=40,
            )
        ],
        duration_ms=45,
    )

    fake_classifier = MagicMock()
    fake_classifier.run_diagnostics.return_value = report
    app.dpi_classifier = fake_classifier

    app.on_classify_tspu()
    wait_and_flush(app)

    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-warn")
    assert "WARNING" in app.tspu_badge.get_text()

    text = get_buffer_text(app.tspu_diag_buffer)
    assert "BlockType): HTTP_BLOCKPAGE" in text
    assert "Уровень угрозы: WARNING" in text
    assert "HTTPS" in text


def test_diagnostics_classification_warning_quic_blackhole(mock_app):
    """Проверка блокировки QUIC/UDP (WARNING -> badge-warn)."""
    app = mock_app
    report = DiagnosticReport(
        results=[
            ClassificationResult(
                target="youtube.com",
                block_type=BlockType.QUIC_BLACKHOLE,
                ip="142.250.74.206",
                details="UDP 443 handshake timed out",
                rtt_ms=1500,
            )
        ],
        duration_ms=1520,
    )

    fake_classifier = MagicMock()
    fake_classifier.run_diagnostics.return_value = report
    app.dpi_classifier = fake_classifier

    app.entry_tspu_domain.set_text("youtube.com")
    app.on_classify_tspu()
    wait_and_flush(app)

    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-warn")
    assert "WARNING" in app.tspu_badge.get_text()

    text = get_buffer_text(app.tspu_diag_buffer)
    assert "BlockType): QUIC_BLACKHOLE" in text
    assert "QUIC" in text


def test_diagnostics_classification_warning_timeout(mock_app):
    """Проверка общего таймаута (WARNING -> badge-warn)."""
    app = mock_app
    report = DiagnosticReport(
        results=[
            ClassificationResult(
                target="unknown-site.org",
                block_type=BlockType.TIMEOUT,
                ip="1.2.3.4",
                details="Connection timed out",
                rtt_ms=3000,
            )
        ],
        duration_ms=3010,
    )

    fake_classifier = MagicMock()
    fake_classifier.run_diagnostics.return_value = report
    app.dpi_classifier = fake_classifier

    app.entry_tspu_domain.set_text("unknown-site.org")
    app.on_classify_tspu()
    wait_and_flush(app)

    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-warn")
    assert "WARNING" in app.tspu_badge.get_text()

    text = get_buffer_text(app.tspu_diag_buffer)
    assert "BlockType): TIMEOUT" in text


def test_diagnostics_classification_error_type(mock_app):
    """Проверка ошибки классификации (ERROR -> badge-bad)."""
    app = mock_app
    report = DiagnosticReport(
        results=[
            ClassificationResult(
                target="bad-domain.invalid",
                block_type=BlockType.ERROR,
                ip=None,
                details="Could not resolve target IP",
                rtt_ms=10,
            )
        ],
        duration_ms=15,
    )

    fake_classifier = MagicMock()
    fake_classifier.run_diagnostics.return_value = report
    app.dpi_classifier = fake_classifier

    app.entry_tspu_domain.set_text("bad-domain.invalid")
    app.on_classify_tspu()
    wait_and_flush(app)

    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-bad")
    assert "ERROR" in app.tspu_badge.get_text()

    text = get_buffer_text(app.tspu_diag_buffer)
    assert "BlockType): ERROR" in text


# ============================================================================
# 3. Button Locking & Restoration Tests
# ============================================================================

def test_diagnostics_button_locking_during_run(mock_app):
    """Проверяет, что кнопка блокируется во время работы и разблокируется по окончании."""
    app = mock_app

    start_event = threading.Event()
    finish_event = threading.Event()

    def slow_diagnostics(targets, mode="auto"):
        start_event.set()
        finish_event.wait(timeout=2.0)
        return DiagnosticReport(
            results=[ClassificationResult("rutracker.org", BlockType.PASS, "1.1.1.1", "OK")]
        )

    fake_classifier = MagicMock()
    fake_classifier.run_diagnostics.side_effect = slow_diagnostics
    app.dpi_classifier = fake_classifier

    assert app.btn_tspu_classify.get_sensitive() is True
    app.on_classify_tspu()

    # Сразу после вызова кнопка заблокирована
    assert app.btn_tspu_classify.get_sensitive() is False
    assert app.tspu_badge.get_text() == "Проверка..."

    # Дожидаемся входа воркера в slow_diagnostics
    assert start_event.wait(timeout=1.0) is True
    assert app.btn_tspu_classify.get_sensitive() is False

    # Сигнализируем завершение воркера
    finish_event.set()
    wait_and_flush(app)

    # После завершения кнопка снова чувствительна
    assert app.btn_tspu_classify.get_sensitive() is True


# ============================================================================
# 4. Honest Error Handling Tests
# ============================================================================

def test_diagnostics_honest_error_on_exception(mock_app):
    """При исключении в фоновом потоке показывается честная ошибка, а не 'успех'."""
    app = mock_app

    fake_classifier = MagicMock()
    fake_classifier.run_diagnostics.side_effect = ConnectionError("Сетевой интерфейс недоступен")
    app.dpi_classifier = fake_classifier

    app.on_classify_tspu()
    wait_and_flush(app)

    # Кнопка разблокирована
    assert app.btn_tspu_classify.get_sensitive() is True

    # Бейдж покрашен в badge-bad
    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-bad")
    assert not ctx.has_class("badge-ok")
    assert "ERROR" in app.tspu_badge.get_text()

    # Буфер содержит честное сообщение об ошибке
    text = get_buffer_text(app.tspu_diag_buffer)
    assert "ОШИБКА ДИАГНОСТИКИ" in text
    assert "Сетевой интерфейс недоступен" in text
    assert "Успех" not in text


def test_diagnostics_empty_domain_validation(mock_app):
    """При пустом поле ввода выдается ошибка валидации без фонового вызова."""
    app = mock_app
    app.entry_tspu_domain.set_text("    ")

    fake_classifier = MagicMock()
    app.dpi_classifier = fake_classifier

    app.on_classify_tspu()
    flush_glib()

    fake_classifier.run_diagnostics.assert_not_called()
    assert app.btn_tspu_classify.get_sensitive() is True

    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-bad")
    assert "ERROR" in app.tspu_badge.get_text()

    text = get_buffer_text(app.tspu_diag_buffer)
    assert "Ошибка: введите доменное имя" in text


# ============================================================================
# 5. Optional Dependency & Injectable Transport Tests
# ============================================================================

def test_get_block_verdict_all_types():
    """Проверка словаря вердиктов для всех известных типов блокировок."""
    for b_type in [
        BlockType.PASS,
        BlockType.DNS_SPOOFING,
        BlockType.TCP_RST_INJECTION,
        BlockType.TLS_SNI_DROP,
        BlockType.HTTP_BLOCKPAGE,
        BlockType.QUIC_BLACKHOLE,
        BlockType.TIMEOUT,
        BlockType.ERROR,
    ]:
        v = get_block_verdict(b_type)
        assert "severity" in v
        assert "badge_class" in v
        assert "badge_text" in v
        assert "description" in v
        assert "recommendation" in v
        assert v["badge_class"] in ("badge-ok", "badge-bad", "badge-warn")


def test_curl_cffi_optional_helpers():
    """Проверка корректной работы curl_cffi хелперов и инъектируемого транспорта."""
    transport = make_curl_cffi_transport(impersonate="chrome124")
    # Если curl_cffi установлен, вернёт функцию, иначе None
    if transport is not None:
        assert callable(transport)

    probe = make_curl_cffi_probe(impersonate="chrome124")
    if probe is not None:
        assert callable(probe)

    # Проверка инъектируемого транспорта в DPIClassifier
    calls = []

    def mock_transport(url, headers=None, timeout=3.5):
        calls.append(url)
        return 200, {}, "<h1>Clean page</h1>"

    classifier = DPIClassifier(http_transport=mock_transport)
    is_block, reason = classifier.check_http_blockpage("example.com", "93.184.216.34")
    assert is_block is False
    assert len(calls) == 1
    assert "example.com" in calls[0]


def test_http_probe_with_injected_transport():
    """Проверка инъекции кастомного транспорта в orchestra.http_probe."""
    target = Target("custom", "example.com", "https://example.com")

    fake_transport = MagicMock(return_value=ProbeResult(True, 42, 200, ""))
    res = http_probe(target, transport=fake_transport)
    fake_transport.assert_called_once_with(target, timeout=3.5)
    assert res.ok is True
    assert res.latency_ms == 42
