#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for DPI Classifier & Diagnostics Engine."""
from __future__ import annotations

import json
import socket
from unittest.mock import MagicMock

import pytest

from dpi_classifier import (
    BlockType,
    ClassificationResult,
    DiagnosticReport,
    DPIClassifier,
    classify_domains,
    detect_blockpage_content,
    generate_chrome_client_hello,
    generate_quic_initial_packet,
    is_bogon_ip,
    is_known_blockpage_ip,
    parse_client_hello,
)


# ===========================================================================
# 1. Tests for Chrome ClientHello & QUIC Packet Generation
# ===========================================================================

class TestPacketGenerators:
    """Проверка байтовой генерации Chrome ClientHello и QUIC Initial."""

    def test_client_hello_record_and_handshake_structure(self):
        raw = generate_chrome_client_hello("example.com")
        assert len(raw) > 100
        # TLS Plaintext Record
        assert raw[0] == 0x16       # Handshake
        assert raw[1:3] == b"\x03\x01"  # TLS 1.0 record legacy version

        parsed = parse_client_hello(raw)
        assert parsed["client_version"] == 0x0303  # TLS 1.2
        assert len(parsed["random"]) == 32
        assert len(parsed["session_id"]) == 32
        assert parsed["sni"] == "example.com"
        assert "h2" in parsed["alpn"]
        assert "http/1.1" in parsed["alpn"]
        assert parsed["has_grease"] is True

    def test_client_hello_idna_hostname(self):
        raw = generate_chrome_client_hello("тест.рф")
        parsed = parse_client_hello(raw)
        assert parsed["sni"] == "тест.рф"

    def test_client_hello_grease_toggle(self):
        raw_grease = generate_chrome_client_hello("site.org", grease=True)
        raw_no_grease = generate_chrome_client_hello("site.org", grease=False)
        parsed_grease = parse_client_hello(raw_grease)
        parsed_no_grease = parse_client_hello(raw_no_grease)

        assert parsed_grease["has_grease"] is True
        assert parsed_no_grease["has_grease"] is False

    def test_client_hello_custom_alpn(self):
        raw = generate_chrome_client_hello("api.org", alpn_protocols=["h3", "h2"])
        parsed = parse_client_hello(raw)
        assert parsed["alpn"] == ["h3", "h2"]

    def test_parse_client_hello_invalid_data(self):
        with pytest.raises(ValueError, match="Too short"):
            parse_client_hello(b"\x16\x03")

        with pytest.raises(ValueError, match="Not a handshake record"):
            parse_client_hello(b"\x17\x03\x01\x00\x05hello")

        with pytest.raises(ValueError, match="Not a ClientHello"):
            # Handshake type 0x02 = ServerHello
            body = b"\x02\x00\x00\x02\x03\x03"
            header = b"\x16\x03\x01\x00" + bytes([len(body)])
            parse_client_hello(header + body)

    def test_quic_initial_packet_format(self):
        dcid = b"\x01\x02\x03\x04\x05\x06\x07\x08"
        scid = b"\x08\x07\x06\x05\x04\x03\x02\x01"
        packet = generate_quic_initial_packet(dcid=dcid, scid=scid, min_size=1200)

        # QUIC Initial must be at least 1200 bytes by RFC 9000
        assert len(packet) >= 1200
        # Long Header (0xC0)
        assert packet[0] == 0xC0
        # Version 1 (0x00000001)
        assert packet[1:5] == b"\x00\x00\x00\x01"
        # DCID len (8) + DCID
        assert packet[5] == 8
        assert packet[6:14] == dcid
        # SCID len (8) + SCID
        assert packet[14] == 8
        assert packet[15:23] == scid


# ===========================================================================
# 2. Tests for DNS Spoofing Classification
# ===========================================================================

