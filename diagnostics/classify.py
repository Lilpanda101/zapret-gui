"""
diagnostics/classify.py - Модуль классификации блокировок с строгим доказательством (Proof of Verdict).
"""

from dataclasses import dataclass
from enum import Enum
import ipaddress
import re
from typing import Dict, List, Optional, Tuple, Any

from diagnostics.words import get_verdict_words


class BlockVerdictType(str, Enum):
    PASS = "PASS"
    DNS_SPOOFING = "DNS_SPOOFING"
    TCP_RST_INJECTION = "TCP_RST_INJECTION"
    TLS_SNI_DROP = "TLS_SNI_DROP"
    HTTP_BLOCKPAGE = "HTTP_BLOCKPAGE"
    QUIC_BLACKHOLE = "QUIC_BLACKHOLE"
    IP_BLOCK = "IP_BLOCK"
    WHITELIST_RESTRICTION = "WHITELIST_RESTRICTION"
    SITE_ACCESS_RESTRICTED = "SITE_ACCESS_RESTRICTED"
    UNKNOWN = "UNKNOWN"


@dataclass
class EvidenceVerdict:
    target: str
    verdict: BlockVerdictType
    proof: str
    details: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        meta = get_verdict_words(self.verdict.value)
        return {
            "target": self.target,
            "verdict": self.verdict.value,
            "title": meta["title"],
            "severity": meta["severity"],
            "badge_text": meta["badge_text"],
            "badge_class": meta["badge_class"],
            "proof": self.proof,
            "description": meta["description"],
            "recommendation": meta["recommendation"],
            "details": self.details,
        }


# Сигнатуры известных заглушек провайдеров и реестра РКН
BLOCKPAGE_SIGNATURES = [
    r"zapret-info\.rublacklist",
    r"eais\.rkn\.gov\.ru",
    r"blocklist\.rkn\.gov\.ru",
    r"доступ.+ограничен.+в соответствии",
    r"ресурс.+заблокирован",
    r"страница.+недоступна.+требован",
    r"warning\.rt\.ru",
    r"blocked\.mts\.ru",
    r"blackhole\.beeline\.ru",
    r"domru\.ru/block",
    r"zapret\.megafon\.ru",
]

# CGNAT и фиктивные IP-адреса, используемые для DNS-спуфинга
SPOOFED_NETWORKS = [
    ipaddress.ip_network("100.64.0.0/10"),    # RFC 6598 Shared Address Space (CGNAT)
    ipaddress.ip_network("127.0.0.0/8"),       # Loopback
    ipaddress.ip_network("0.0.0.0/8"),         # Current network
    ipaddress.ip_network("192.0.2.0/24"),      # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),   # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),    # TEST-NET-3
]

KNOWN_SPOOFED_IPS = {
    "127.0.0.1",
    "0.0.0.0",
    "10.10.10.10",
    "100.64.0.1",
    "192.168.1.1",
    "8.8.8.8", # when returned for domain that cannot be google dns
}


def is_spoofed_ip(ip_str: str) -> bool:
    """Проверяет, попадает ли IP в фиктивный или CGNAT диапазон."""
    if not ip_str:
        return False
    if ip_str in KNOWN_SPOOFED_IPS:
        return True
    try:
        addr = ipaddress.ip_address(ip_str)
        return any(addr in net for net in SPOOFED_NETWORKS)
    except ValueError:
        return False


def classify_dns_responses(
    target: str,
    responses: Dict[str, Optional[List[str]]],
) -> Optional[EvidenceVerdict]:
    """
    Сравнивает ответы 4 резолверов (например: system_udp, tcp_google, dot_cloudflare, doh_quad9).
    Формирует вердикт DNS_SPOOFING с точным доказательством расхождения или возврата CGNAT IP.
    """
    valid_ips_by_resolver: Dict[str, List[str]] = {}
    for res_name, ips in responses.items():
        if ips:
            valid_ips_by_resolver[res_name] = sorted(list(set(ips)))

    # Проверка на заведомо ложный IP / 100.64.0.0/10
    for res_name, ips in valid_ips_by_resolver.items():
        for ip in ips:
            if is_spoofed_ip(ip):
                return EvidenceVerdict(
                    target=target,
                    verdict=BlockVerdictType.DNS_SPOOFING,
                    proof=f"Резолвер {res_name} вернул заведомо фиктивный/CGNAT адрес: {ip}",
                    details={"resolver": res_name, "spoofed_ip": ip, "all_responses": responses},
                )

    # Проверка на расхождение системного/UDP DNS с шифрованными DoT/DoH
    secure_ips = set()
    for s_name in ("dot_cloudflare", "doh_quad9", "doh_google", "secure_dot"):
        if s_name in valid_ips_by_resolver:
            secure_ips.update(valid_ips_by_resolver[s_name])

    plain_ips = set(valid_ips_by_resolver.get("system_udp", []))
    if secure_ips and plain_ips:
        # Если ни один IP из системного DNS не пересекается с защищенным DNS
        if not plain_ips.intersection(secure_ips):
            return EvidenceVerdict(
                target=target,
                verdict=BlockVerdictType.DNS_SPOOFING,
                proof=(
                    f"Системный DNS ответил {sorted(list(plain_ips))}, тогда как защищенный DoT/DoH ответил {sorted(list(secure_ips))}"
                ),
                details={"system_ips": list(plain_ips), "secure_ips": list(secure_ips)},
            )

    return None


