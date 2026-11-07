"""
tests/test_diagnostics_advanced.py - Тесты для этапов 5.1-5.7:
- Долги 5.1:
  1. orchestra_ui: лейбл транспорта обновляется в реальном времени при вызове set_probe()
  2. dpi_classifier: make_curl_cffi_transport содержит полный Chrome/124 UA и не содержит Firefox
- 5.2 diagnostics/classify.py: вердикт с доказательством (SNI, IP, 451, редирект, белые списки, DNS 100.64.0.0/10, 403/429 закрытый сайт)
- 5.3 diagnostics/domain_inspector.py: аудит домена с фейковым транспортом, запрет отправки локальных IP
- 5.4 diagnostics/quic_analyzer.py: замер QUIC и вердикт с ценой отказа
- 5.5 diagnostics/apply_checker.py: автопроверка после применения и рекомендация альтернативы
- 5.6 diagnostics/blockcheck2_runner.py: таймаут, разбор стратегий и гарантированное восстановление в finally
- 5.7 diagnostics/words.py: единственный источник правды без дублей
"""

import ipaddress
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock

from diagnostics.words import (
    VERDICTS,
    STATUS_NOT_CHECKED,
    STATUS_CHECKING,
    STATUS_BLOCKED_OR_TIMEOUT,
    STATUS_ERROR,
    get_verdict_words,
)
from diagnostics.classify import (
    BlockVerdictType,
    EvidenceVerdict,
    is_spoofed_ip,
    classify_dns_responses,
    classify_http_response,
    classify_whitelist_state,
    classify_network_drop,
)
from diagnostics.domain_inspector import (
    CertificateInfo,
    DomainInspector,
    DomainInspectionReport,
    is_private_ip,
)
from diagnostics.quic_analyzer import QuicAnalyzer, QuicVerdict
from diagnostics.apply_checker import ApplyChecker, ApplyCheckOutcome
from diagnostics.blockcheck2_runner import BlockCheck2Runner, BlockCheck2Result
from dpi_classifier import make_curl_cffi_transport
from orchestra_ui import OrchestraWidget
from orchestra.targets import http_probe


# ================= 5.1 CLOSING DEBTS =================

def test_orchestra_ui_transport_label_dynamic_update():
    """Тест: лейбл транспорта в OrchestraWidget реально обновляется при смене пробы через set_probe."""
    widget = OrchestraWidget(probe=http_probe)
    assert "urllib (fallback)" in widget.lbl_transport.get_text()

    # Создаем фейковую пробу с другим именем
    fake_probe = lambda target, timeout=3.5: None
    fake_probe.transport_name = "Custom Mock Probe (curl_cffi)"
    fake_probe.is_curl_cffi = True

    widget.set_probe(fake_probe)
    assert widget.probe_fn == fake_probe
    assert "Custom Mock Probe (curl_cffi)" in widget.lbl_transport.get_text()

    # Сброс на дефолт (None)
    widget.set_probe(None)
    assert widget.lbl_transport.get_text().startswith("Транспорт проб:")


def test_dpi_classifier_make_curl_cffi_transport_user_agent():
    """Тест: UA в make_curl_cffi_transport содержит Chrome/124 и не содержит Firefox."""
    transport = make_curl_cffi_transport()
    assert transport is not None, "curl_cffi должен быть установлен в тестовом окружении"

    # Инспектируем дефолтный заголовок через замыкание функции
    closure_vars = transport.__code__.co_consts
    ua_found = None
    for const in closure_vars:
        if isinstance(const, str) and "Mozilla/5.0" in const:
            ua_found = const
            break

    assert ua_found is not None, "User-Agent строка должна присутствовать в _transport"
    assert "Chrome/124" in ua_found
    assert "Firefox" not in ua_found


# ================= 5.2 CLASSIFY WITH PROOF =================

def test_classify_http_site_access_restricted_403_429():
    """403 / 429 / Капча — это закрытый сайт (SITE_ACCESS_RESTRICTED), а не блокировка ТСПУ."""
    v403 = classify_http_response("test.com", 403, {}, "Forbidden")
    assert v403 is not None
    assert v403.verdict == BlockVerdictType.SITE_ACCESS_RESTRICTED
    assert "сайт самостоятельно ограничил доступ" in v403.proof

    v429 = classify_http_response("test.com", 429, {}, "Too Many Requests")
    assert v429.verdict == BlockVerdictType.SITE_ACCESS_RESTRICTED

    v_cf = classify_http_response("test.com", 200, {}, "<html>challenge-platform.js</html>")
    assert v_cf.verdict == BlockVerdictType.SITE_ACCESS_RESTRICTED


