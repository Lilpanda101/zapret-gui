#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DNS Providers Catalog, RTT Probing, and DoH/DoT Resolution with Graceful Fallback.
Designed for Zapret GUI Linux.
"""

from __future__ import annotations

import concurrent.futures
import ipaddress
import json
import logging
import socket
import ssl
import struct
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger("zapret_gui.dns_providers")


class DNSResolutionError(Exception):
    """Raised when DNS resolution fails across attempted providers."""
    pass


@dataclass(frozen=True)
class DNSProvider:
    """DNS Provider specification for DoH and DoT."""
    id: str
    name: str
    description: str
    doh_url: str
    dot_host: str
    dot_ips: Tuple[str, ...]
    dot_port: int = 853
    badge: str = ""
    is_encrypted: bool = True

    def matches(self, query: str) -> bool:
        """Case-insensitive search by id, name, or dot_host."""
        q = query.strip().lower()
        return (
            q == self.id.lower()
            or q in self.name.lower()
            or q in self.dot_host.lower()
        )


# Comprehensive catalog of popular and secure DoH/DoT providers
DNS_CATALOG: Dict[str, DNSProvider] = {
    "cloudflare": DNSProvider(
        id="cloudflare",
        name="Cloudflare DNS",
        description="Быстрый и защищенный DNS от Cloudflare (1.1.1.1) с поддержкой DoH/DoT.",
        doh_url="https://cloudflare-dns.com/dns-query",
        dot_host="cloudflare-dns.com",
        dot_ips=("1.1.1.1", "1.0.0.1", "2606:4700:4700::1111", "2606:4700:4700::1001"),
        dot_port=853,
        badge="Быстрый",
        is_encrypted=True,
    ),
    "google": DNSProvider(
        id="google",
        name="Google Public DNS",
        description="Глобальная сеть DNS-серверов Google (8.8.8.8) с поддержкой DoH и DoT.",
        doh_url="https://dns.google/dns-query",
        dot_host="dns.google",
        dot_ips=("8.8.8.8", "8.8.4.4", "2001:4860:4860::8888", "2001:4860:4860::8844"),
        dot_port=853,
        badge="Универсальный",
        is_encrypted=True,
    ),
    "quad9": DNSProvider(
        id="quad9",
        name="Quad9",
        description="Швейцарский сервис (9.9.9.9) с защитой приватности и блокировкой вредоносных сайтов.",
        doh_url="https://dns.quad9.net/dns-query",
        dot_host="dns.quad9.net",
        dot_ips=("9.9.9.9", "149.112.112.112", "2620:fe::fe", "2620:fe::9"),
        dot_port=853,
        badge="Безопасность",
        is_encrypted=True,
    ),
    "adguard": DNSProvider(
        id="adguard",
        name="AdGuard DNS",
        description="Резолвер AdGuard с защитой от трекеров, аналитики и рекламных сетей.",
        doh_url="https://dns.adguard-dns.com/dns-query",
        dot_host="dns.adguard-dns.com",
        dot_ips=("94.140.14.14", "94.140.15.15", "2a10:50c0::ad1:ff", "2a10:50c0::ad2:ff"),
        dot_port=853,
        badge="Блокировка рекламы",
        is_encrypted=True,
    ),
    "mullvad": DNSProvider(
        id="mullvad",
        name="Mullvad DNS",
        description="Строгая приватность без логирования от создателей Mullvad VPN.",
        doh_url="https://dns.mullvad.net/dns-query",
        dot_host="dns.mullvad.net",
        dot_ips=("194.242.2.2", "194.242.2.3", "2a07:e340::2"),
        dot_port=853,
        badge="Приватность",
        is_encrypted=True,
    ),
    "comss": DNSProvider(
        id="comss",
        name="Comss.one DNS",
        description="Быстрый резолвер Comss.one с оптимизацией маршрутов и защитой от блокировок в РФ.",
        doh_url="https://dns.comss.one/dns-query",
        dot_host="dns.comss.one",
        dot_ips=("92.223.109.31", "92.38.169.115"),
        dot_port=853,
        badge="РФ Оптимизация",
        is_encrypted=True,
    ),
    "nextdns": DNSProvider(
        id="nextdns",
        name="NextDNS",
        description="Современный настраиваемый облачный DNS-файрвол с DoH и DoT.",
        doh_url="https://dns.nextdns.io/dns-query",
        dot_host="dns.nextdns.io",
        dot_ips=("45.90.28.0", "45.90.30.0", "2a07:a8c0::0", "2a07:a8c1::0"),
        dot_port=853,
        badge="Кастомизация",
        is_encrypted=True,
    ),
    # Дополнительные провайдеры для совместимости со старыми пресетами
    "dns_ai": DNSProvider(
        id="dns_ai",
        name="DNS-AI (Нейросети DoT)",
        description="Специализированный DoT резолвер для доступа к AI-сервисам.",
        doh_url="https://dns-ai.ru/dns-query",
        dot_host="dns-ai.ru",
        dot_ips=("194.87.196.13", "45.151.102.219"),
        dot_port=853,
        badge="Разблокировка ИИ",
        is_encrypted=True,
    ),
    "geohide": DNSProvider(
        id="geohide",
        name="Geohide DNS",
        description="Резолвер для обхода гео-ограничений популярных зарубежных ресурсов.",
        doh_url="https://geohide.ru/dns-query",
        dot_host="geohide.ru",
        dot_ips=("37.230.192.51",),
        dot_port=853,
        badge="Геоблокировки",
        is_encrypted=True,
    ),
    "system": DNSProvider(
        id="system",
        name="Системный DNS",
        description="Использовать стандартный системный резолвер (DHCP / NetworkManager).",
        doh_url="",
        dot_host="",
        dot_ips=(),
        dot_port=0,
        badge="По умолчанию",
        is_encrypted=False,
    ),
}


def get_provider(provider_id: Union[str, DNSProvider]) -> DNSProvider:
    """
    Returns DNSProvider instance by ID or object.
    Raises KeyError if provider is unknown.
    """
    if isinstance(provider_id, DNSProvider):
        return provider_id
    clean_id = provider_id.strip().lower()
    if clean_id in DNS_CATALOG:
        return DNS_CATALOG[clean_id]
    raise KeyError(f"Unknown DNS provider: {provider_id}")


def list_providers(include_system: bool = True) -> List[DNSProvider]:
    """Returns list of all registered DNS providers."""
    if include_system:
        return list(DNS_CATALOG.values())
    return [p for p in DNS_CATALOG.values() if p.is_encrypted]


# --- Minimal Pure-Python DNS Wire Protocol Helpers ---

TYPE_A = 1
TYPE_AAAA = 28
CLASS_IN = 1


def _encode_dns_name(domain: str) -> bytes:
    """Encodes a domain name into DNS wire format labels."""
    parts = domain.rstrip(".").split(".")
    out = bytearray()
    for part in parts:
        encoded = part.encode("idna")
        if len(encoded) > 63:
            raise ValueError(f"Label too long: {part}")
        out.append(len(encoded))
        out.extend(encoded)
    out.append(0)
    return bytes(out)


def _decode_dns_name(wire: bytes, offset: int) -> Tuple[str, int]:
    """Decodes a domain name from DNS wire bytes, handling compression pointers."""
    labels: List[str] = []
    curr = offset
    visited_offsets = set()

    jumped = False
    next_offset = offset

    while curr < len(wire):
        length = wire[curr]
        if length == 0:
            if not jumped:
                next_offset = curr + 1
            break

        # Check for DNS pointer compression (0b11xxxxxx)
        if (length & 0xC0) == 0xC0:
            if curr + 1 >= len(wire):
                break
            ptr = ((length & 0x3F) << 8) | wire[curr + 1]
            if not jumped:
                next_offset = curr + 2
                jumped = True
            if ptr in visited_offsets or ptr >= len(wire):
                break
            visited_offsets.add(ptr)
            curr = ptr
            continue

        curr += 1
        label = wire[curr : curr + length].decode("ascii", errors="replace")
        labels.append(label)
        curr += length

    if not jumped:
        next_offset = max(next_offset, curr + 1)

    return ".".join(labels), next_offset


def build_dns_query(domain: str, record_type: str = "A", query_id: int = 0x1234) -> bytes:
    """
    Constructs an RFC 1035 compliant DNS query wire packet.
    """
    rtype = TYPE_AAAA if record_type.upper() == "AAAA" else TYPE_A
    header = struct.pack("!HHHHHH", query_id, 0x0100, 1, 0, 0, 0)
    qname = _encode_dns_name(domain)
    question = qname + struct.pack("!HH", rtype, CLASS_IN)
    return header + question


def parse_dns_response(wire: bytes) -> List[str]:
    """
    Parses an RFC 1035 DNS response wire packet and extracts IP addresses.
    """
    if len(wire) < 12:
        return []

    query_id, flags, qdcount, ancount, _, _ = struct.unpack("!HHHHHH", wire[:12])
    # Check RCODE (lowest 4 bits of flags)
    rcode = flags & 0x000F
    if rcode != 0:
        logger.debug("DNS response returned non-zero rcode: %d", rcode)
        return []

    offset = 12

    # Skip Questions
    for _ in range(qdcount):
        _, offset = _decode_dns_name(wire, offset)
        offset += 4  # Skip QTYPE and QCLASS

    answers: List[str] = []

    # Parse Answers
    for _ in range(ancount):
        if offset >= len(wire):
            break
        _, offset = _decode_dns_name(wire, offset)
        if offset + 10 > len(wire):
            break
        atype, aclass, ttl, rdlength = struct.unpack("!HHIH", wire[offset : offset + 10])
        offset += 10
        rdata = wire[offset : offset + rdlength]
        offset += rdlength

        if atype == TYPE_A and rdlength == 4:
            ip = socket.inet_ntop(socket.AF_INET, rdata)
            answers.append(ip)
        elif atype == TYPE_AAAA and rdlength == 16:
            ip = socket.inet_ntop(socket.AF_INET6, rdata)
            answers.append(ip)

    return answers


# --- Resolution Implementations ---

def resolve_doh(
    domain: str,
    provider: Union[str, DNSProvider],
    record_type: str = "A",
    timeout: float = 3.0,
) -> List[str]:
    """
    Resolves domain via DNS-over-HTTPS (DoH).
    Supports RFC 8484 wire message and JSON DNS fallback.
    """
    prov = get_provider(provider)
    if not prov.doh_url:
        raise DNSResolutionError(f"Provider '{prov.name}' does not support DoH")

    rtype = record_type.upper()
    query_wire = build_dns_query(domain, rtype)

    # First attempt: RFC 8484 wire format via HTTP POST
    req = urllib.request.Request(
        prov.doh_url,
        data=query_wire,
        headers={
            "Content-Type": "application/dns-message",
            "Accept": "application/dns-message, application/dns-json",
            "User-Agent": "ZapretGUI-DNS/1.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw_body = resp.read()

            if "application/dns-message" in content_type:
                ips = parse_dns_response(raw_body)
                if ips:
                    return ips

            # If response is JSON (some servers respond with JSON even on POST)
            if "json" in content_type or raw_body.strip().startswith(b"{"):
                try:
                    data = json.loads(raw_body.decode("utf-8"))
                    ips = []
                    for ans in data.get("Answer", []):
                        if (rtype == "A" and ans.get("type") == 1) or (rtype == "AAAA" and ans.get("type") == 28):
                            ips.append(ans.get("data", ""))
                    if ips:
                        return ips
                except Exception:
                    pass
    except Exception as exc:
        logger.debug("DoH POST failed for %s (%s): %s", prov.name, domain, exc)

    # Fallback attempt: DoH JSON GET format (?name=...&type=...)
    try:
        params = urllib.parse.urlencode({"name": domain, "type": rtype})
        get_url = f"{prov.doh_url}?{params}"
        req_get = urllib.request.Request(
            get_url,
            headers={
                "Accept": "application/dns-json",
                "User-Agent": "ZapretGUI-DNS/1.0",
            },
        )
        with urllib.request.urlopen(req_get, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ips = []
            for ans in data.get("Answer", []):
                val = ans.get("data", "")
                if val:
                    # Filter out CNAME values when querying A/AAAA
                    try:
                        ipaddress.ip_address(val)
                        ips.append(val)
                    except ValueError:
                        continue
            if ips:
                return ips
    except Exception as exc:
        logger.debug("DoH GET fallback failed for %s (%s): %s", prov.name, domain, exc)

    raise DNSResolutionError(f"Failed to resolve '{domain}' via DoH using provider '{prov.name}'")


def resolve_dot(
    domain: str,
    provider: Union[str, DNSProvider],
    record_type: str = "A",
    timeout: float = 3.0,
) -> List[str]:
    """
    Resolves domain via DNS-over-TLS (DoT, RFC 7858).
    Connects to TLS port 853 with SNI validation.
    """
    prov = get_provider(provider)
    if not prov.dot_host or not prov.dot_ips:
        raise DNSResolutionError(f"Provider '{prov.name}' does not support DoT")

    rtype = record_type.upper()
    query_wire = build_dns_query(domain, rtype)
    # DoT prefixes message with 2-byte length
    prefixed_query = struct.pack("!H", len(query_wire)) + query_wire

    ctx = ssl.create_default_context()

    last_error: Optional[Exception] = None
    # Try available IPs for provider
    for ip in prov.dot_ips:
        # Check if IPv6 is supported on host
        family = socket.AF_INET6 if ":" in ip else socket.AF_INET
        try:
            with socket.socket(family, socket.SOCK_STREAM) as raw_sock:
                raw_sock.settimeout(timeout)
                with ctx.wrap_socket(raw_sock, server_hostname=prov.dot_host) as tls_sock:
                    tls_sock.connect((ip, prov.dot_port))
                    tls_sock.sendall(prefixed_query)

                    # Read 2-byte length prefix
                    len_bytes = tls_sock.recv(2)
                    if len(len_bytes) < 2:
                        continue
                    msg_len = struct.unpack("!H", len_bytes)[0]

                    # Read response payload
                    chunks: List[bytes] = []
                    bytes_read = 0
                    while bytes_read < msg_len:
                        chunk = tls_sock.recv(min(4096, msg_len - bytes_read))
                        if not chunk:
                            break
                        chunks.append(chunk)
                        bytes_read += len(chunk)

                    resp_wire = b"".join(chunks)
                    ips = parse_dns_response(resp_wire)
                    if ips:
                        return ips
        except Exception as exc:
            last_error = exc
            logger.debug("DoT attempt to %s (%s) failed: %s", ip, prov.name, exc)
            continue

    raise DNSResolutionError(
        f"Failed to resolve '{domain}' via DoT using provider '{prov.name}': {last_error}"
    )


def resolve_system(domain: str, record_type: str = "A") -> List[str]:
    """Resolves domain using local system resolver."""
    family = socket.AF_INET6 if record_type.upper() == "AAAA" else socket.AF_INET
    try:
        addrinfo = socket.getaddrinfo(domain, None, family=family, type=socket.SOCK_STREAM)
        results: List[str] = []
        for item in addrinfo:
            ip = item[4][0]
            if ip not in results:
                results.append(ip)
        if results:
            return results
    except Exception as exc:
        raise DNSResolutionError(f"System DNS resolution failed for '{domain}': {exc}") from exc
    raise DNSResolutionError(f"System DNS returned no addresses for '{domain}'")


def resolve_with_fallback(
    domain: str,
    providers: Optional[Sequence[Union[str, DNSProvider]]] = None,
    record_type: str = "A",
    timeout: float = 2.5,
    prefer_method: str = "doh",
) -> Tuple[str, List[str]]:
    """
    Resolves domain by iterating through providers with graceful fallback.
    Returns (successful_provider_id, list_of_ips).
    If all encrypted providers fail, attempts graceful fallback to system resolver.
    """
    if providers is None:
        # Default chain: Cloudflare -> Google -> Quad9 -> AdGuard
        provider_chain = ["cloudflare", "google", "quad9", "adguard"]
    else:
        provider_chain = list(providers)

    attempted_errors: List[str] = []

    for item in provider_chain:
        try:
            prov = get_provider(item)
            if not prov.is_encrypted:
                # Direct system resolver
                ips = resolve_system(domain, record_type=record_type)
                return prov.id, ips

            ips: List[str] = []
            if prefer_method == "dot":
                try:
                    ips = resolve_dot(domain, prov, record_type=record_type, timeout=timeout)
                except Exception:
                    ips = resolve_doh(domain, prov, record_type=record_type, timeout=timeout)
            else:
                try:
                    ips = resolve_doh(domain, prov, record_type=record_type, timeout=timeout)
                except Exception:
                    ips = resolve_dot(domain, prov, record_type=record_type, timeout=timeout)

            if ips:
                return prov.id, ips
        except Exception as exc:
            prov_id = getattr(item, "id", str(item))
            attempted_errors.append(f"{prov_id}: {exc}")
            logger.debug("Provider %s failed, falling back to next...", prov_id)

    # Ultimate fallback: system DNS resolver
    try:
        system_ips = resolve_system(domain, record_type=record_type)
        return "system", system_ips
    except Exception as exc:
        attempted_errors.append(f"system: {exc}")

    raise DNSResolutionError(
        f"All DNS providers in fallback chain failed for '{domain}'. Errors: {'; '.join(attempted_errors)}"
    )


# --- RTT Latency Probing ---

def probe_rtt(
    provider: Union[str, DNSProvider],
    timeout: float = 2.0,
    domain_probe: str = "cloudflare.com",
) -> Optional[float]:
    """
    Measures latency (RTT in ms) to the DNS provider.
    Tries TLS connection to DoT endpoint or lightweight query.
    Returns latency in milliseconds, or None if provider is unreachable.
    """
    prov = get_provider(provider)
    if not prov.is_encrypted:
        # Measure system ping/lookup time
        t0 = time.perf_counter()
        try:
            socket.getaddrinfo(domain_probe, None)
            return round((time.perf_counter() - t0) * 1000.0, 1)
        except Exception:
            return None

    # Probe 1: TCP/TLS handshake latency to DoT port
    if prov.dot_ips:
        ctx = ssl.create_default_context()
        for ip in prov.dot_ips:
            family = socket.AF_INET6 if ":" in ip else socket.AF_INET
            t0 = time.perf_counter()
            try:
                with socket.socket(family, socket.SOCK_STREAM) as sock:
                    sock.settimeout(timeout)
                    with ctx.wrap_socket(sock, server_hostname=prov.dot_host) as tls_sock:
                        tls_sock.connect((ip, prov.dot_port))
                        rtt_ms = (time.perf_counter() - t0) * 1000.0
                        return round(rtt_ms, 1)
            except Exception:
                continue

    # Probe 2: DoH HEAD / minimal request latency
    if prov.doh_url:
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(
                prov.doh_url,
                headers={"User-Agent": "ZapretGUI-Probe/1.0"},
                method="HEAD",
            )
            with urllib.request.urlopen(req, timeout=timeout):
                return round((time.perf_counter() - t0) * 1000.0, 1)
        except urllib.error.HTTPError:
            # Server answered (e.g. 400/405), which still indicates reachable host
            return round((time.perf_counter() - t0) * 1000.0, 1)
        except Exception:
            pass

    return None


def probe_all_rtt(
    providers: Optional[Sequence[Union[str, DNSProvider]]] = None,
    timeout: float = 2.0,
    max_workers: int = 6,
) -> Dict[str, Optional[float]]:
    """
    Concurrently measures latency for given providers (or all in catalog).
    Returns mapping {provider_id: rtt_ms or None}.
    """
    targets = list(providers) if providers is not None else list(DNS_CATALOG.keys())
    results: Dict[str, Optional[float]] = {}

    def _probe_worker(target: Union[str, DNSProvider]) -> Tuple[str, Optional[float]]:
        prov_id = target.id if isinstance(target, DNSProvider) else str(target)
        try:
            return prov_id, probe_rtt(target, timeout=timeout)
        except Exception:
            return prov_id, None

    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {executor.submit(_probe_worker, t): t for t in targets}
        for future in concurrent.futures.as_completed(future_map):
            pid, rtt = future.result()
            results[pid] = rtt

    return results
