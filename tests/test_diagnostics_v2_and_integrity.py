"""
tests/test_diagnostics_v2_and_integrity.py - Тесты для этапа 5.3:
1. diagnostics/block_cause.py и diagnostics/verdict.py (разделение collect и judge).
2. DNS: запрет вывода о подмене только по несовпадению IP. Подтверждение сертификата на Anycast/CDN.
   Отдельно исходы из 100.64.0.0/10 и фиктивных IP.
3. Пробы причины: recased имя, allowed имена (max.ru, ya.ru, vk.com) для белых списков, HTTP 80 451.
4. Окно приёма: 1 байт (дважды) против контроля 1 КБ (вердикт wssize).
5. Расширенные исходы judge_service:
   - открывается (OK)
   - открывается через раз (UNSTABLE)
   - грузится не до конца (CUT_WINDOW)
   - нет адреса (NO_ADDRESS)
   - основной открывается, но сломаны вторичные (SECONDARY_BROKEN)
   - сайт закрыт сам с 403, 429 или капчей (SITE_RESTRICTED)
6. install_integrity: fast (размер+наличие) и full (SHA-256) на временных каталогах.
   Заблокированный файл не считать повреждением (CORRUPTED), retry delays (0.2, 0.5, 1.0 с).
"""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import time
from unittest.mock import MagicMock

import pytest

from diagnostics.block_cause import (
    ALLOWED_NAMES,
    CONTROL_WINDOW_BYTES,
    HELLO_ALERT,
    HELLO_CONNECT,
    HELLO_OK,
    HELLO_RESET,
    HELLO_TIMEOUT,
    NEUTRAL_NAME,
    SMALL_WINDOW_BYTES,
    CauseFacts,
    CauseVerdict,
    HelloResult,
    HttpFacts,
    case_variant,
    is_reply_window_proven,
    judge_cause,
)
from diagnostics.verdict import (
    DnsJudgement,
    DnsState,
    ServiceJudgement,
    ServiceReachState,
    is_clearly_bogus_ip,
    judge_dns,
    judge_service,
)
from install_integrity import (
    InstallManifest,
    IntegrityCause,
    ManifestEntry,
    build_manifest,
    load_manifest,
    verify_fast,
    verify_full,
    verify_installation,
    write_manifest,
)


# ================= 1. JUDGE CAUSE & PROBES =================

def test_case_variant_generation():
    """Тест переворота регистра последней части домена."""
    assert case_variant("googlevideo.com") == "googlevideo.COM"
    assert case_variant("rutracker.ORG") == "rutracker.org"
    assert case_variant("localhost") == ""


def test_judge_cause_reply_window_wssize():
    """Окно приёма: 1 байт ответило дважды подряд, 1 КБ сброшено -> вердикт TLS_REPLY_WINDOW."""
    facts = CauseFacts(
        host="nnmclub.to",
        ip="104.21.43.11",
        real_hello=HelloResult(HELLO_RESET),
        neutral_hello=HelloResult(HELLO_RESET),
        nameless_hello=HelloResult(HELLO_RESET),
        small_window_1=HelloResult(HELLO_OK, rtt_ms=25.0, data_len=5),
        small_window_2=HelloResult(HELLO_OK, rtt_ms=26.0, data_len=5),
        window_control=HelloResult(HELLO_RESET),
    )
    assert is_reply_window_proven(facts.small_window_1, facts.small_window_2, facts.window_control)
    verdict = judge_cause(facts)
    assert verdict.cause_code == "TLS_REPLY_WINDOW"
    assert "wssize" in verdict.recommendation
    assert "С окном 1 байт" in verdict.proof


def test_judge_cause_reply_window_control_also_passes_not_window():
    """Если и контроль 1 КБ проходит, то дело не в окне ответа."""
    assert not is_reply_window_proven(
        HelloResult(HELLO_OK),
        HelloResult(HELLO_OK),
        HelloResult(HELLO_OK), # контроль тоже ответил
    )


def test_judge_cause_whitelist_restriction():
    """Режим белых списков: max.ru/vk.com отвечают, а целевой и example.com нет."""
    facts = CauseFacts(
        host="instagram.com",
        ip="157.240.247.174",
        real_hello=HelloResult(HELLO_TIMEOUT),
        neutral_hello=HelloResult(HELLO_TIMEOUT),
        nameless_hello=HelloResult(HELLO_TIMEOUT),
        allowed_hellos={
            "max.ru": HelloResult(HELLO_OK),
            "vk.com": HelloResult(HELLO_OK),
        },
    )
    verdict = judge_cause(facts)
    assert verdict.cause_code == "WHITELIST_RESTRICTION"
    assert "белыми списками" in verdict.recommendation
    assert "max.ru" in verdict.proof


