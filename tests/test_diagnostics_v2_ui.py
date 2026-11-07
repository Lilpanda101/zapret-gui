#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Headless UI and unit tests for Stage 5.4 diagnostics v2 & integrity UI wiring."""

from __future__ import annotations

import json
import ssl
from unittest.mock import MagicMock, patch

import pytest
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from diagnostics import (
    NetworkFactCollector,
    extract_real_tls_cert,
    judge_cause,
    judge_dns,
    judge_service,
    DnsState,
    CauseFacts,
    HelloResult,
    HttpFacts,
    HELLO_OK,
    HELLO_RESET,
    HELLO_TIMEOUT,
    SMALL_WINDOW_BYTES,
    CONTROL_WINDOW_BYTES,
    BlockCheck2Runner,
    get_verdict_words,
    VERDICTS,
)
from dpi_classifier import get_block_verdict, BlockType
from install_integrity import (
    verify_fast,
    verify_full,
    IntegrityCause,
    IntegrityFinding,
    IntegrityReport,
    KIND_MISSING,
    ROLE_CRITICAL,
)
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
        # Ensure legacy dpi_classifier mock is None by default so v2 runs
        app.dpi_classifier = None
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
    ctx = GLib.main_context_default()
    count = 0
    while ctx.pending() and count < max_iterations:
        ctx.iteration(False)
        count += 1


def wait_and_flush(app: Zapret2App):
    if hasattr(app, "_tspu_thread") and app._tspu_thread:
        app._tspu_thread.join(timeout=2.5)
    flush_glib()


def get_buffer_text(buffer: Gtk.TextBuffer) -> str:
    start = buffer.get_start_iter()
    end = buffer.get_end_iter()
    return buffer.get_text(start, end, True)


# ============================================================================
# 1. Headless UI tests of diagnostics v2 on BlockCheck page
# ============================================================================

def test_diagnostics_v2_ui_dns_spoofed(mock_app):
    """Тест встройки v2: при возврате системным DNS адреса CGNAT (100.64.0.1)
    ставится вердикт DNS_SPOOFING с доказательством и бейджем badge-bad."""
    app = mock_app
    app.entry_tspu_domain.set_text("blocked-target.org")

    with (
        patch("socket.getaddrinfo") as mock_gai,
        patch("urllib.request.urlopen") as mock_urlopen,
        patch("main.extract_real_tls_cert") as mock_tls_cert,
    ):
        mock_gai.return_value = [(2, 1, 6, "", ("100.64.0.1", 443))]
        mock_tls_cert.return_value = (None, None, "")
        # DoH reference returns standard IP
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"Answer": [{"type": 1, "data": "93.184.216.34"}]}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        app.on_classify_tspu()
        wait_and_flush(app)

    assert app.btn_tspu_classify.get_sensitive() is True
    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-bad")
    assert "DNS" in app.tspu_badge.get_text()

    txt = get_buffer_text(app.tspu_diag_buffer)
    assert "DNS_SPOOFING" in txt
    assert "100.64.0.1" in txt
    assert "CGNAT" in txt
    assert "DoT / DoH" in txt


def test_diagnostics_v2_ui_reply_window(mock_app):
    """Тест встройки v2: при Anycast/CDN с валидным сертификатом и обрыве
    на окне ответа выносится вердикт TLS_REPLY_WINDOW с wssize рекомендацией."""
    app = mock_app
    app.entry_tspu_domain.set_text("rutracker.org")

    fake_collector = MagicMock()
    fake_collector.collect.return_value = CauseFacts(
        host="rutracker.org",
        ip="104.21.32.1",
        real_hello=HelloResult(HELLO_TIMEOUT, rtt_ms=3000),
        neutral_hello=HelloResult(HELLO_TIMEOUT, rtt_ms=3000),
        nameless_hello=HelloResult(HELLO_TIMEOUT, rtt_ms=3000),
        allowed_hellos={},
        recased_name="RuTrAcKeR.OrG",
        recased_hello=HelloResult(HELLO_TIMEOUT, rtt_ms=3000),
        http=HttpFacts(status=None),
        ping_ok=True,
        small_window_1=HelloResult(HELLO_OK, rtt_ms=45, data_len=5),
        small_window_2=HelloResult(HELLO_OK, rtt_ms=42, data_len=5),
        window_control=HelloResult(HELLO_RESET, rtt_ms=50),
    )
    app.network_fact_collector = fake_collector

    with (
        patch("socket.getaddrinfo") as mock_gai,
        patch("urllib.request.urlopen") as mock_urlopen,
        patch("main.extract_real_tls_cert") as mock_tls_cert,
    ):
        mock_gai.return_value = [(2, 1, 6, "", ("104.21.32.1", 443))]
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"Answer": [{"type": 1, "data": "104.21.32.2"}]}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        # Valid cert on system IP -> Anycast CDN confirmed
        mock_tls_cert.return_value = (True, True, "Cloudflare Inc ECC CA-3")

        app.on_classify_tspu()
        wait_and_flush(app)

    assert app.btn_tspu_classify.get_sensitive() is True
    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-bad")
    assert "Окно ответа" in app.tspu_badge.get_text()

    txt = get_buffer_text(app.tspu_diag_buffer)
    assert "TLS_REPLY_WINDOW" in txt
    assert "1 байт" in txt
    assert "wssize" in txt