def classify_http_response(
    target: str,
    status_code: int,
    headers: Dict[str, str],
    body_text: str,
) -> Optional[EvidenceVerdict]:
    """
    Анализирует HTTP ответ на предмет заглушек оператора, 451, редиректов или ограничения доступа сайтом.
    """
    lower_body = (body_text or "").lower()
    headers_lower = {k.lower(): v for k, v in (headers or {}).items()}
    location = headers_lower.get("location", "")

    # 1. 403 / 429 / Cloudflare Captcha -> Сайт закрыт владельцем, не блокировка ТСПУ
    if status_code in (403, 429) or "challenge-platform" in lower_body or "cf-mitigated" in headers_lower:
        return EvidenceVerdict(
            target=target,
            verdict=BlockVerdictType.SITE_ACCESS_RESTRICTED,
            proof=f"HTTP {status_code}: сайт самостоятельно ограничил доступ (капча/WAF/лимит), цензура ТСПУ отсутствует",
            details={"status_code": status_code, "headers": headers},
        )

    # 2. HTTP 451 Unavailable For Legal Reasons
    if status_code == 451:
        return EvidenceVerdict(
            target=target,
            verdict=BlockVerdictType.HTTP_BLOCKPAGE,
            proof="HTTP 451: сервер вернул официальный статус недоступности по юридическим требованиям",
            details={"status_code": 451, "location": location},
        )

    # 3. Редирект на заглушку
    if location:
        for pattern in BLOCKPAGE_SIGNATURES:
            if re.search(pattern, location, re.IGNORECASE):
                return EvidenceVerdict(
                    target=target,
                    verdict=BlockVerdictType.HTTP_BLOCKPAGE,
                    proof=f"HTTP {status_code} редирект на заглушку оператора: Location={location}",
                    details={"status_code": status_code, "location": location},
                )

    # 4. Поиск сигнатур в теле ответа
    for pattern in BLOCKPAGE_SIGNATURES:
        match = re.search(pattern, lower_body)
        if match:
            snippet = lower_body[max(0, match.start() - 20) : min(len(lower_body), match.end() + 20)].strip()
            return EvidenceVerdict(
                target=target,
                verdict=BlockVerdictType.HTTP_BLOCKPAGE,
                proof=f"Обнаружена сигнатура заглушки оператора в тексте: «{snippet}»",
                details={"pattern": pattern, "snippet": snippet},
            )

    return None


def classify_whitelist_state(
    ru_services_ok: bool,
    foreign_services_ok: bool,
    target: str,
) -> Optional[EvidenceVerdict]:
    """
    Выявляет режим белых списков: национальные сервисы открываются, а внешние полностью недоступны.
    """
    if ru_services_ok and not foreign_services_ok:
        return EvidenceVerdict(
            target=target,
            verdict=BlockVerdictType.WHITELIST_RESTRICTION,
            proof="Связь с российскими сервисами (Яндекс/VK) в норме, но зарубежные хосты изолированы",
            details={"ru_accessible": ru_services_ok, "foreign_accessible": foreign_services_ok},
        )
    return None


def classify_network_drop(
    target: str,
    tcp_connected: bool,
    tls_connected: bool,
    sni_drop: bool,
    rst_received: bool,
    ip_ping_ok: Optional[bool] = None,
) -> EvidenceVerdict:
    """
    Классифицирует сбросы на транспортном и сессионном уровнях: TLS SNI drop, TCP RST или блокировка IP.
    """
    if sni_drop:
        return EvidenceVerdict(
            target=target,
            verdict=BlockVerdictType.TLS_SNI_DROP,
            proof="TCP-соединение установлено, но соединение сброшено сразу после отправки TLS ClientHello со SNI",
            details={"tcp_connected": tcp_connected, "sni_drop": sni_drop},
        )

    if rst_received:
        return EvidenceVerdict(
            target=target,
            verdict=BlockVerdictType.TCP_RST_INJECTION,
            proof="При установлении TCP соединения получен принудительный флаг RST от ТСПУ/провайдера",
            details={"rst_received": True},
        )

    if not tcp_connected:
        if ip_ping_ok is False:
            return EvidenceVerdict(
                target=target,
                verdict=BlockVerdictType.IP_BLOCK,
                proof="TCP 443 не отвечает и ICMP пинг отсутствует: полная блокировка маршрутизации к IP-адресу",
                details={"tcp_connected": False, "icmp_ping": False},
            )
        return EvidenceVerdict(
            target=target,
            verdict=BlockVerdictType.IP_BLOCK,
            proof="Таймаут подключения TCP на порт 443: трафик к IP-адресу блокируется или фильтруется",
            details={"tcp_connected": False},
        )

    if tcp_connected and tls_connected:
        return EvidenceVerdict(
            target=target,
            verdict=BlockVerdictType.PASS,
            proof="TCP соединение и TLS рукопожатие успешно завершены без вмешательства фильтров",
            details={"tcp_connected": True, "tls_connected": True},
        )

    return EvidenceVerdict(
        target=target,
        verdict=BlockVerdictType.UNKNOWN,
        proof="Соединение ведёт себя нестандартно: детальная причина не определена",
        details={},
    )