def test_judge_cause_recased_sni():
    """Имя другим регистром проходит, оригинальное нет -> фильтр ищет буква в букву."""
    facts = CauseFacts(
        host="youtube.com",
        ip="142.250.180.206",
        real_hello=HelloResult(HELLO_RESET),
        neutral_hello=HelloResult(HELLO_RESET),
        nameless_hello=HelloResult(HELLO_RESET),
        recased_name="youtube.COM",
        recased_hello=HelloResult(HELLO_OK),
    )
    verdict = judge_cause(facts)
    assert verdict.cause_code == "TLS_SNI_DROP"
    assert "youtube.COM" in verdict.proof
    assert "буква в букву" in verdict.proof


def test_judge_cause_http_80_stub_and_451():
    """HTTP 80 возвращает 451 или заглушку РКН."""
    facts_451 = CauseFacts(
        host="blocked.org",
        ip="1.2.3.4",
        real_hello=HelloResult(HELLO_RESET),
        neutral_hello=HelloResult(HELLO_RESET),
        nameless_hello=HelloResult(HELLO_RESET),
        http=HttpFacts(status=451),
    )
    v451 = judge_cause(facts_451)
    assert v451.cause_code == "HTTP_BLOCKPAGE"
    assert "451" in v451.proof

    facts_stub = CauseFacts(
        host="blocked.org",
        ip="1.2.3.4",
        real_hello=HelloResult(HELLO_RESET),
        neutral_hello=HelloResult(HELLO_RESET),
        nameless_hello=HelloResult(HELLO_RESET),
        http=HttpFacts(status=302, location="http://warning.rt.ru/block"),
    )
    vstub = judge_cause(facts_stub)
    assert vstub.cause_code == "HTTP_BLOCKPAGE"
    assert "warning.rt.ru" in vstub.proof


# ================= 2. DNS JUDGEMENT & ANYCAST/CDN =================

def test_judge_dns_anycast_and_cdn_with_valid_cert_is_not_spoofed():
    """Anycast и CDN с разными IP и подлинным сертификатом - НЕ подмена!"""
    res = judge_dns(
        target="cloudflare.com",
        system_ips=("104.16.132.229",),
        reference_ips=("104.16.133.229",), # разные IP!
        cert_valid=True,
        cert_san_match=True,
        cert_issuer="Cloudflare Inc ECC CA-3",
    )
    assert res.state == DnsState.OK
    assert "CDN / Anycast" in res.reason
    assert "подлинный сертификат" in res.reason


def test_judge_dns_spoofed_when_cert_fails_or_mismatches():
    """Если IP отличаются и сертификат не валиден или чужой - это подмена."""
    res = judge_dns(
        target="rutracker.org",
        system_ips=("93.184.216.34",),
        reference_ips=("195.82.146.120",),
        cert_valid=False,
        cert_san_match=False,
        cert_issuer="Rostelecom Proxy CA",
    )
    assert res.state == DnsState.SPOOFED
    assert "Подмена DNS" in res.reason
    assert "Rostelecom" in res.proof


def test_judge_dns_clearly_bogus_ip_and_cgnat():
    """Ответы из 100.64.0.0/10 или 127.0.0.1 - безусловная подмена без проверки сертификата."""
    assert is_clearly_bogus_ip("100.64.0.1")
    assert is_clearly_bogus_ip("127.0.0.1")
    assert not is_clearly_bogus_ip("1.1.1.1")

    res_cgnat = judge_dns(
        target="rutracker.org",
        system_ips=("100.64.12.34",),
        reference_ips=("195.82.146.120",),
    )
    assert res_cgnat.state == DnsState.SPOOFED
    assert "CGNAT" in res_cgnat.proof


def test_judge_dns_no_address():
    """Пустой ответ системного DNS -> исход NO_ADDRESS."""
    res = judge_dns(
        target="nonexistent.xyz",
        system_ips=(),
        reference_ips=("1.2.3.4",),
    )
    assert res.state == DnsState.NO_ADDRESS


# ================= 3. EXTENDED SERVICE REACH JUDGEMENT =================