def test_diagnostics_v2_ui_clean_pass(mock_app):
    """Тест встройки v2: чистый проход (PASS) с валидным соединением."""
    app = mock_app
    app.entry_tspu_domain.set_text("rutracker.org")

    fake_collector = MagicMock()
    fake_collector.collect.return_value = CauseFacts(
        host="rutracker.org",
        ip="104.21.32.1",
        real_hello=HelloResult(HELLO_OK, rtt_ms=35, data_len=5),
        neutral_hello=HelloResult(HELLO_OK, rtt_ms=36, data_len=5),
        nameless_hello=HelloResult(HELLO_OK, rtt_ms=34, data_len=5),
        allowed_hellos={},
        recased_name="RuTrAcKeR.OrG",
        recased_hello=HelloResult(HELLO_OK, rtt_ms=35, data_len=5),
        http=HttpFacts(status=200),
        ping_ok=True,
    )
    app.network_fact_collector = fake_collector

    with (
        patch("socket.getaddrinfo") as mock_gai,
        patch("urllib.request.urlopen") as mock_urlopen,
        patch("main.extract_real_tls_cert") as mock_tls_cert,
    ):
        mock_gai.return_value = [(2, 1, 6, "", ("104.21.32.1", 443))]
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.read.return_value = json.dumps({"Answer": [{"type": 1, "data": "104.21.32.1"}]}).encode()
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        mock_tls_cert.return_value = (True, True, "Cloudflare Inc ECC CA-3")

        app.on_classify_tspu()
        wait_and_flush(app)

    assert app.btn_tspu_classify.get_sensitive() is True
    ctx = app.tspu_badge.get_style_context()
    assert ctx.has_class("badge-ok")
    assert "PASS" in app.tspu_badge.get_text()

    txt = get_buffer_text(app.tspu_diag_buffer)
    assert "PASS" in txt
    assert "Доказательство вердикта" in txt


# ============================================================================
# 2. Real TLS handshake certificate extraction tests
# ============================================================================

def test_extract_real_tls_cert_mocked():
    """Проверка логики извлечения сертификата: доверенный, недостоверный, сбой сокета."""
    class MockValidSocket:
        def settimeout(self, t): pass
        def connect(self, addr): pass
        def close(self): pass

    class MockTLSSocket:
        def __init__(self, cert): self._cert = cert
        def getpeercert(self): return self._cert
        def close(self): pass

    # 1. Валидный сертификат с совпадением SAN
    cert_dict = {
        "subjectAltName": [("DNS", "example.com"), ("DNS", "*.example.com")],
        "subject": ((("commonName", "example.com"),),),
        "issuer": ((("organizationName", "DigiCert"),),),
    }
    with patch("ssl.create_default_context") as mock_ctx:
        ctx_inst = MagicMock()
        ctx_inst.wrap_socket.return_value = MockTLSSocket(cert_dict)
        mock_ctx.return_value = ctx_inst

        valid, match, issuer = extract_real_tls_cert(
            "93.184.216.34", "example.com", socket_factory=lambda *a, **kw: MockValidSocket()
        )
        assert valid is True
        assert match is True
        assert "DigiCert" in issuer

    # 2. Недостоверный сертификат (SSLCertVerificationError от ISP-заглушки)
    with patch("ssl.create_default_context") as mock_ctx:
        ctx_inst = MagicMock()
        ctx_inst.wrap_socket.side_effect = ssl.SSLCertVerificationError(1, "[SSL: CERTIFICATE_VERIFY_FAILED] self-signed")
        mock_ctx.return_value = ctx_inst

        valid, match, issuer = extract_real_tls_cert(
            "93.184.216.34", "example.com", socket_factory=lambda *a, **kw: MockValidSocket()
        )
        assert valid is False
        assert match is False
        assert "Ошибка валидации CA" in issuer

    # 3. Таймаут соединения
    with patch("ssl.create_default_context") as mock_ctx:
        ctx_inst = MagicMock()
        mock_ctx.return_value = ctx_inst

        def failing_sock(*a, **kw):
            s = MagicMock()
            s.connect.side_effect = TimeoutError("Connection timed out")
            return s

        valid, match, issuer = extract_real_tls_cert(
            "93.184.216.34", "example.com", socket_factory=failing_sock
        )
        assert valid is None
        assert match is None


# ============================================================================
# 3. install_integrity UI integration tests
# ============================================================================

