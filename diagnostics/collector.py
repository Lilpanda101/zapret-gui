"""
diagnostics/collector.py - Сбор сетевых фактов для диагностики причин блокировки.
Выполняет пробы к тому же IP:
1. Тот же IP с настоящим SNI
2. Тот же IP с посторонним SNI (example.com)
3. Тот же IP без SNI
4. Тот же IP с тем же SNI другим регистром (case_variant)
5. Тот же IP с allowed именами (max.ru, ya.ru, vk.com) для режима белых списков
6. Проба окна приёма: 1 байт (две попытки) против контроля 1 КБ
7. HTTP 80 для заглушки и 451
Пауза STAGGER_S (0.25 с) между стартами приветствий к одному адресу.
"""

from __future__ import annotations

import socket
import ssl
import time
from typing import Callable, Dict, List, Optional, Tuple

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
    STAGGER_S,
    CauseFacts,
    HelloResult,
    HttpFacts,
    case_variant,
)


def _client_hello_bytes(name: str) -> bytes:
    """Генерирует бинарный ClientHello с указанным SNI (или без него)."""
    from dpi_classifier import make_chrome_tls_client_hello
    if name:
        return make_chrome_tls_client_hello(name)
    # Минимальный TLS ClientHello без SNI
    return (
        b"\x16\x03\x01\x00\x38"
        b"\x01\x00\x00\x34\x03\x03"
        + b"\x00" * 32
        + b"\x00"
        b"\x00\x04\x13\x01\x13\x02"
        b"\x01\x00\x00\x09\x00\x00\x00\x05\x00\x03\x00\x00\x00"
    )


def send_tls_hello(
    ip: str,
    name: str,
    port: int = 443,
    timeout: float = 3.5,
    window: Optional[int] = None,
    socket_factory: Optional[Callable[..., socket.socket]] = None,
) -> HelloResult:
    """Отправляет ClientHello к указанному адресу с контролем SO_RCVBUF (окно приёма)."""
    sf = socket_factory or socket.socket
    hello_bytes = _client_hello_bytes(name)
    sock = sf(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM)
    try:
        if window is not None:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, int(window))
        sock.settimeout(timeout)
        t0 = time.time()
        sock.connect((ip, port))
        sock.sendall(hello_bytes)

        # Читаем первые байты ответа (тип записи TLS: 0x16 Handshake или 0x15 Alert)
        header = sock.recv(5)
        dt = round((time.time() - t0) * 1000, 1)
        if not header:
            sock.close()
            return HelloResult(HELLO_RESET, dt, 0)

        record_type = header[0]
        if record_type == 0x16:
            sock.close()
            return HelloResult(HELLO_OK, dt, len(header))
        elif record_type == 0x15:
            sock.close()
            return HelloResult(HELLO_ALERT, dt, len(header))
        else:
            sock.close()
            return HelloResult(HELLO_ALERT, dt, len(header))

    except (socket.timeout, TimeoutError):
        try:
            sock.close()
        except Exception:
            pass
        return HelloResult(HELLO_TIMEOUT)
    except ConnectionResetError:
        try:
            sock.close()
        except Exception:
            pass
        return HelloResult(HELLO_RESET)
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return HelloResult(HELLO_CONNECT)