def test_judge_service_all_outcomes():
    """Проверка всех исходов пункта 5:
    - открывается
    - открывается через раз
    - грузится не до конца
    - нет адреса
    - основной открывается, но сломаны вторичные
    - сайт закрыт сам с 403, 429 или капчей
    """
    # 1. 403 / 429
    j_403 = judge_service(target="mysite.com", main_ok=False, http_status=403)
    assert j_403.state == ServiceReachState.SITE_RESTRICTED
    assert "403" in j_403.proof

    # 2. Нет адреса
    j_no_addr = judge_service(target="nodomain.com", main_ok=False, main_no_address=True)
    assert j_no_addr.state == ServiceReachState.NO_ADDRESS
    assert "не удалось узнать адрес" in j_no_addr.headline

    # 3. Грузится не до конца (cut_window 12–36 КБ)
    j_cut = judge_service(target="video.com", main_ok=False, main_body_cut=True)
    assert j_cut.state == ServiceReachState.CUT_WINDOW
    assert "грузится не до конца" in j_cut.headline

    # 4. Открывается через раз (unstable)
    j_unstable = judge_service(target="site.com", main_ok=True, main_unstable=True)
    assert j_unstable.state == ServiceReachState.UNSTABLE
    assert "через раз" in j_unstable.headline

    # 5. Основной открывается, но сломаны вторичные (CDN, API)
    j_sec = judge_service(target="discord.com", main_ok=True, secondary_broken_parts=("gateway.discord.gg", "cdn.discordapp.com"))
    assert j_sec.state == ServiceReachState.SECONDARY_BROKEN
    assert "gateway.discord.gg" in j_sec.headline

    # 6. Открывается штатно
    j_ok = judge_service(target="ya.ru", main_ok=True)
    assert j_ok.state == ServiceReachState.OK
    assert "открывается" in j_ok.headline


# ================= 4. INSTALL INTEGRITY FAST & FULL =================

def test_install_integrity_fast_and_full_verification():
    """Проверка целостности: fast (наличие и размер) и full (SHA-256) на временном каталоге."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "bin").mkdir()
        (root / "lua").mkdir()

        f1 = root / "bin" / "nfqws"
        f1.write_bytes(b"A" * 100)
        f2 = root / "lua" / "zapret.lua"
        f2.write_bytes(b"B" * 200)

        manifest = build_manifest(root, version="2.0.0", scopes=("bin", "lua"))
        write_manifest(manifest, root)

        # Fast verify
        rep_fast = verify_fast(root=root)
        assert rep_fast.ok
        assert rep_fast.cause == IntegrityCause.OK
        assert rep_fast.checked_files == 2
        assert not rep_fast.deep

        # Full verify
        rep_full = verify_full(root=root)
        assert rep_full.ok
        assert rep_full.deep

        # Симуляция повреждения содержимого (размер тот же, хэш другой)
        f1.write_bytes(b"C" * 100)
        # Fast не заметит (размер 100)
        rep_fast_corrupted = verify_fast(root=root)
        assert rep_fast_corrupted.ok

        # Full заметит несовпадение хэша
        rep_full_corrupted = verify_full(root=root)
        assert not rep_full_corrupted.ok
        assert rep_full_corrupted.cause == IntegrityCause.CORRUPTED
        assert "bin/nfqws" in rep_full_corrupted.corrupted


def test_install_integrity_locked_file_is_not_corrupted():
    """Заблокированный файл (OSError при чтении) не считается повреждением (CORRUPTED)."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "bin").mkdir()
        f1 = root / "bin" / "nfqws"
        f1.write_bytes(b"DATA123")

        manifest = build_manifest(root, version="2.0.0", scopes=("bin",))
        write_manifest(manifest, root)

        # Симулируем временную блокировку файла (OSError)
        def mock_sha256_err(path, retry_delays=None):
            raise PermissionError("File locked by antivirus")

        from install_integrity import verify
        orig_sha256 = verify._sha256_with_retry
        try:
            verify._sha256_with_retry = mock_sha256_err
            # Проверяем full verify с быстрыми retry
            rep = verify_full(root=root, retry_delays=(0.01, 0.01))
            # Не должен объявить файл повреждённым!
            assert rep.ok
            assert not rep.corrupted
        finally:
            verify._sha256_with_retry = orig_sha256


def test_install_integrity_causes_classification():
    """Тест причин: INCOMPLETE_INSTALL, REMOVED_AFTER_INSTALL, MANIFEST_ABSENT."""
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        # Без манифеста
        rep_absent = verify_fast(root=root)
        assert rep_absent.cause == IntegrityCause.MANIFEST_ABSENT

        # Создаем манифест с файлами, но каталогов нет
        entry1 = ManifestEntry(path="bin/nfqws", size=10, sha256="abc", role="critical")
        entry2 = ManifestEntry(path="lua/init.lua", size=10, sha256="def", role="required")
        manifest = InstallManifest(schema=1, version="2.0", channel="rel", entries=(entry1, entry2))
        write_manifest(manifest, root)

        rep_incomplete = verify_fast(root=root)
        assert rep_incomplete.cause == IntegrityCause.INCOMPLETE_INSTALL

        # Каталог bin есть, один файл на месте, другого нет -> REMOVED_AFTER_INSTALL
        (root / "bin").mkdir()
        (root / "lua").mkdir()
        (root / "bin" / "nfqws").write_bytes(b"EXISTING")
        rep_removed = verify_fast(root=root)
        assert rep_removed.cause == IntegrityCause.REMOVED_AFTER_INSTALL