class TestDNSSpoofing:
    """Проверка выявления DNS подмены и отравления кэша."""

    def test_bogon_ip_detection(self):
        assert is_bogon_ip("127.0.0.1") is True
        assert is_bogon_ip("0.0.0.0") is True
        assert is_bogon_ip("10.0.0.1") is True
        assert is_bogon_ip("192.168.1.1") is True
        assert is_bogon_ip("172.16.5.4") is True
        assert is_bogon_ip("169.254.1.1") is True
        assert is_bogon_ip("::1") is True
        assert is_bogon_ip("93.184.216.34") is False
        assert is_bogon_ip("invalid-ip") is False

    def test_known_blockpage_ip_detection(self):
        assert is_known_blockpage_ip("195.82.146.120") is True
        assert is_known_blockpage_ip("95.173.136.70") is True
        assert is_known_blockpage_ip("8.8.8.8") is False

    def test_dns_bogon_classified_as_spoofing(self):
        classifier = DPIClassifier(
            dns_resolver=lambda d: ["127.0.0.1"]
        )
        res = classifier.classify("blocked-service.com")
        assert res.block_type == BlockType.DNS_SPOOFING
        assert res.is_blocked is True
        assert "bogon" in res.details.lower()
        assert res.ip == "127.0.0.1"

    def test_dns_rkn_ip_classified_as_spoofing(self):
        classifier = DPIClassifier(
            dns_resolver=lambda d: ["195.82.146.120"]
        )
        res = classifier.classify("rutracker.org")
        assert res.block_type == BlockType.DNS_SPOOFING
        assert "blockpage" in res.details.lower()
        assert res.ip == "195.82.146.120"

    def test_dns_mismatch_with_trusted_resolver(self):
        classifier = DPIClassifier(
            dns_resolver=lambda d: ["99.88.77.66"],
            trusted_dns_resolver=lambda d: ["1.1.1.1", "1.0.0.1"],
        )
        is_spoofed, ip, details = classifier.check_dns("google.com")
        assert is_spoofed is True
        assert "mismatch" in details.lower()

    def test_dns_direct_ip_skips_spoofing(self):
        classifier = DPIClassifier(dns_resolver=lambda d: ["127.0.0.1"])
        is_spoofed, ip, details = classifier.check_dns("8.8.8.8")
        assert is_spoofed is False
        assert ip == "8.8.8.8"


# ===========================================================================
# 3. Tests for TCP RST Injection
# ===========================================================================

class TestTCPRSTInjection:
    """Проверка детекции активного инжекта TCP RST со стороны ТСПУ."""

    def test_rst_during_tcp_handshake(self):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionResetError("Connection reset by peer")

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["93.184.216.34"],
            socket_factory=lambda *a, **kw: mock_sock,
        )

        res = classifier.classify("reset-me.com")
        assert res.block_type == BlockType.TCP_RST_INJECTION
        assert "TCP RST" in res.details
        assert res.ip == "93.184.216.34"

    def test_rst_injected_after_tls_client_hello(self):
        mock_sock = MagicMock()
        # TCP connect проходит успешно
        mock_sock.connect.return_value = None
        # Но как только DPI видит заблокированный SNI в ClientHello — прилетает RST на recv()
        mock_sock.recv.side_effect = ConnectionResetError("Connection reset by peer")

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["142.250.74.206"],
            socket_factory=lambda *a, **kw: mock_sock,
        )

        res = classifier.classify("youtube.com")
        assert res.block_type == BlockType.TCP_RST_INJECTION
        assert "TCP RST injected after TLS ClientHello" in res.details
        assert "youtube.com" in res.details

    def test_rst_injected_during_http_request(self):
        """Если TLS прошел, но на открытом HTTP порту прилетает RST."""
        # 1-й сокет (TCP handshake 443): OK
        sock1 = MagicMock()
        sock1.connect.return_value = None
        # ServerHello OK
        sock1.recv.return_value = b"\x16\x03\x03\x00\x40ServerHello"

        # 2-й сокет (HTTP 80): RST
        sock2 = MagicMock()
        sock2.connect.return_value = None
        sock2.sendall.side_effect = ConnectionResetError("RST on HTTP")

        sockets = [sock1, sock2]

        def fake_socket_factory(*a, **kw):
            return sockets.pop(0) if sockets else MagicMock()

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["1.2.3.4"],
            socket_factory=fake_socket_factory,
        )

        res = classifier.classify("http-rst.org", check_quic_flag=False)
        assert res.block_type == BlockType.TCP_RST_INJECTION
        assert "TCP RST" in res.details

    def test_silent_close_after_sni(self):
        mock_sock = MagicMock()
        mock_sock.connect.return_value = None
        mock_sock.recv.return_value = b""  # Immediate FIN/empty

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["1.2.3.4"],
            socket_factory=lambda *a, **kw: mock_sock,
        )

        block_type, details = classifier.check_tls_sni("test.com", "1.2.3.4")
        assert block_type == BlockType.TCP_RST_INJECTION
        assert "closed immediately" in details.lower()