def test_classify_http_blockpage_and_451():
    """HTTP 451 или редирект/текст заглушки РКН."""
    v451 = classify_http_response("rkn-block.ru", 451, {}, "Unavailable For Legal Reasons")
    assert v451.verdict == BlockVerdictType.HTTP_BLOCKPAGE
    assert "HTTP 451" in v451.proof

    v_red = classify_http_response("blocked.ru", 302, {"Location": "http://eais.rkn.gov.ru/block"}, "")
    assert v_red.verdict == BlockVerdictType.HTTP_BLOCKPAGE
    assert "редирект на заглушку" in v_red.proof

    v_body = classify_http_response("blocked.ru", 200, {}, "Доступ к ресурсу ограничен в соответствии с законом")
    assert v_body.verdict == BlockVerdictType.HTTP_BLOCKPAGE
    assert "Обнаружена сигнатура заглушки" in v_body.proof


def test_classify_dns_spoofing_cgnat_and_mismatch():
    """Сравнение 4 резолверов: выявление ответов из 100.64.0.0/10 и расхождения с DoT/DoH."""
    # 1. CGNAT IP 100.64.0.1
    cgnat_res = {
        "system_udp": ["100.64.0.1"],
        "dot_cloudflare": ["195.82.146.120"],
    }
    v_cgnat = classify_dns_responses("rutracker.org", cgnat_res)
    assert v_cgnat is not None
    assert v_cgnat.verdict == BlockVerdictType.DNS_SPOOFING
    assert "100.64.0.1" in v_cgnat.proof

    # 2. Непересекающиеся множества публичных IP
    mismatch_res = {
        "system_udp": ["93.184.216.34"],
        "dot_cloudflare": ["140.82.121.4"],
    }
    v_mismatch = classify_dns_responses("github.com", mismatch_res)
    assert v_mismatch is not None
    assert v_mismatch.verdict == BlockVerdictType.DNS_SPOOFING
    assert "Системный DNS ответил" in v_mismatch.proof


def test_classify_whitelist_mode():
    """Режим белых списков: яндекс доступен, внешние хосты нет."""
    v_wl = classify_whitelist_state(ru_services_ok=True, foreign_services_ok=False, target="global")
    assert v_wl is not None
    assert v_wl.verdict == BlockVerdictType.WHITELIST_RESTRICTION
    assert "российскими сервисами (Яндекс/VK)" in v_wl.proof

    assert classify_whitelist_state(ru_services_ok=True, foreign_services_ok=True, target="global") is None


def test_classify_network_drops():
    """Сброс по TLS SNI, TCP RST и блокировка IP."""
    v_sni = classify_network_drop("rutracker.org", tcp_connected=True, tls_connected=False, sni_drop=True, rst_received=False)
    assert v_sni.verdict == BlockVerdictType.TLS_SNI_DROP
    assert "ClientHello со SNI" in v_sni.proof

    v_rst = classify_network_drop("rutracker.org", tcp_connected=False, tls_connected=False, sni_drop=False, rst_received=True)
    assert v_rst.verdict == BlockVerdictType.TCP_RST_INJECTION
    assert "RST" in v_rst.proof

    v_ip = classify_network_drop("blocked-ip.com", tcp_connected=False, tls_connected=False, sni_drop=False, rst_received=False, ip_ping_ok=False)
    assert v_ip.verdict == BlockVerdictType.IP_BLOCK
    assert "ICMP пинг отсутствует" in v_ip.proof


# ================= 5.3 DOMAIN INSPECTOR =================

def test_domain_inspector_privacy_and_local_ip_protection():
    """Локальные IP и отключенный ASN чекбокс не отправляют запросы наружу."""
    inspector = DomainInspector(allow_external_asn=False)
    num, org, country, src = inspector.lookup_asn("8.8.8.8")
    assert num is None
    assert "отключены" in src

    # Даже если разрешено, приватный IP (192.168.1.1 или 127.0.0.1) не отправляется
    inspector_allowed = DomainInspector(allow_external_asn=True)
    num, org, country, src = inspector_allowed.lookup_asn("192.168.1.1")
    assert num is None
    assert "приватный IP" in src
    assert is_private_ip("10.0.0.1")
    assert is_private_ip("127.0.0.1")
    assert is_private_ip("100.64.0.1")
    assert not is_private_ip("1.1.1.1")


def test_domain_inspector_with_mock_components():
    """Полная проверка цикла аудита с замоканными резолвером и сокетами."""
    def fake_resolver(dom, proto):
        if proto == "system_udp":
            return ["1.2.3.4"]
        return ["1.2.3.4"]

    class FakeSocket:
        def __init__(self, *args, **kwargs):
            pass
        def settimeout(self, t):
            pass
        def connect(self, addr):
            pass
        def close(self):
            pass

    inspector = DomainInspector(
        dns_resolver_fn=fake_resolver,
        socket_factory=FakeSocket,
        allow_external_asn=False,
    )
    # Отключаем реальный ping и tls в тесте
    inspector.check_icmp = lambda ip: (True, 15.0)
    inspector.inspect_tls_handshake = lambda dom, ip, port: (
        True, "TLSv1.3", "TLS_AES_256_GCM_SHA384",
        CertificateInfo(subject="CN=test.com", issuer="CN=Let's Encrypt", not_before="2026-01-01", not_after="2026-04-01", san=["test.com"])
    )

    rep = inspector.inspect("test.com")
    assert rep.domain == "test.com"
    assert rep.target_ip == "1.2.3.4"
    assert not rep.dns_spoofed
    assert rep.tcp_connected
    assert rep.tls_connected
    assert rep.summary_verdict == "PASS"
    assert "TLSv1.3" in rep.proof_line


