"""
diagnostics/verdict.py - Чистые функции судейства (judge) над собранными фактами.
Реализует:
- judge_dns: проверка подмены DNS с обязательной проверкой сертификата на IP из системного DNS (SAN, issuer, срок).
  Anycast и CDN с разными IP и подлинным сертификатом - НЕ подмена!
  Отдельно исходы из 100.64.0.0/10 и заведомо ложные адреса.
- judge_service: расширенные исходы («открывается», «открывается через раз», «грузится не до конца»,
  «нет адреса», «основной открывается, но сломаны вторичные», «сайт закрыт сам с 403, 429 или капчей»).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import ipaddress
from typing import Any, Dict, List, Optional, Tuple

from diagnostics.words import get_verdict_words


class DnsState(str, Enum):
    OK = "ok"
    SPOOFED = "spoofed"
    NO_ADDRESS = "no_address"
    LOCAL = "local"


@dataclass(frozen=True)
class DnsJudgement:
    state: DnsState
    reason: str
    proof: str


class ServiceReachState(str, Enum):
    OK = "ok"
    UNSTABLE = "unstable"
    CUT_WINDOW = "cut_window"
    SECONDARY_BROKEN = "secondary_broken"
    SITE_RESTRICTED = "site_restricted"
    BLOCKED = "blocked"
    NO_ADDRESS = "no_address"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class ServiceJudgement:
    state: ServiceReachState
    headline: str
    proof: str
    recommendation: str
    badge_text: str
    badge_class: str


# CGNAT 100.64.0.0/10 и заведомо фиктивные IP
CGNAT_NETWORK = ipaddress.ip_network("100.64.0.0/10")
SPOOFED_NETWORKS = (
    CGNAT_NETWORK,
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("192.0.2.0/24"),
    ipaddress.ip_network("198.51.100.0/24"),
    ipaddress.ip_network("203.0.113.0/24"),
)


def is_clearly_bogus_ip(ip_str: str) -> bool:
    if not ip_str:
        return False
    if ip_str in ("127.0.0.1", "0.0.0.0", "10.10.10.10", "100.64.0.1"):
        return True
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in SPOOFED_NETWORKS)
    except ValueError:
        return False


def judge_dns(
    *,
    target: str,
    system_ips: Tuple[str, ...],
    reference_ips: Tuple[str, ...],
    cert_valid: Optional[bool] = None,
    cert_san_match: Optional[bool] = None,
    cert_issuer: str = "",
) -> DnsJudgement:
    """
    Чистое судейство честности DNS.
    ЗАКОН: Запрещено делать вывод о подмене только по несовпадению IP!
    Anycast/CDN с разными IP и подлинным сертификатом - НЕ подмена!
    Решает сертификат на адресе из системного DNS.
    """
    if not system_ips:
        return DnsJudgement(
            state=DnsState.NO_ADDRESS,
            reason="DNS компьютеру не называет адрес хоста (NXDOMAIN / пустой ответ)",
            proof="Системный DNS не вернул ни одного IP-адреса",
        )

    # 1. Заведомо ложные IP / CGNAT (100.64.0.0/10)
    for ip in system_ips:
        if is_clearly_bogus_ip(ip):
            return DnsJudgement(
                state=DnsState.SPOOFED,
                reason="Системный DNS вернул фиктивный IP-адрес или адрес из диапазона CGNAT",
                proof=f"Системный DNS вернул адрес {ip}, входящий в фиктивный/CGNAT диапазон",
            )

    # 2. Если IP совпадают с эталонным DoH/DoT
    if reference_ips and set(system_ips).intersection(set(reference_ips)):
        return DnsJudgement(
            state=DnsState.OK,
            reason="Адрес из системного DNS подтверждён эталонным DoT/DoH резолвером",
            proof=f"IP {system_ips[0]} совпадает с эталонным ответом DoH",
        )

    # 3. Разные IP (Anycast/CDN или подмена). Проверяем сертификат на системном IP!
    if cert_valid is True and cert_san_match is True:
        # Сервер предъявил подлинный сертификат сайта: это CDN или Anycast, НЕ подмена!
        return DnsJudgement(
            state=DnsState.OK,
            reason="Адреса DNS отличаются от эталона, но сервер предъявил подлинный сертификат (CDN / Anycast)",
            proof=f"Сертификат сайта на системном адресе {system_ips[0]} валиден (issuer: {cert_issuer or 'валидный'})",
        )

    if cert_valid is False or cert_san_match is False:
        # Сертификат чужой или невалидный -> настоящая подмена DNS!
        return DnsJudgement(
            state=DnsState.SPOOFED,
            reason="Подмена DNS: по выданному адресу сервер не смог предъявить подлинный сертификат целевого домена",
            proof=f"Системный IP {system_ips[0]} не имеет валидного SAN для {target} (сертификат: {cert_issuer or 'недостоверный'})",
        )

    # Если сертификат не проверялся, но IP просто не совпали
    return DnsJudgement(
        state=DnsState.OK,
        reason="Ответ системного DNS отличается от эталонного DoH (распределение CDN / Anycast)",
        proof=f"Системный IP: {system_ips[0]}, эталонный DoH: {reference_ips[0] if reference_ips else '-'}",
    )


def judge_service(
    *,
    target: str,
    main_ok: bool,
    main_unstable: bool = False,
    main_body_cut: bool = False,
    main_no_address: bool = False,
    http_status: Optional[int] = None,
    secondary_broken_parts: Tuple[str, ...] = (),
    proof_hint: str = "",
) -> ServiceJudgement:
    """
    Расширенные исходы вердикта:
    - Открывается
    - Открывается через раз
    - Грузится не до конца
    - Нет адреса
    - Основной открывается, но сломаны вторичные
    - Сайт закрыт сам с 403, 429 или капчей
    """
    # 1. 403 / 429 / Капча
    if http_status in (403, 429):
        meta = get_verdict_words("SITE_ACCESS_RESTRICTED")
        return ServiceJudgement(
            state=ServiceReachState.SITE_RESTRICTED,
            headline=f"{target}: {meta['title']}",
            proof=f"HTTP статус {http_status}: целевой ресурс самостоятельно ограничил доступ клиенту (WAF/лимит)",
            recommendation=meta["recommendation"],
            badge_text=meta["badge_text"],
            badge_class=meta["badge_class"],
        )

    # 2. Нет адреса (DNS)
    if main_no_address:
        meta = get_verdict_words("DNS_NO_ADDRESS")
        return ServiceJudgement(
            state=ServiceReachState.NO_ADDRESS,
            headline=f"{target} не открывается: не удалось узнать адрес сервера",
            proof="Домен не разрешается в IP-адрес через системный DNS",
            recommendation=meta["recommendation"],
            badge_text=meta["badge_text"],
            badge_class=meta["badge_class"],
        )

    # 3. Грузится не до конца (cut_window 12–36 КБ)
    if main_body_cut:
        meta = get_verdict_words("CUT_WINDOW")
        return ServiceJudgement(
            state=ServiceReachState.CUT_WINDOW,
            headline=f"{target} грузится не до конца (обрыв потока)",
            proof=proof_hint or "Соединение установлено, но поток сброшен при передаче первых килобайт данных (обрыв ТСПУ)",
            recommendation=meta["recommendation"],
            badge_text=meta["badge_text"],
            badge_class=meta["badge_class"],
        )

    # 4. Открывается через раз (unstable)
    if main_unstable:
        meta = get_verdict_words("UNSTABLE")
        return ServiceJudgement(
            state=ServiceReachState.UNSTABLE,
            headline=f"{target} открывается через раз",
            proof=proof_hint or "Часть повторных запросов завершается таймаутом или сбросом: нестабильная фильтрация",
            recommendation=meta["recommendation"],
            badge_text=meta["badge_text"],
            badge_class=meta["badge_class"],
        )

    # 5. Основной открывается, но сломаны вторичные
    if main_ok and secondary_broken_parts:
        parts_str = ", ".join(secondary_broken_parts)
        meta = get_verdict_words("SECONDARY_BROKEN")
        return ServiceJudgement(
            state=ServiceReachState.SECONDARY_BROKEN,
            headline=f"{target} открывается, но не работают: {parts_str}",
            proof=f"Главная страница доступна, но вспомогательные узлы ({parts_str}) сбрасываются",
            recommendation=meta["recommendation"],
            badge_text=meta["badge_text"],
            badge_class=meta["badge_class"],
        )

    # 6. Открывается
    if main_ok:
        meta = get_verdict_words("PASS")
        return ServiceJudgement(
            state=ServiceReachState.OK,
            headline=f"{target} открывается",
            proof=proof_hint or "Сетевое соединение, TLS рукопожатие и получение данных выполнены штатно",
            recommendation=meta["recommendation"],
            badge_text=meta["badge_text"],
            badge_class=meta["badge_class"],
        )

    # 7. Заблокирован
    meta = get_verdict_words("UNKNOWN")
    return ServiceJudgement(
        state=ServiceReachState.BLOCKED,
        headline=f"{target} не открывается: блокировка доступа",
        proof=proof_hint or "Соединение с хостом сбрасывается или не устанавливается",
        recommendation=meta["recommendation"],
        badge_text="Не открывается (FAIL)",
        badge_class="badge-bad",
    )