def probe_http_80(
    ip: str,
    host: str,
    timeout: float = 3.5,
    socket_factory: Optional[Callable[..., socket.socket]] = None,
) -> HttpFacts:
    """Проверяет ответ на порт 80 для выявления редиректов или заглушек провайдера."""
    sf = socket_factory or socket.socket
    sock = sf(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(timeout)
        sock.connect((ip, 80))
        req = f"GET / HTTP/1.1\r\nHost: {host}\r\nUser-Agent: ZapretGUI/2.0\r\nConnection: close\r\n\r\n"
        sock.sendall(req.encode("utf-8"))
        res = sock.recv(4096).decode("latin-1", "ignore")
        sock.close()

        lines = res.split("\r\n")
        status = None
        location = ""
        if lines:
            parts = lines[0].split()
            if len(parts) >= 2 and parts[1].isdigit():
                status = int(parts[1])
        for line in lines[1:]:
            if line.lower().startswith("location:"):
                location = line.split(":", 1)[1].strip()
                break
        return HttpFacts(status=status, location=location, body=res)
    except Exception:
        try:
            sock.close()
        except Exception:
            pass
        return HttpFacts()


def extract_real_tls_cert(
    ip: str,
    domain: str,
    port: int = 443,
    timeout: float = 3.5,
    socket_factory: Optional[Callable[..., socket.socket]] = None,
) -> Tuple[Optional[bool], Optional[bool], str]:
    """
    Выполняет реальный TLS handshake к IP с указанным SNI (domain).
    Возвращает (cert_valid, cert_san_match, cert_issuer).
    - cert_valid: True если сертификат доверен и валиден, False если поддельный/самоподписанный, None при сбое соединения.
    - cert_san_match: True если domain совпадает с SAN или CN в сертификате, иначе False.
    - cert_issuer: издатель сертификата (CA).
    """
    if not ip or not domain:
        return None, None, ""
    sf = socket_factory or socket.socket
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_REQUIRED
    try:
        sock = sf(socket.AF_INET6 if ":" in ip else socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((ip, port))
        tls_sock = ctx.wrap_socket(sock, server_hostname=domain)
        cert = tls_sock.getpeercert()
        tls_sock.close()
        sans = [v for k, v in cert.get("subjectAltName", []) if k == "DNS"]
        common_names = [part[0][1] for part in cert.get("subject", ()) if part and part[0][0] == "commonName"]
        all_names = sans + common_names
        dom_lower = domain.lower()
        match = any(
            dom_lower == san.lower() or (san.startswith("*.") and dom_lower.endswith(san[1:].lower()))
            for san in all_names
        )
        issuer_parts = [f"{part[0][0]}={part[0][1]}" for part in cert.get("issuer", ()) if part]
        issuer_str = ", ".join(issuer_parts)
        return True, match, issuer_str
    except ssl.SSLCertVerificationError as exc:
        msg = getattr(exc, "verify_message", str(exc))
        return False, False, f"Ошибка валидации CA: {msg}"
    except Exception as exc:
        return None, None, str(exc)


class NetworkFactCollector:
    """Сборщик фактов с паузой STAGGER_S (0.25с) между запросами к одному IP."""

    def __init__(
        self,
        hello_fn: Optional[Callable[..., HelloResult]] = None,
        http_fn: Optional[Callable[..., HttpFacts]] = None,
        ping_fn: Optional[Callable[[str], bool]] = None,
        stagger_s: float = STAGGER_S,
        timeout: float = 3.5,
    ):
        self.hello_fn = hello_fn or send_tls_hello
        self.http_fn = http_fn or probe_http_80
        self.ping_fn = ping_fn
        self.stagger_s = stagger_s
        self.timeout = timeout

    def collect(self, host: str, ip: str) -> CauseFacts:
        host = host.strip().lower()

        # 1. Настоящее имя
        real = self.hello_fn(ip, host, timeout=self.timeout)
        time.sleep(self.stagger_s)

        # 2. Постороннее имя
        neutral = self.hello_fn(ip, NEUTRAL_NAME, timeout=self.timeout)
        time.sleep(self.stagger_s)

        # 3. Без SNI
        nameless = self.hello_fn(ip, "", timeout=self.timeout)
        time.sleep(self.stagger_s)

        # 4. Другой регистр
        recased_n = case_variant(host)
        recased_res = None
        if recased_n:
            recased_res = self.hello_fn(ip, recased_n, timeout=self.timeout)
            time.sleep(self.stagger_s)

        # 5. Разрешённые имена (белые списки)
        allowed_results: Dict[str, HelloResult] = {}
        for a_name in ALLOWED_NAMES:
            res = self.hello_fn(ip, a_name, timeout=self.timeout)
            allowed_results[a_name] = res
            time.sleep(self.stagger_s)
            if res.answered:
                break

        # 6. HTTP 80
        http_facts = self.http_fn(ip, host, timeout=self.timeout)

        # 7. ICMP Ping
        ping_ok = None
        if self.ping_fn is not None:
            ping_ok = self.ping_fn(ip)

        # 8. Проба окна приёма (1 байт x2 и контроль 1 КБ)
        small_1 = None
        small_2 = None
        control = None
        if not real.answered and not neutral.answered:
            small_1 = self.hello_fn(ip, NEUTRAL_NAME, timeout=self.timeout, window=SMALL_WINDOW_BYTES)
            time.sleep(self.stagger_s)
            if small_1.answered:
                small_2 = self.hello_fn(ip, NEUTRAL_NAME, timeout=self.timeout, window=SMALL_WINDOW_BYTES)
                time.sleep(self.stagger_s)
                control = self.hello_fn(ip, NEUTRAL_NAME, timeout=self.timeout, window=CONTROL_WINDOW_BYTES)

        return CauseFacts(
            host=host,
            ip=ip,
            real_hello=real,
            neutral_hello=neutral,
            nameless_hello=nameless,
            allowed_hellos=allowed_results,
            recased_name=recased_n,
            recased_hello=recased_res,
            http=http_facts,
            ping_ok=ping_ok,
            small_window_1=small_1,
            small_window_2=small_2,
            window_control=control,
        )