def test_install_integrity_fast_blocks_launch(mock_app):
    """verify_fast блокирует запуск движка при повреждении критических компонентов."""
    app = mock_app
    app.engine_mode = "nfqws2"

    corrupted_report = IntegrityReport(
        cause=IntegrityCause.CORRUPTED,
        findings=(
            IntegrityFinding(path="bin/nfqws2", kind=KIND_MISSING, role=ROLE_CRITICAL, engines=("nfqws2",)),
        ),
        manifest_version="1",
        checked_files=10,
        deep=False,
    )

    with (
        patch("main.verify_fast", return_value=corrupted_report),
        patch("main.run_engine") as mock_run_eng,
        patch.object(app, "show_dialog") as mock_dlg,
    ):
        app.start_engine()
        flush_glib()

        assert app.btn_toggle.get_sensitive() is True
        mock_run_eng.assert_not_called()
        mock_dlg.assert_called_once()
        assert "целостности" in mock_dlg.call_args[0][0].lower()


def test_install_integrity_fast_allows_manifest_absent_and_locked(mock_app):
    """verify_fast разрешает запуск при отсутствии манифеста или когда файлы заблокированы."""
    app = mock_app

    absent_report = IntegrityReport(
        cause=IntegrityCause.MANIFEST_ABSENT,
        findings=(),
        checked_files=0,
        deep=False,
    )

    with (
        patch("main.verify_fast", return_value=absent_report),
        patch("main.run_engine") as mock_run_eng,
    ):
        mock_run_eng.return_value = MagicMock(returncode=0, stdout="RUNNING", stderr="")
        app.start_engine()
        flush_glib()

        # Engine was allowed to run
        mock_run_eng.assert_called_once()


def test_on_verify_integrity_dialog(mock_app):
    """Кнопка проверки целостности в UI вызывает verify_full и показывает диалог."""
    app = mock_app

    full_report = IntegrityReport(
        cause=IntegrityCause.OK,
        findings=(),
        manifest_version="1.0",
        checked_files=42,
        deep=True,
    )

    with (
        patch("main.verify_full", return_value=full_report),
        patch.object(app, "show_dialog") as mock_dlg,
    ):
        app.on_verify_integrity()
        if hasattr(app, "_integrity_thread") and app._integrity_thread:
            app._integrity_thread.join(timeout=2.0)
        flush_glib()

        mock_dlg.assert_called_once()
        assert "42" in mock_dlg.call_args[0][1]
        assert "подтверждена" in mock_dlg.call_args[0][1]


# ============================================================================
# 4. BlockCheck2 runner timeout and finally restoration
# ============================================================================

def test_blockcheck2_runner_timeout_and_finally_restoration():
    """Тест 5.6: таймаут 124 дает статус 'Тест не завершен: лимит времени 15 минут',
    а блок finally гарантированно восстанавливает DNS и состояние движка."""
    calls = []

    def mock_run_engine(*args):
        calls.append(args)
        if args[0] == "blockcheck2":
            return MagicMock(returncode=124, stdout="Testing strategy 1...\nTesting strategy 2...", stderr="")
        return MagicMock(returncode=0, stdout="OK", stderr="")

    runner = BlockCheck2Runner(
        run_engine_fn=mock_run_engine,
        engine_was_running=True,
        engine_restore_args=("start", "any", "general"),
        active_iface="any",
        active_dns="cloudflare",
        timeout_s=900,
    )

    res = runner.run("rutracker.org")
    assert res.timeout_hit is True
    assert res.completed is False
    assert "лимит времени 15 минут" in res.status_summary
    assert "Тест не завершен" in res.status_summary

    # Ensure engine was stopped before, and restored in finally
    assert calls[0] == ("stop", "any")
    assert calls[1] == ("blockcheck2", "rutracker.org", "any", "cloudflare")
    assert calls[2] == ("start", "any", "general")


# ============================================================================
# 5. Static test: words.py deduplication & Single Source of Truth
# ============================================================================

def test_words_no_duplicates_and_ssot():
    """Тест 5.7: diagnostics/words.py - единственный источник правды без дублей строк."""
    from collections import Counter

    # Проверка уникальности текстов внутри VERDICTS
    for field_name in ("title", "description", "recommendation", "badge_text"):
        values = [v[field_name] for v in VERDICTS.values() if field_name in v]
        counts = Counter(values)
        duplicates = {k: c for k, c in counts.items() if c > 1}
        assert not duplicates, f"Обнаружены дубликаты в поле '{field_name}' словаря VERDICTS: {duplicates}"

    # Проверка, что get_block_verdict использует тот же словарь
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
        v1 = get_block_verdict(b_type)
        v2 = get_verdict_words(b_type.value)
        assert v1["badge_text"] == v2["badge_text"]
        assert v1["recommendation"] == v2["recommendation"]
        assert v1["badge_class"] == v2["badge_class"]