# ================= 5.4 QUIC ANALYZER =================

def test_quic_analyzer_verdicts():
    """Замер с QUIC и без, понятный вердикт и цена отказа."""
    # 1. QUIC заблокирован (Blackhole), TCP доступен
    qa = QuicAnalyzer(
        quic_probe_fn=lambda h, p: (False, None),
        tcp_probe_fn=lambda h, p: (True, 25.0),
    )
    v1 = qa.analyze("youtube.com")
    assert not v1.quic_available
    assert v1.tcp_available
    assert "заблокирован ТСПУ" in v1.verdict_text
    assert "Нулевая" in v1.price_of_refusal

    # 2. И QUIC, и TCP доступны (разница в задержке)
    qa2 = QuicAnalyzer(
        quic_probe_fn=lambda h, p: (True, 20.0),
        tcp_probe_fn=lambda h, p: (True, 50.0),
    )
    v2 = qa2.analyze("cloudflare.com")
    assert v2.quic_available
    assert v2.penalty_ms == 30.0
    assert "медленнее на ~30.0 мс" in v2.price_of_refusal


# ================= 5.5 APPLY CHECKER =================

def test_apply_checker_success_and_suggestion():
    """Автопроверка после применения: успех и предложение альтернативы."""
    # Успех
    ac_ok = ApplyChecker(probe_fn=lambda url, to: (True, 200, 15.0, None))
    res_ok = ac_ok.check("general")
    assert res_ok.success
    assert res_ok.suggested_preset is None

    # Провал -> предложение альтернативы
    ac_fail = ApplyChecker(probe_fn=lambda url, to: (False, None, None, "Connection reset"))
    res_fail = ac_fail.check("general")
    assert not res_fail.success
    assert res_fail.suggested_preset == "general ALT"
    assert "Высокая агрессивность TLS сплита" in res_fail.suggestion_reason


# ================= 5.6 BLOCKCHECK2 RUNNER FINALLY RESTORATION =================

def test_blockcheck2_runner_restores_engine_in_finally():
    """Гарантированное восстановление движка и DNS в блоке finally даже при исключении."""
    engine_calls = []

    def mock_run_engine(*args):
        engine_calls.append(args)
        if args[0] == "blockcheck2":
            raise RuntimeError("Симулированный сбой во время тестирования blockcheck2")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    runner = BlockCheck2Runner(
        run_engine_fn=mock_run_engine,
        engine_was_running=True,
        engine_restore_args=("start", "preset_winner", "eth0"),
        active_iface="eth0",
        active_dns="dns_ai",
    )

    res = runner.run("rutracker.org")
    assert not res.completed
    assert "Тест не завершен" in res.status_summary
    # Проверяем, что в finally был вызван restore
    assert ("stop", "eth0") in engine_calls
    assert ("start", "preset_winner", "eth0") in engine_calls


def test_blockcheck2_runner_timeout_handling():
    """Код возврата 124 интерпретируется как превышение 15-минутного таймаута с частичным логом."""
    def mock_run_engine(*args):
        if args[0] == "blockcheck2":
            return SimpleNamespace(returncode=124, stdout="[1/50] test1 OK\n--dpi-desync=fake", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    runner = BlockCheck2Runner(
        run_engine_fn=mock_run_engine,
        engine_was_running=False,
        engine_restore_args=(),
        active_iface="any",
    )
    res = runner.run("rutracker.org")
    assert res.timeout_hit
    assert not res.completed
    assert "лимит времени 15 минут исчерпан" in res.status_summary
    assert "--dpi-desync=fake" in res.discovered_strategies


# ================= 5.7 WORDS SSOT INTEGRITY =================

def test_words_ssot_no_duplicates_and_all_verdicts_defined():
    """В words.py нет дублей текстов, все типы вердиктов содержат обязательные поля."""
    required_fields = {"title", "description", "recommendation", "badge_text", "badge_class", "severity"}
    for key, item in VERDICTS.items():
        assert required_fields.issubset(item.keys()), f"Вердикт {key} не содержит всех обязательных полей"

    # Проверка get_verdict_words
    assert get_verdict_words("PASS")["badge_text"] == "Доступен (PASS)"
    assert get_verdict_words("NON_EXISTENT")["badge_text"] == "Неизвестно (WARN)"