# ===========================================================================
# 4. Tests for TLS SNI Drop (Blackhole)
# ===========================================================================

class TestTLSSNIDrop:
    """Проверка детекции silent drop пакетов после передачи SNI."""

    def test_tls_sni_drop_timeout(self):
        mock_sock = MagicMock()
        # TCP handshake успешен
        mock_sock.connect.return_value = None
        # Но при чтении ServerHello сокет таймаутится (ТСПУ дропает пакеты)
        mock_sock.recv.side_effect = socket.timeout("timed out")

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["104.16.132.229"],
            socket_factory=lambda *a, **kw: mock_sock,
        )

        res = classifier.classify("rutracker.org")
        assert res.block_type == BlockType.TLS_SNI_DROP
        assert "packet dropped by DPI for SNI" in res.details
        assert "rutracker.org" in res.details
        assert res.is_blocked is True

    def test_tls_alert_treated_as_clean(self):
        mock_sock = MagicMock()
        mock_sock.connect.return_value = None
        # Сервер ответил TLS Alert (0x15, 0x03)
        mock_sock.recv.return_value = b"\x15\x03\x03\x00\x02\x02\x70"

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["1.1.1.1"],
            socket_factory=lambda *a, **kw: mock_sock,
        )

        block_type, details = classifier.check_tls_sni("alert.com", "1.1.1.1")
        assert block_type is None
        assert "TLS Alert received" in details


# ===========================================================================
# 5. Tests for HTTP Blockpage Detection
# ===========================================================================

class TestHTTPBlockpage:
    """Проверка детекции страниц-заглушек и редиректов провайдеров / РКН."""

    def test_detect_status_451(self):
        is_block, reason = detect_blockpage_content(451, {}, "")
        assert is_block is True
        assert "451" in reason

    def test_detect_redirect_to_rkn(self):
        is_block, reason = detect_blockpage_content(
            302,
            {"Location": "https://eais.rkn.gov.ru/?url=http://site.com"},
            "",
        )
        assert is_block is True
        assert "eais.rkn.gov.ru" in reason

    def test_detect_redirect_to_provider_warning(self):
        is_block, reason = detect_blockpage_content(
            301,
            {"Location": "http://warning.rt.ru/index.html"},
            "",
        )
        assert is_block is True
        assert "warning.rt.ru" in reason

    def test_detect_html_body_signatures(self):
        body_snippets = [
            "<h1>Доступ ограничен</h1><p>Сайт внесен в Единый реестр запрещенных сайтов</p>",
            "<div>Страница заблокирована по решению суда</div>",
            "<p>На основании положений Федерального закона 149-ФЗ доступ закрыт</p>",
            "<div>Access Denied: blocked by RKN order</div>",
        ]
        for snippet in body_snippets:
            is_block, reason = detect_blockpage_content(200, {}, snippet)
            assert is_block is True, f"Failed to detect blockpage in snippet: {snippet}"

    def test_clean_html_passes(self):
        clean_body = "<html><body><h1>Welcome to My Blog</h1><p>Articles about programming</p></body></html>"
        is_block, reason = detect_blockpage_content(200, {}, clean_body)
        assert is_block is False

    def test_http_blockpage_classification_integration(self):
        # 1-й сокет (TCP 443): ServerHello OK
        sock_tls = MagicMock()
        sock_tls.connect.return_value = None
        sock_tls.recv.return_value = b"\x16\x03\x03\x00\x40ServerHello"

        # 2-й сокет (HTTP 80): Возвращает заглушку Ростелекома
        sock_http = MagicMock()
        sock_http.connect.return_value = None
        http_response = (
            b"HTTP/1.1 302 Found\r\n"
            b"Location: http://warning.rt.ru/blocked\r\n"
            b"Content-Length: 0\r\n\r\n"
        )
        sock_http.recv.side_effect = [http_response, b""]

        sockets = [sock_tls, sock_http]

        def fake_socket_factory(*a, **kw):
            return sockets.pop(0) if sockets else MagicMock()

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["178.248.232.1"],
            socket_factory=fake_socket_factory,
        )

        res = classifier.classify("site-with-blockpage.com", check_quic_flag=False)
        assert res.block_type == BlockType.HTTP_BLOCKPAGE
        assert "warning.rt.ru" in res.details
        assert res.is_blocked is True


