#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DPI Classifier & Diagnostics Engine for Zapret GUI Linux.

Определяет точные методы блокировки цензоров / ТСПУ (DPI) провайдеров:
- DNS_SPOOFING: подмена IP резолвером или провайдером на IP заглушки/bogon
- TCP_RST_INJECTION: активный сброс соединения инжектом TCP RST пакета
- TLS_SNI_DROP: молчаливый сброс пакетов (blackhole) после ClientHello с заблокированным SNI
- HTTP_BLOCKPAGE: HTTP редирект (302/451) или HTML-заглушка РКН / провайдера
- QUIC_BLACKHOLE / UDP_DROP: блокировка UDP/443 рукопожатий QUIC
- PASS / OK: цензура не обнаружена, трафик проходит чисто
"""
from __future__ import annotations

import concurrent.futures
from dataclasses import asdict, dataclass, field
from enum import Enum
import ipaddress
import json
import os
import re
import socket
import struct
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple, Union
import urllib.error
import urllib.request


class BlockType(str, Enum):
    """Типы блокировок и цензуры."""
    PASS = "PASS"
    DNS_SPOOFING = "DNS_SPOOFING"
    TCP_RST_INJECTION = "TCP_RST_INJECTION"
    TLS_SNI_DROP = "TLS_SNI_DROP"
    HTTP_BLOCKPAGE = "HTTP_BLOCKPAGE"
    QUIC_BLACKHOLE = "QUIC_BLACKHOLE"
    TIMEOUT = "TIMEOUT"
    ERROR = "ERROR"

    # Aliases
    OK = "PASS"
    UDP_DROP = "QUIC_BLACKHOLE"


# Известные IP-адреса страниц-заглушек РКН и провайдеров
KNOWN_BLOCKPAGE_IPS = {
    "195.82.146.120",   # eais.rkn.gov.ru / Роскомнадзор
    "195.82.146.121",
    "82.192.88.10",
    "95.173.136.70",    # Ростелеком
    "95.173.136.71",
    "95.173.136.72",
    "109.105.134.195",
    "178.248.232.22",
    "212.1.254.100",
}

# Регулярные выражения для распознавания доменов заглушек
BLOCKPAGE_DOMAINS_RE = re.compile(
    r"(?:warning|blocked|block|zapret|blackhole)\.(?:rt|mts|mgts|beeline|megafon|ertelecom|dom|tele2)\.ru|"
    r"eais\.rkn\.gov\.ru|"
    r"zapret-info\.rublacklist\.net",
    re.IGNORECASE,
)

# Текстовые паттерны заглушек в теле ответа
BLOCKPAGE_PATTERNS = [
    re.compile(r"единый\s+реестр", re.IGNORECASE),
    re.compile(r"доступ\s+(?:к\s+ресурсу\s+)?ограничен", re.IGNORECASE),
    re.compile(r"страница\s+(?:временно\s+)?заблокирована", re.IGNORECASE),
    re.compile(r"заблокирован(?:о)?\s+по\s+решению", re.IGNORECASE),
    re.compile(r"149-фз", re.IGNORECASE),
    re.compile(r"министерств[а-я]*\s+юстиц", re.IGNORECASE),
    re.compile(r"сайт\s+внесен\s+в\s+реестр", re.IGNORECASE),
    re.compile(r"blocked\s+by\s+(?:rkn|court|isp)", re.IGNORECASE),
    re.compile(r"forbidden\s+by\s+judicial\s+decision", re.IGNORECASE),
]


def is_bogon_ip(ip_str: str) -> bool:
    """Проверяет, является ли IP адрес bogon / private / loopback / blackhole адресом."""
    try:
        ip = ipaddress.ip_address(ip_str)
        return (
            ip.is_loopback
            or ip.is_unspecified
            or ip.is_link_local
            or ip.is_private
            or ip.is_reserved
        )
    except ValueError:
        return False


def is_known_blockpage_ip(ip_str: str) -> bool:
    """Проверяет, входит ли IP в список известных заглушек РКН/провайдеров."""
    return ip_str in KNOWN_BLOCKPAGE_IPS


def detect_blockpage_content(
    status_code: int,
    headers: Dict[str, str],
    body: str,
) -> Tuple[bool, str]:
    """Анализирует HTTP ответ на наличие признаков страницы-заглушки."""
    if status_code == 451:
        return True, "HTTP Status 451 (Unavailable For Legal Reasons)"

    # Проверка Location в редиректах 301, 302, 303, 307, 308
    location = headers.get("Location") or headers.get("location") or ""
    if location:
        if BLOCKPAGE_DOMAINS_RE.search(location):
            return True, f"HTTP redirect to blockpage domain: {location}"
        for known_ip in KNOWN_BLOCKPAGE_IPS:
            if known_ip in location:
                return True, f"HTTP redirect to blockpage IP: {location}"

    # Проверка текста страницы
    if body:
        for pat in BLOCKPAGE_PATTERNS:
            match = pat.search(body)
            if match:
                return True, f"Blockpage pattern found in HTTP body: '{match.group(0)}'"

    return False, ""


# ---------------------------------------------------------------------------
# TLS Chrome ClientHello Generator & Parser
# ---------------------------------------------------------------------------

def generate_chrome_client_hello(
    hostname: str,
    alpn_protocols: Sequence[str] = ("h2", "http/1.1"),
    grease: bool = True,
    session_id: Optional[bytes] = None,
    client_random: Optional[bytes] = None,
) -> bytes:
    """Генерирует бинарный TLS 1.3/1.2 ClientHello в формате современного Google Chrome.

    Включает:
    - TLS Plaintext record (0x16, 0x03, 0x01)
    - Handshake Type 0x01 (ClientHello)
    - Client Version 0x0303 (TLS 1.2 legacy)
    - 32-байтный random
    - 32-байтный legacy session id
    - Набор шифров Chrome (GREASE + AES GCM + ChaCha20 + ECDHE)
    - Расширения:
      * GREASE (0x2a2a / 0x0a0a)
      * server_name (SNI, 0x0000)
      * supported_groups (0x000a)
      * ec_point_formats (0x000b)
      * signature_algorithms (0x000d)
      * alpn (0x0010)
      * supported_versions (0x002b) с GREASE, TLS 1.3, TLS 1.2
      * key_share (0x0033) с x25519
      * psk_key_exchange_modes (0x002d)
    """
    # 1. Random & Session ID
    random_bytes = client_random if client_random is not None else os.urandom(32)
    sess_id = session_id if session_id is not None else os.urandom(32)

    # 2. Cipher Suites
    cipher_suites = bytearray()
    if grease:
        cipher_suites.extend(b"\x2a\x2a")  # GREASE cipher suite
    cipher_suites.extend(b"\x13\x01")      # TLS_AES_128_GCM_SHA256
    cipher_suites.extend(b"\x13\x02")      # TLS_AES_256_GCM_SHA384
    cipher_suites.extend(b"\x13\x03")      # TLS_CHACHA20_POLY1305_SHA256
    cipher_suites.extend(b"\xc0\x2b")      # ECDHE-ECDSA-AES128-GCM-SHA256
    cipher_suites.extend(b"\xc0\x2f")      # ECDHE-RSA-AES128-GCM-SHA256
    cipher_suites.extend(b"\xc0\x2c")      # ECDHE-ECDSA-AES256-GCM-SHA384
    cipher_suites.extend(b"\xc0\x30")      # ECDHE-RSA-AES256-GCM-SHA384
    cipher_suites.extend(b"\xcc\xa9")      # ECDHE-ECDSA-CHACHA20-POLY1305
    cipher_suites.extend(b"\xcc\xa8")      # ECDHE-RSA-CHACHA20-POLY1305

    # 3. Compression Methods (null compression)
    compression_methods = b"\x01\x00"

    # 4. Extensions
    extensions = bytearray()

    # Extension: GREASE (если включен)
    if grease:
        extensions.extend(struct.pack("!HH", 0x3A3A, 1) + b"\x00")

    # Extension: server_name (SNI, type 0x0000)
    if hostname:
        host_bytes = hostname.encode("idna")
        # Entry: type 0 (host_name), 2 bytes length, hostname
        sni_entry = b"\x00" + struct.pack("!H", len(host_bytes)) + host_bytes
        sni_list = struct.pack("!H", len(sni_entry)) + sni_entry
        extensions.extend(struct.pack("!HH", 0x0000, len(sni_list)) + sni_list)

    # Extension: extended_master_secret (0x0017)
    extensions.extend(struct.pack("!HH", 0x0017, 0))

    # Extension: renegotiation_info (0xff01)
    extensions.extend(struct.pack("!HH", 0xFF01, 1) + b"\x00")

    # Extension: supported_groups (0x000a)
    # GREASE (0x4a4a) + X25519 (0x001d) + secp256r1 (0x0017) + secp384r1 (0x0018)
    groups = bytearray()
    if grease:
        groups.extend(b"\x4a\x4a")
    groups.extend(b"\x00\x1d\x00\x17\x00\x18")
    groups_data = struct.pack("!H", len(groups)) + groups
    extensions.extend(struct.pack("!HH", 0x000A, len(groups_data)) + groups_data)

    # Extension: ec_point_formats (0x000b)
    ec_points = b"\x01\x00"  # uncompressed
    extensions.extend(struct.pack("!HH", 0x000B, len(ec_points)) + ec_points)

    # Extension: session_ticket (0x0023)
    extensions.extend(struct.pack("!HH", 0x0023, 0))

    # Extension: ALPN (0x0010)
    if alpn_protocols:
        alpn_data = bytearray()
        for proto in alpn_protocols:
            proto_bytes = proto.encode("ascii")
            alpn_data.append(len(proto_bytes))
            alpn_data.extend(proto_bytes)
        alpn_ext = struct.pack("!H", len(alpn_data)) + alpn_data
        extensions.extend(struct.pack("!HH", 0x0010, len(alpn_ext)) + alpn_ext)

    # Extension: status_request (OCSP, 0x0005)
    extensions.extend(struct.pack("!HH", 0x0005, 5) + b"\x01\x00\x00\x00\x00")

    # Extension: signature_algorithms (0x000d)
    # ecdsa_secp256r1_sha256 (0x0403), rsa_pss_rsae_sha256 (0x0804), rsa_pkcs1_sha256 (0x0401)
    sig_algs = b"\x04\x03\x08\x04\x04\x01\x05\x03\x08\x05\x05\x01\x08\x06\x06\x01"
    sig_data = struct.pack("!H", len(sig_algs)) + sig_algs
    extensions.extend(struct.pack("!HH", 0x000D, len(sig_data)) + sig_data)

    # Extension: supported_versions (0x002b)
    # GREASE (0x6a6a) + TLS 1.3 (0x0304) + TLS 1.2 (0x0303)
    versions = bytearray()
    if grease:
        versions.extend(b"\x6a\x6a")
    versions.extend(b"\x03\x04\x03\x03")
    versions_data = struct.pack("!B", len(versions)) + versions
    extensions.extend(struct.pack("!HH", 0x002B, len(versions_data)) + versions_data)

    # Extension: key_share (0x0033)
    # x25519 (0x001d) with 32 dummy bytes
    key_exchange = os.urandom(32)
    key_share_entry = b"\x00\x1d" + struct.pack("!H", len(key_exchange)) + key_exchange
    if grease:
        grease_ks = b"\x5a\x5a\x00\x01\x00"
        key_share_client = struct.pack("!H", len(grease_ks) + len(key_share_entry)) + grease_ks + key_share_entry
    else:
        key_share_client = struct.pack("!H", len(key_share_entry)) + key_share_entry
    extensions.extend(struct.pack("!HH", 0x0033, len(key_share_client)) + key_share_client)

    # Extension: psk_key_exchange_modes (0x002d)
    # psk_dhe_ke (0x01)
    psk_modes = b"\x01\x01"
    extensions.extend(struct.pack("!HH", 0x002D, len(psk_modes)) + psk_modes)

    # 5. Handshake ClientHello Body
    handshake_body = bytearray()
    handshake_body.extend(b"\x03\x03")  # Legacy client version TLS 1.2
    handshake_body.extend(random_bytes)
    handshake_body.append(len(sess_id))
    handshake_body.extend(sess_id)
    handshake_body.extend(struct.pack("!H", len(cipher_suites)))
    handshake_body.extend(cipher_suites)
    handshake_body.extend(compression_methods)
    handshake_body.extend(struct.pack("!H", len(extensions)))
    handshake_body.extend(extensions)

    # 6. Handshake Header: Type 0x01 (ClientHello), 3-byte Length
    handshake_len = len(handshake_body)
    handshake_header = b"\x01" + struct.pack("!I", handshake_len)[1:]
    handshake_packet = handshake_header + handshake_body

    # 7. TLS Plaintext Record: ContentType 0x16 (Handshake), Legacy Version 0x0301, 2-byte Length
    record_header = b"\x16\x03\x01" + struct.pack("!H", len(handshake_packet))
    return record_header + handshake_packet


def parse_client_hello(raw: bytes) -> Dict[str, Any]:
    """Разбирает байты TLS ClientHello для анализа и проверки тестами."""
    if len(raw) < 5:
        raise ValueError("Too short for TLS record")

    rec_type, rec_ver, rec_len = struct.unpack("!BHH", raw[:5])
    if rec_type != 0x16:
        raise ValueError(f"Not a handshake record (type={rec_type:#x})")

    body = raw[5:5 + rec_len]
    if len(body) < 4:
        raise ValueError("Too short for handshake header")

    hs_type = body[0]
    hs_len = struct.unpack("!I", b"\x00" + body[1:4])[0]
    if hs_type != 0x01:
        raise ValueError(f"Not a ClientHello (type={hs_type:#x})")

    pos = 4
    client_version = struct.unpack("!H", body[pos:pos+2])[0]
    pos += 2

    client_random = body[pos:pos+32]
    pos += 32

    sess_id_len = body[pos]
    pos += 1
    session_id = body[pos:pos+sess_id_len]
    pos += sess_id_len

    ciphers_len = struct.unpack("!H", body[pos:pos+2])[0]
    pos += 2
    ciphers_raw = body[pos:pos+ciphers_len]
    ciphers = [
        struct.unpack("!H", ciphers_raw[i:i+2])[0]
        for i in range(0, ciphers_len, 2)
    ]
    pos += ciphers_len

    comp_len = body[pos]
    pos += 1 + comp_len

    extensions: Dict[int, bytes] = {}
    sni = None
    alpn_list: List[str] = []

    if pos + 2 <= len(body):
        ext_total_len = struct.unpack("!H", body[pos:pos+2])[0]
        pos += 2
        end_ext = pos + ext_total_len
        while pos + 4 <= end_ext:
            ext_type, ext_len = struct.unpack("!HH", body[pos:pos+4])
            pos += 4
            ext_val = body[pos:pos+ext_len]
            pos += ext_len
            extensions[ext_type] = ext_val

            # Распознавание SNI
            if ext_type == 0x0000 and len(ext_val) >= 5:
                # list_len (2), name_type (1), name_len (2), name
                try:
                    name_type = ext_val[2]
                    name_len = struct.unpack("!H", ext_val[3:5])[0]
                    if name_type == 0 and len(ext_val) >= 5 + name_len:
                        sni = ext_val[5:5+name_len].decode("idna")
                except Exception:
                    pass

            # Распознавание ALPN
            elif ext_type == 0x0010 and len(ext_val) >= 2:
                alpn_len = struct.unpack("!H", ext_val[:2])[0]
                cur = 2
                while cur < 2 + alpn_len and cur < len(ext_val):
                    p_len = ext_val[cur]
                    cur += 1
                    proto = ext_val[cur:cur+p_len].decode("ascii", errors="replace")
                    alpn_list.append(proto)
                    cur += p_len

    return {
        "record_version": rec_ver,
        "client_version": client_version,
        "random": client_random,
        "session_id": session_id,
        "cipher_suites": ciphers,
        "extensions": extensions,
        "sni": sni,
        "alpn": alpn_list,
        "has_grease": any(c in {0x0a0a, 0x1a1a, 0x2a2a, 0x3a3a} for c in ciphers),
    }


# ---------------------------------------------------------------------------
# QUIC Initial Packet Generator
# ---------------------------------------------------------------------------

def _quic_varint(n: int) -> bytes:
    """Кодирует целое число в QUIC variable-length integer (RFC 9000)."""
    if n < 64:
        return struct.pack("!B", n)
    elif n < 16384:
        return struct.pack("!H", n | 0x4000)
    elif n < 1073741824:
        return struct.pack("!I", n | 0x80000000)
    else:
        return struct.pack("!Q", n | 0xC000000000000000)


def generate_quic_initial_packet(
    dcid: Optional[bytes] = None,
    scid: Optional[bytes] = None,
    min_size: int = 1200,
) -> bytes:
    """Генерирует QUIC Initial Packet (RFC 9000 v1) минимальным размером >= 1200 байт.

    Используется для проверки блокировки UDP 443 (QUIC_BLACKHOLE / UDP_DROP).
    """
    dest_cid = dcid if dcid is not None else os.urandom(8)
    src_cid = scid if scid is not None else os.urandom(8)

    # Long Header:
    # 0xC0: Header Form (1), Fixed Bit (1), Long Packet Type: Initial (0x00), Reserved/PN (0x00)
    header = bytearray()
    header.append(0xC0)
    header.extend(struct.pack("!I", 0x00000001))  # QUIC Version 1

    header.append(len(dest_cid))
    header.extend(dest_cid)

    header.append(len(src_cid))
    header.extend(src_cid)

    # Token Length = 0
    header.append(0x00)

    # Packet Number: 1 байт
    pn = b"\x00"

    # Minimal payload (CRYPTO dummy frame or PADDING)
    # Чтобы весь пакет был ровно min_size (1200 байт), вычисляем размер
    prefix_len = len(header)
    target_payload_len = min_size - prefix_len - 2 - len(pn)
    if target_payload_len < 0:
        target_payload_len = 0

    length_varint = _quic_varint(len(pn) + target_payload_len)
    header.extend(length_varint)
    header.extend(pn)

    # Payload padding
    payload = b"\x00" * target_payload_len
    packet = bytes(header) + payload

    # Гарантируем добивку до min_size
    if len(packet) < min_size:
        packet += b"\x00" * (min_size - len(packet))

    return packet


# ---------------------------------------------------------------------------
# Результаты и отчеты
# ---------------------------------------------------------------------------

def get_block_verdict(block_type: Union[BlockType, str]) -> Dict[str, str]:
    """Возвращает метаданные вердикта для UI (severity, CSS класс, бейдж, описание, рекомендация).
    Делегирует в единый источник правды (SSOT) — diagnostics/words.py.
    """
    from diagnostics.words import get_verdict_words
    val = block_type.value if isinstance(block_type, BlockType) else str(block_type)
    return get_verdict_words(val.upper())


def make_curl_cffi_transport(impersonate: str = "chrome124") -> Optional[Callable[..., Tuple[int, Dict[str, str], str]]]:
    """Опциональный curl_cffi транспорт для реалистичного Chrome TLS fingerprint.

    Если curl_cffi не установлен в системе, возвращает None (graceful fallback).
    """
    try:
        from curl_cffi import requests as curl_requests
    except ImportError:
        return None

    def _transport(
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 3.5,
    ) -> Tuple[int, Dict[str, str], str]:
        req_headers = {
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        }
        if headers:
            req_headers.update(headers)
        res = curl_requests.get(url, headers=req_headers, impersonate=impersonate, timeout=timeout)
        return res.status_code, dict(res.headers), res.text

    return _transport


@dataclass
class ClassificationResult:
    """Результат классификации одного хоста/домена."""
    target: str
    block_type: BlockType
    ip: Optional[str] = None
    details: str = ""
    rtt_ms: int = 0
    sub_checks: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    @property
    def is_blocked(self) -> bool:
        return self.block_type != BlockType.PASS

    @property
    def verdict(self) -> Dict[str, str]:
        return get_block_verdict(self.block_type)

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["block_type"] = self.block_type.value
        return data


@dataclass
class DiagnosticReport:
    """Структурированный отчёт по итогам прогона классификатора."""
    results: List[ClassificationResult]
    duration_ms: int = 0
    timestamp: float = field(default_factory=time.time)

    @property
    def summary(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for r in self.results:
            key = r.block_type.value
            counts[key] = counts.get(key, 0) + 1
        return counts

    @property
    def total_count(self) -> int:
        return len(self.results)

    @property
    def blocked_count(self) -> int:
        return sum(1 for r in self.results if r.is_blocked)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "summary": self.summary,
            "total_count": self.total_count,
            "blocked_count": self.blocked_count,
            "duration_ms": self.duration_ms,
            "timestamp": self.timestamp,
            "results": [r.to_dict() for r in self.results],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def summary_text(self) -> str:
        """Возвращает форматированный человекочитаемый отчет."""
        lines = [
            "=" * 60,
            "📊 DPI CLASSIFIER DIAGNOSTIC REPORT",
            "=" * 60,
            f"Проверено целей: {self.total_count} (Заблокировано: {self.blocked_count})",
            f"Время выполнения: {self.duration_ms} мс",
            "Распределение типов блокировок:",
        ]
        for b_type, count in sorted(self.summary.items()):
            lines.append(f"  • {b_type:<20}: {count}")
        lines.append("-" * 60)
        lines.append(f"{'ЦЕЛЬ':<25} {'ТИП БЛОКИРОВКИ':<20} {'IP':<16} {'RTT':<6} ДЕТАЛИ")
        lines.append("-" * 60)
        for r in self.results:
            ip_str = r.ip or "-"
            lines.append(f"{r.target:<25} {r.block_type.value:<20} {ip_str:<16} {r.rtt_ms:<4}мс {r.details}")
        lines.append("=" * 60)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# DPI Classifier Core
# ---------------------------------------------------------------------------

class DPIClassifier:
    """Классификатор методов цензуры и DPI ТСПУ.

    Поддерживает внедрение зависимостей (DNS resolver, socket factory)
    для 100% изоляции и детерминированного тестирования без реальной сети.
    """

    def __init__(
        self,
        timeout: float = 3.0,
        quic_timeout: float = 1.5,
        dns_resolver: Optional[Callable[[str], List[str]]] = None,
        trusted_dns_resolver: Optional[Callable[[str], List[str]]] = None,
        socket_factory: Callable[..., Any] = socket.socket,
        http_transport: Optional[Callable[..., Tuple[int, Dict[str, str], str]]] = None,
    ):
        self.timeout = timeout
        self.quic_timeout = quic_timeout
        self.dns_resolver = dns_resolver or self._default_dns_resolver
        self.trusted_dns_resolver = trusted_dns_resolver
        self.socket_factory = socket_factory
        self.http_transport = http_transport

    @staticmethod
    def _default_dns_resolver(domain: str) -> List[str]:
        """Стандартное системное разрешение DNS имен."""
        try:
            infos = socket.getaddrinfo(domain, None, socket.AF_INET, socket.SOCK_STREAM)
            return list({item[4][0] for item in infos})
        except Exception:
            return []

    # -----------------------------------------------------------------------
    # Sub-checks
    # -----------------------------------------------------------------------

    def check_dns(self, domain: str) -> Tuple[bool, Optional[str], str]:
        """Проверка DNS на подмену IP (DNS_SPOOFING)."""
        # Если цель уже является валидным IP-адресом, DNS спуфинг неприменим
        try:
            ipaddress.ip_address(domain)
            return False, domain, "Target is direct IP"
        except ValueError:
            pass

        resolved_ips = self.dns_resolver(domain)
        if not resolved_ips:
            return False, None, "DNS resolution returned no addresses"

        primary_ip = resolved_ips[0]

        # 1. Проверка на известные IP заглушек РКН/провайдеров
        for ip in resolved_ips:
            if is_known_blockpage_ip(ip):
                return True, ip, f"DNS resolved to known RKN/ISP blockpage IP: {ip}"

        # 2. Проверка на bogon / loopback / private IP для публичного домена
        for ip in resolved_ips:
            if is_bogon_ip(ip):
                return True, ip, f"DNS resolved to bogon/private/blackhole IP: {ip}"

        # 3. Сверка с доверенным резолвером (DoH / Do53)
        if self.trusted_dns_resolver:
            try:
                trusted_ips = self.trusted_dns_resolver(domain)
                if trusted_ips and not any(ip in trusted_ips for ip in resolved_ips):
                    return (
                        True,
                        primary_ip,
                        f"DNS mismatch: resolved {resolved_ips} vs trusted {trusted_ips}",
                    )
            except Exception:
                pass

        return False, primary_ip, f"DNS resolved cleanly to {primary_ip}"

    def check_tcp_handshake(self, ip: str, port: int = 443) -> Tuple[Optional[BlockType], str, Any]:
        """Проверяет базовое TCP соединение на порт (обычно 443)."""
        sock = self.socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((ip, port))
            return None, "TCP handshake established", sock
        except ConnectionResetError as exc:
            sock.close()
            return BlockType.TCP_RST_INJECTION, f"TCP RST received during handshake: {exc}", None
        except (socket.timeout, TimeoutError) as exc:
            sock.close()
            return BlockType.TIMEOUT, f"TCP connect timeout to {ip}:{port}: {exc}", None
        except Exception as exc:
            sock.close()
            return BlockType.ERROR, f"TCP connect failed: {exc}", None

    def check_tls_sni(
        self,
        domain: str,
        ip: str,
        port: int = 443,
        connected_socket: Any = None,
    ) -> Tuple[Optional[BlockType], str]:
        """Отправляет Chrome ClientHello и анализирует реакцию DPI на SNI.

        Обнаруживает:
        - TCP_RST_INJECTION: ТСПУ рвёт сокет RST-пакетом сразу после получения SNI.
        - TLS_SNI_DROP: ТСПУ молча отбрасывает пакеты (timeout на recv).
        - PASS: получен ответ сервера (ServerHello / Alert).
        """
        sock = connected_socket
        should_close = False
        if sock is None:
            sock = self.socket_factory(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self.timeout)
            should_close = True
            try:
                sock.connect((ip, port))
            except ConnectionResetError as exc:
                sock.close()
                return BlockType.TCP_RST_INJECTION, f"TCP RST during connection: {exc}"
            except (socket.timeout, TimeoutError) as exc:
                sock.close()
                return BlockType.TIMEOUT, f"TCP connection timed out: {exc}"
            except Exception as exc:
                sock.close()
                return BlockType.ERROR, f"TCP connection error: {exc}"

        try:
            sock.settimeout(self.timeout)
            # Генерируем Chrome ClientHello с целевым SNI
            client_hello = generate_chrome_client_hello(domain)
            sock.sendall(client_hello)

            # Ожидаем ответ (ServerHello)
            resp = sock.recv(4096)
            if not resp:
                return (
                    BlockType.TCP_RST_INJECTION,
                    "Connection closed immediately after SNI (FIN/empty)",
                )

            # Проверяем TLS ServerHello (ContentType 0x16, Version 0x03xx)
            if resp.startswith(b"\x16\x03"):
                return None, f"TLS ServerHello received ({len(resp)} bytes)"
            elif resp.startswith(b"\x15\x03"):
                # TLS Alert (например unrecognized_name) - цензор не вмешивался
                return None, f"TLS Alert received from server ({len(resp)} bytes)"
            else:
                return None, f"Received non-TLS response ({len(resp)} bytes)"

        except ConnectionResetError as exc:
            # Классика ТСПУ: активный сброс RST сокетом при чтении или отправке SNI
            return (
                BlockType.TCP_RST_INJECTION,
                f"TCP RST injected after TLS ClientHello (SNI '{domain}'): {exc}",
            )
        except (socket.timeout, TimeoutError) as exc:
            # ТСПУ дропает пакеты по SNI (черная дыра)
            return (
                BlockType.TLS_SNI_DROP,
                f"Timeout awaiting ServerHello; packet dropped by DPI for SNI '{domain}': {exc}",
            )
        except Exception as exc:
            return BlockType.ERROR, f"Error during TLS handshake: {exc}"
        finally:
            if should_close:
                try:
                    sock.close()
                except Exception:
                    pass

    def check_http_blockpage(self, domain: str, ip: str, port: int = 80) -> Tuple[bool, str]:
        """Отправляет простой HTTP GET запрос и проверяет на заглушку РКН/провайдера."""
        if self.http_transport is not None:
            try:
                status_code, headers, body = self.http_transport(f"http://{domain}:{port}/", timeout=self.timeout)
                return detect_blockpage_content(status_code, headers, body)
            except ConnectionResetError as exc:
                return True, f"TCP RST during HTTP request: {exc}"
            except Exception as exc:
                return False, f"HTTP check failed via transport: {exc}"

        sock = self.socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        try:
            sock.connect((ip, port))
            http_req = (
                f"GET / HTTP/1.1\r\n"
                f"Host: {domain}\r\n"
                f"User-Agent: Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36\r\n"
                f"Connection: close\r\n\r\n"
            ).encode("utf-8")
            sock.sendall(http_req)

            resp_data = bytearray()
            while True:
                try:
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    resp_data.extend(chunk)
                    if len(resp_data) > 65536:
                        break
                except (socket.timeout, TimeoutError):
                    break

            raw_text = resp_data.decode("utf-8", errors="replace")
            if not raw_text:
                return False, "Empty HTTP response"

            # Разбор статуса и заголовков
            lines = raw_text.split("\r\n")
            status_line = lines[0] if lines else ""
            status_code = 0
            parts = status_line.split(" ")
            if len(parts) >= 2 and parts[1].isdigit():
                status_code = int(parts[1])

            headers: Dict[str, str] = {}
            body_start = 0
            for i, line in enumerate(lines[1:], 1):
                if not line:
                    body_start = i + 1
                    break
                if ":" in line:
                    k, v = line.split(":", 1)
                    headers[k.strip()] = v.strip()

            body = "\r\n".join(lines[body_start:]) if body_start else ""

            is_blocked, reason = detect_blockpage_content(status_code, headers, body)
            return is_blocked, reason

        except ConnectionResetError as exc:
            return True, f"TCP RST during HTTP request: {exc}"
        except Exception as exc:
            return False, f"HTTP check failed: {exc}"
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def check_quic(self, ip: str, port: int = 443) -> Tuple[bool, str]:
        """Отправляет QUIC Initial пакет и проверяет блокировку UDP/443 (QUIC_BLACKHOLE).

        Возвращает (is_dropped, details).
        """
        sock = self.socket_factory(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(self.quic_timeout)
        try:
            packet = generate_quic_initial_packet()
            sock.sendto(packet, (ip, port))
            resp, _ = sock.recvfrom(2048)
            return False, f"QUIC response received ({len(resp)} bytes)"
        except (socket.timeout, TimeoutError):
            return True, "QUIC Initial packet dropped (UDP/443 timeout)"
        except Exception as exc:
            return True, f"QUIC test failed with exception: {exc}"
        finally:
            try:
                sock.close()
            except Exception:
                pass

    def classify_quic(self, target: str, ip: Optional[str] = None, port: int = 443) -> ClassificationResult:
        """Специализированная проверка блокировки QUIC/UDP для цели."""
        t0 = time.time()
        cleaned_target = re.sub(r"^(?:quic|udp|https?)://", "", target).split("/")[0].strip()

        resolved_ip = ip
        if not resolved_ip:
            is_spoofed, maybe_ip, _ = self.check_dns(cleaned_target)
            if is_spoofed:
                dt = int((time.time() - t0) * 1000)
                return ClassificationResult(
                    target=cleaned_target,
                    block_type=BlockType.DNS_SPOOFING,
                    ip=maybe_ip,
                    details="DNS Spoofed before QUIC check",
                    rtt_ms=dt,
                )
            resolved_ip = maybe_ip

        if not resolved_ip:
            dt = int((time.time() - t0) * 1000)
            return ClassificationResult(
                target=cleaned_target,
                block_type=BlockType.ERROR,
                details="Could not resolve IP for QUIC check",
                rtt_ms=dt,
            )

        is_dropped, details = self.check_quic(resolved_ip, port)
        dt = int((time.time() - t0) * 1000)
        block_type = BlockType.QUIC_BLACKHOLE if is_dropped else BlockType.PASS
        return ClassificationResult(
            target=cleaned_target,
            block_type=block_type,
            ip=resolved_ip,
            details=details,
            rtt_ms=dt,
            sub_checks={"quic": {"dropped": is_dropped, "details": details}},
        )

    # -----------------------------------------------------------------------
    # Основная логика классификации
    # -----------------------------------------------------------------------

    def classify(
        self,
        target: str,
        ip: Optional[str] = None,
        check_http: bool = True,
        check_quic_flag: bool = True,
        mode: str = "auto",  # 'auto', 'quic_only', 'tls_only'
    ) -> ClassificationResult:
        """Классифицирует тип цензуры для указанной цели (домен или IP)."""
        # Если явно запрошена только QUIC диагностика
        if mode == "quic_only" or target.startswith(("quic://", "udp://")):
            return self.classify_quic(target, ip=ip)

        t0 = time.time()
        sub_checks: Dict[str, Any] = {}

        # Нормализация цели
        cleaned_target = re.sub(r"^https?://", "", target).split("/")[0].strip()
        if not cleaned_target:
            return ClassificationResult(
                target=target,
                block_type=BlockType.ERROR,
                details="Empty target",
            )

        # Шаг 1: DNS классификация
        resolved_ip = ip
        if not resolved_ip:
            is_spoofed, maybe_ip, dns_msg = self.check_dns(cleaned_target)
            sub_checks["dns"] = {"spoofed": is_spoofed, "ip": maybe_ip, "details": dns_msg}
            if is_spoofed:
                dt = int((time.time() - t0) * 1000)
                return ClassificationResult(
                    target=cleaned_target,
                    block_type=BlockType.DNS_SPOOFING,
                    ip=maybe_ip,
                    details=dns_msg,
                    rtt_ms=dt,
                    sub_checks=sub_checks,
                )
            resolved_ip = maybe_ip

        if not resolved_ip:
            dt = int((time.time() - t0) * 1000)
            return ClassificationResult(
                target=cleaned_target,
                block_type=BlockType.ERROR,
                details="Could not resolve target IP",
                rtt_ms=dt,
                sub_checks=sub_checks,
            )

        # Шаг 2: TCP Handshake к 443
        tcp_block, tcp_msg, connected_sock = self.check_tcp_handshake(resolved_ip, 443)
        sub_checks["tcp"] = {"block": tcp_block.value if tcp_block else None, "details": tcp_msg}

        if tcp_block == BlockType.TCP_RST_INJECTION:
            dt = int((time.time() - t0) * 1000)
            return ClassificationResult(
                target=cleaned_target,
                block_type=BlockType.TCP_RST_INJECTION,
                ip=resolved_ip,
                details=tcp_msg,
                rtt_ms=dt,
                sub_checks=sub_checks,
            )

        # Шаг 3: TLS SNI Check с Chrome ClientHello
        tls_block = None
        tls_msg = ""
        if connected_sock is not None:
            tls_block, tls_msg = self.check_tls_sni(
                domain=cleaned_target,
                ip=resolved_ip,
                port=443,
                connected_socket=connected_sock,
            )
            try:
                connected_sock.close()
            except Exception:
                pass
        else:
            # Если TCP 443 упал по таймауту
            tls_block = tcp_block
            tls_msg = tcp_msg

        sub_checks["tls"] = {"block": tls_block.value if tls_block else None, "details": tls_msg}

        if tls_block in (BlockType.TCP_RST_INJECTION, BlockType.TLS_SNI_DROP):
            dt = int((time.time() - t0) * 1000)
            return ClassificationResult(
                target=cleaned_target,
                block_type=tls_block,
                ip=resolved_ip,
                details=tls_msg,
                rtt_ms=dt,
                sub_checks=sub_checks,
            )

        # Шаг 4: HTTP Blockpage Check (если порт 80 доступен)
        if check_http and mode != "tls_only":
            is_blockpage, http_msg = self.check_http_blockpage(cleaned_target, resolved_ip, 80)
            sub_checks["http"] = {"blockpage": is_blockpage, "details": http_msg}
            if is_blockpage:
                dt = int((time.time() - t0) * 1000)
                # Если в HTTP прилетел RST
                if "TCP RST" in http_msg:
                    return ClassificationResult(
                        target=cleaned_target,
                        block_type=BlockType.TCP_RST_INJECTION,
                        ip=resolved_ip,
                        details=http_msg,
                        rtt_ms=dt,
                        sub_checks=sub_checks,
                    )
                return ClassificationResult(
                    target=cleaned_target,
                    block_type=BlockType.HTTP_BLOCKPAGE,
                    ip=resolved_ip,
                    details=http_msg,
                    rtt_ms=dt,
                    sub_checks=sub_checks,
                )

        # Шаг 5: QUIC / UDP Check
        if check_quic_flag:
            is_quic_dropped, quic_msg = self.check_quic(resolved_ip, 443)
            sub_checks["quic"] = {"dropped": is_quic_dropped, "details": quic_msg}

        # Итоговая оценка
        dt = int((time.time() - t0) * 1000)
        if tls_block == BlockType.TIMEOUT or tcp_block == BlockType.TIMEOUT:
            return ClassificationResult(
                target=cleaned_target,
                block_type=BlockType.TIMEOUT,
                ip=resolved_ip,
                details=tls_msg or tcp_msg,
                rtt_ms=dt,
                sub_checks=sub_checks,
            )

        if tls_block == BlockType.ERROR or tcp_block == BlockType.ERROR:
            return ClassificationResult(
                target=cleaned_target,
                block_type=BlockType.ERROR,
                details=tls_msg or tcp_msg,
                rtt_ms=dt,
                sub_checks=sub_checks,
            )

        # Если явных TCP/TLS блокировок нет, но QUIC заблокирован (например для видеосервисов)
        if check_quic_flag and sub_checks.get("quic", {}).get("dropped"):
            # В details указываем статус QUIC
            quic_status_note = " (QUIC/UDP blocked)"
        else:
            quic_status_note = ""

        return ClassificationResult(
            target=cleaned_target,
            block_type=BlockType.PASS,
            ip=resolved_ip,
            details="Traffic passes cleanly without censorship" + quic_status_note,
            rtt_ms=dt,
            sub_checks=sub_checks,
        )

    # -----------------------------------------------------------------------
    # Диагностический прогон по списку целей
    # -----------------------------------------------------------------------

    def run_diagnostics(
        self,
        targets: Sequence[str],
        max_workers: int = 5,
        check_http: bool = True,
        check_quic_flag: bool = True,
        mode: str = "auto",
    ) -> DiagnosticReport:
        """Быстрый параллельный диагностический прогон по списку доменов/IP."""
        t0 = time.time()
        results: List[ClassificationResult] = []

        if not targets:
            return DiagnosticReport(results=[], duration_ms=0)

        workers = min(max_workers, len(targets))
        with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
            future_to_target = {
                executor.submit(
                    self.classify,
                    target,
                    check_http=check_http,
                    check_quic_flag=check_quic_flag,
                    mode=mode,
                ): target
                for target in targets
            }
            for future in concurrent.futures.as_completed(future_to_target):
                target = future_to_target[future]
                try:
                    res = future.result()
                    results.append(res)
                except Exception as exc:
                    results.append(
                        ClassificationResult(
                            target=target,
                            block_type=BlockType.ERROR,
                            details=f"Unexpected error in diagnostic worker: {exc}",
                        )
                    )

        # Сортируем результаты в исходном порядке targets
        order_map = {t: i for i, t in enumerate(targets)}
        results.sort(key=lambda r: order_map.get(r.target, 9999))

        duration_ms = int((time.time() - t0) * 1000)
        return DiagnosticReport(
            results=results,
            duration_ms=duration_ms,
        )


def classify_domains(
    domains: Sequence[str],
    timeout: float = 3.0,
    max_workers: int = 5,
    mode: str = "auto",
    http_transport: Optional[Callable[..., Tuple[int, Dict[str, str], str]]] = None,
) -> DiagnosticReport:
    """Удобная функция быстрого запуска диагностики списка доменов."""
    classifier = DPIClassifier(timeout=timeout, http_transport=http_transport)
    return classifier.run_diagnostics(domains, max_workers=max_workers, mode=mode)