# ===========================================================================
# 6. Tests for QUIC Blackhole / UDP Drop
# ===========================================================================

class TestQUICBlackhole:
    """Проверка выявления блокировки UDP 443 рукопожатий."""

    def test_quic_timeout_classification(self):
        udp_mock = MagicMock()
        udp_mock.recvfrom.side_effect = socket.timeout("timed out")

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["142.250.180.14"],
            socket_factory=lambda *a, **kw: udp_mock,
        )

        res = classifier.classify_quic("youtube.com")
        assert res.block_type == BlockType.QUIC_BLACKHOLE
        assert "dropped" in res.details.lower()
        assert res.is_blocked is True

    def test_quic_pass_when_response_received(self):
        udp_mock = MagicMock()
        # Ответ Version Negotiation или Initial ACK
        udp_mock.recvfrom.return_value = (b"\x80\x00\x00\x00\x01\x00\x00", ("142.250.180.14", 443))

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["142.250.180.14"],
            socket_factory=lambda *a, **kw: udp_mock,
        )

        res = classifier.classify_quic("youtube.com")
        assert res.block_type == BlockType.PASS
        assert res.is_blocked is False

    def test_quic_scheme_target_triggers_quic_mode(self):
        udp_mock = MagicMock()
        udp_mock.recvfrom.side_effect = socket.timeout("timed out")

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["1.1.1.1"],
            socket_factory=lambda *a, **kw: udp_mock,
        )

        res = classifier.classify("quic://cloudflare.com")
        assert res.block_type == BlockType.QUIC_BLACKHOLE

    def test_block_type_aliases(self):
        assert BlockType.UDP_DROP == BlockType.QUIC_BLACKHOLE
        assert BlockType.OK == BlockType.PASS


# ===========================================================================
# 7. Tests for Clean Traffic & General Failures (PASS, TIMEOUT, ERROR)
# ===========================================================================

class TestTrafficPassAndErrors:
    """Проверка нормального прохождения трафика и обработки общих сбоев."""

    def test_traffic_passes_cleanly(self):
        # 1-й сокет (TCP 443 + TLS): Успешно
        sock_tls = MagicMock()
        sock_tls.connect.return_value = None
        sock_tls.recv.return_value = b"\x16\x03\x03\x00\x40ServerHello"

        # 2-й сокет (HTTP 80): Обычный ответ без блокировок
        sock_http = MagicMock()
        sock_http.connect.return_value = None
        sock_http.recv.side_effect = [
            b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n\r\n<h1>Clean page</h1>",
            b"",
        ]

        # 3-й сокет (QUIC UDP 443): Ответ получен
        sock_udp = MagicMock()
        sock_udp.recvfrom.return_value = (b"\x80\x00\x00\x00\x01", ("93.184.216.34", 443))

        sockets = [sock_tls, sock_http, sock_udp]

        def fake_socket_factory(*a, **kw):
            return sockets.pop(0) if sockets else MagicMock()

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["93.184.216.34"],
            socket_factory=fake_socket_factory,
        )

        res = classifier.classify("example.com")
        assert res.block_type == BlockType.PASS
        assert res.is_blocked is False
        assert "cleanly" in res.details

    def test_tcp_connect_timeout_classified_as_timeout(self):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = socket.timeout("connect timed out")

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["1.1.1.1"],
            socket_factory=lambda *a, **kw: mock_sock,
        )

        res = classifier.classify("timeout-target.com")
        assert res.block_type == BlockType.TIMEOUT
        assert "timeout" in res.details.lower()

    def test_unresolvable_domain_classified_as_error(self):
        classifier = DPIClassifier(dns_resolver=lambda d: [])
        res = classifier.classify("non-existent-domain-xyz.local")
        assert res.block_type == BlockType.ERROR
        assert "could not resolve" in res.details.lower()

    def test_empty_target_classified_as_error(self):
        classifier = DPIClassifier()
        res = classifier.classify("")
        assert res.block_type == BlockType.ERROR

    def test_socket_exception_classified_as_error(self):
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = OSError("Network is unreachable")

        classifier = DPIClassifier(
            dns_resolver=lambda d: ["1.2.3.4"],
            socket_factory=lambda *a, **kw: mock_sock,
        )

        res = classifier.classify("unreachable.net")
        assert res.block_type == BlockType.ERROR


# ===========================================================================
# 8. Tests for Diagnostics Report & Multi-target Runs
# ===========================================================================

class TestDiagnosticReport:
    """Проверка генерации структурированных отчетов."""

    def test_report_summary_and_serialization(self):
        results = [
            ClassificationResult("youtube.com", BlockType.TLS_SNI_DROP, "142.250.74.206", "SNI drop"),
            ClassificationResult("discord.com", BlockType.TCP_RST_INJECTION, "162.159.138.232", "RST"),
            ClassificationResult("rutracker.org", BlockType.HTTP_BLOCKPAGE, "195.82.146.120", "Blockpage"),
            ClassificationResult("google.com", BlockType.PASS, "142.250.74.14", "Pass"),
        ]

        report = DiagnosticReport(results=results, duration_ms=150)
        assert report.total_count == 4
        assert report.blocked_count == 3
        assert report.summary["TLS_SNI_DROP"] == 1
        assert report.summary["TCP_RST_INJECTION"] == 1
        assert report.summary["HTTP_BLOCKPAGE"] == 1
        assert report.summary["PASS"] == 1

        # Сериализация в dict и JSON
        d = report.to_dict()
        assert d["total_count"] == 4
        assert len(d["results"]) == 4

        json_str = report.to_json()
        data = json.loads(json_str)
        assert data["summary"]["PASS"] == 1

        # Форматированный текстовый отчет
        summary_text = report.summary_text()
        assert "DPI CLASSIFIER DIAGNOSTIC REPORT" in summary_text
        assert "youtube.com" in summary_text
        assert "TLS_SNI_DROP" in summary_text

    def test_run_diagnostics_parallel_ordering(self):
        """Проверка, что результаты в параллельном прогоне возвращаются в исходном порядке targets."""
        def mock_dns(target):
            return ["1.2.3.4"]

        # Создадим сокеты, возвращающие ServerHello
        def fake_socket_factory(*a, **kw):
            m = MagicMock()
            m.connect.return_value = None
            m.recv.return_value = b"\x16\x03\x03\x00\x40ServerHello"
            m.recvfrom.return_value = (b"\x00", ("1.2.3.4", 443))
            return m

        classifier = DPIClassifier(
            dns_resolver=mock_dns,
            socket_factory=fake_socket_factory,
        )

        targets = ["alpha.com", "beta.org", "gamma.net"]
        report = classifier.run_diagnostics(targets, max_workers=3, check_http=False, check_quic_flag=False)

        assert report.total_count == 3
        assert [r.target for r in report.results] == targets
        for r in report.results:
            assert r.block_type == BlockType.PASS

    def test_classify_domains_helper(self):
        report = classify_domains([])
        assert report.total_count == 0
        assert report.duration_ms == 0
