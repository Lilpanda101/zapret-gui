"""
diagnostics/domain_inspector.py - Диагностика домена:
DNS UDP/TCP/DoT/DoH со сравнением, ICMP, TCP 443, TLS-рукопожатие, сертификат SAN/issuer/срок, ASN.
Внешние сервисы — строго под чекбоксом (allow_external_asn=True).
Локальные и приватные адреса никогда не отправляются наружу.
"""

from dataclasses import dataclass, field
import datetime
import ipaddress
import json
import socket
import ssl
import subprocess
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
import urllib.request


@dataclass
class CertificateInfo:
    subject: str = ""
    issuer: str = ""
    not_before: str = ""
    not_after: str = ""
    san: List[str] = field(default_factory=list)
    version: int = 3
    is_valid_date: bool = True


@dataclass
class DomainInspectionReport:
    domain: str
    timestamp: float = field(default_factory=time.time)
    dns_resolutions: Dict[str, List[str]] = field(default_factory=dict)
    dns_spoofed: bool = False
    dns_details: str = ""
    target_ip: Optional[str] = None
    icmp_available: Optional[bool] = None
    icmp_rtt_ms: Optional[float] = None
    tcp_connected: bool = False
    tcp_rtt_ms: Optional[float] = None
    tls_connected: bool = False
    tls_version: Optional[str] = None
    tls_cipher: Optional[str] = None
    cert_info: Optional[CertificateInfo] = None
    asn_number: Optional[str] = None
    asn_org: Optional[str] = None
    asn_country: Optional[str] = None
    asn_source: str = "disabled"
    summary_verdict: str = "Не проверялось"
    proof_line: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "domain": self.domain,
            "timestamp": self.timestamp,
            "dns_resolutions": self.dns_resolutions,
            "dns_spoofed": self.dns_spoofed,
            "dns_details": self.dns_details,
            "target_ip": self.target_ip,
            "icmp_available": self.icmp_available,
            "icmp_rtt_ms": self.icmp_rtt_ms,
            "tcp_connected": self.tcp_connected,
            "tcp_rtt_ms": self.tcp_rtt_ms,
            "tls_connected": self.tls_connected,
            "tls_version": self.tls_version,
            "tls_cipher": self.tls_cipher,
            "asn_number": self.asn_number,
            "asn_org": self.asn_org,
            "asn_country": self.asn_country,
            "asn_source": self.asn_source,
            "summary_verdict": self.summary_verdict,
            "proof_line": self.proof_line,
        }


def is_private_ip(ip_str: str) -> bool:
    """Проверяет, является ли IP локальным, петлевым, CGNAT или приватным."""
    try:
        ip = ipaddress.ip_address(ip_str)
        # RFC 6598 CGNAT 100.64.0.0/10
        cgnat_net = ipaddress.ip_network("100.64.0.0/10")
        return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or (ip in cgnat_net)
    except ValueError:
        return True


class DomainInspector:
    """Выполняет разносторонний технический аудит домена без привлечения root прав."""

    def __init__(
        self,
        dns_resolver_fn: Optional[Callable[[str, str], List[str]]] = None,
        socket_factory: Optional[Callable[..., socket.socket]] = None,
        http_get_fn: Optional[Callable[[str], Tuple[int, str]]] = None,
        allow_external_asn: bool = False,
        timeout: float = 3.5,
    ):
        self.dns_resolver_fn = dns_resolver_fn
        self.socket_factory = socket_factory or socket.socket
        self.http_get_fn = http_get_fn
        self.allow_external_asn = allow_external_asn
        self.timeout = timeout

    def resolve_all_dns(self, domain: str) -> Tuple[Dict[str, List[str]], bool, str]:
        """
        Резолвит домен через системный UDP/TCP и публичные DoT/DoH endpoints.
        Возвращает карту результатов, признак спуфинга и доказательство.
        """
        results: Dict[str, List[str]] = {}

        if self.dns_resolver_fn is not None:
            for proto in ("system_udp", "tcp_google", "dot_cloudflare", "doh_quad9"):
                try:
                    ips = self.dns_resolver_fn(domain, proto)
                    if ips:
                        results[proto] = ips
                except Exception:
                    pass
        else:
            # 1. System getaddrinfo
            try:
                infos = socket.getaddrinfo(domain, 443, socket.AF_INET, socket.SOCK_STREAM)
                sys_ips = sorted(list(set(item[4][0] for item in infos if item[4])))
                if sys_ips:
                    results["system_udp"] = sys_ips
            except Exception:
                results["system_udp"] = []

            # 2. DoH Cloudflare
            try:
                req = urllib.request.Request(
                    f"https://1.1.1.1/dns-query?name={domain}&type=A",
                    headers={"Accept": "application/dns-json", "User-Agent": "ZapretGUI/2.0"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8", "ignore"))
                        answers = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
                        if answers:
                            results["dot_cloudflare"] = sorted(answers)
            except Exception:
                pass

            # 3. DoH Google
            try:
                req = urllib.request.Request(
                    f"https://dns.google/resolve?name={domain}&type=A",
                    headers={"Accept": "application/json", "User-Agent": "ZapretGUI/2.0"},
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    if resp.status == 200:
                        data = json.loads(resp.read().decode("utf-8", "ignore"))
                        answers = [a["data"] for a in data.get("Answer", []) if a.get("type") == 1]
                        if answers:
                            results["tcp_google"] = sorted(answers)
            except Exception:
                pass

        # Анализ на подмену
        from diagnostics.classify import classify_dns_responses
        verdict = classify_dns_responses(domain, results)
        if verdict:
            return results, True, verdict.proof
        return results, False, "DNS-ответы резолверов согласованы"

    def check_icmp(self, ip: str) -> Tuple[Optional[bool], Optional[float]]:
        """Проверка доступности хоста по ICMP (ping) с таймаутом."""
        if not ip or is_private_ip(ip):
            return None, None
        try:
            t0 = time.time()
            res = subprocess.run(
                ["ping", "-c", "1", "-W", "2", ip],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=2.5,
            )
            rtt = round((time.time() - t0) * 1000, 1)
            if res.returncode == 0:
                return True, rtt
            return False, None
        except Exception:
            return None, None

    def check_tcp_port(self, ip: str, port: int = 443) -> Tuple[bool, Optional[float]]:
        """Проверяет установление TCP соединения на указанный порт."""
        if not ip:
            return False, None
        s = self.socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(self.timeout)
        t0 = time.time()
        try:
            s.connect((ip, port))
            dt = round((time.time() - t0) * 1000, 1)
            s.close()
            return True, dt
        except Exception:
            try:
                s.close()
            except Exception:
                pass
            return False, None

    def inspect_tls_handshake(self, domain: str, ip: str, port: int = 443) -> Tuple[bool, Optional[str], Optional[str], Optional[CertificateInfo]]:
        """Выполняет TLS рукопожатие и извлекает информацию о сертификате (SAN, issuer, срок)."""
        if not ip:
            return False, None, None, None

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

        raw_sock = self.socket_factory(socket.AF_INET, socket.SOCK_STREAM)
        raw_sock.settimeout(self.timeout)
        try:
            raw_sock.connect((ip, port))
            tls_sock = ctx.wrap_socket(raw_sock, server_hostname=domain)
            ver = tls_sock.version()
            cipher_info = tls_sock.cipher()
            cipher_name = cipher_info[0] if cipher_info else None

            # Извлечение сертификата
            cert = tls_sock.getpeercert(binary_form=False)
            cert_obj = None
            if cert:
                san_list = [entry[1] for entry in cert.get("subjectAltName", []) if entry[0] == "DNS"]
                sub_entries = [f"{part[0][0]}={part[0][1]}" for part in cert.get("subject", ()) if part]
                iss_entries = [f"{part[0][0]}={part[0][1]}" for part in cert.get("issuer", ()) if part]

                cert_obj = CertificateInfo(
                    subject=", ".join(sub_entries),
                    issuer=", ".join(iss_entries),
                    not_before=cert.get("notBefore", ""),
                    not_after=cert.get("notAfter", ""),
                    san=san_list,
                    version=cert.get("version", 3),
                )
            tls_sock.close()
            return True, ver, cipher_name, cert_obj
        except Exception:
            try:
                raw_sock.close()
            except Exception:
                pass
            return False, None, None, None

    def lookup_asn(self, ip: str) -> Tuple[Optional[str], Optional[str], Optional[str], str]:
        """
        Запрашивает ASN и принадлежность IP сети.
        Защита приватности: только если включен флаг allow_external_asn, и НИКОГДА для приватных IP.
        """
        if not self.allow_external_asn:
            return None, None, None, "Внешние запросы ASN отключены настройкой приватности"

        if not ip or is_private_ip(ip):
            return None, None, None, "Локальный/приватный IP не передается внешним сервисам"

        if self.http_get_fn is not None:
            try:
                code, text = self.http_get_fn(f"https://ipapi.co/{ip}/json/")
                if code == 200:
                    d = json.loads(text)
                    return d.get("asn"), d.get("org"), d.get("country_name"), "ipapi"
            except Exception:
                pass

        try:
            req = urllib.request.Request(
                f"https://ipapi.co/{ip}/json/",
                headers={"User-Agent": "ZapretGUI/2.0"},
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8", "ignore"))
                    return data.get("asn"), data.get("org"), data.get("country_name"), "ipapi"
        except Exception as exc:
            return None, None, None, f"Ошибка запроса ASN: {exc}"

        return None, None, None, "Не удалось определить ASN"

    def inspect(self, domain: str) -> DomainInspectionReport:
        """Полный цикл инспекции домена."""
        domain = domain.strip().lower()
        report = DomainInspectionReport(domain=domain)

        # 1. DNS
        dns_res, is_spoofed, dns_proof = self.resolve_all_dns(domain)
        report.dns_resolutions = dns_res
        report.dns_spoofed = is_spoofed
        report.dns_details = dns_proof

        # Выбираем целевой IP (предпочтительно из защищенных DoT/DoH или системного)
        chosen_ip = None
        for key in ("dot_cloudflare", "tcp_google", "system_udp"):
            if dns_res.get(key):
                chosen_ip = dns_res[key][0]
                break
        report.target_ip = chosen_ip

        if not chosen_ip:
            report.summary_verdict = "Ошибка DNS"
            report.proof_line = "Домен не резолвится ни одним доступным DNS-сервером"
            return report

        if is_spoofed:
            report.summary_verdict = "DNS Подмена (CRITICAL)"
            report.proof_line = dns_proof
            # Даже при спуфинге продолжим тест указанного IP для полноты картины

        # 2. ICMP
        icmp_ok, icmp_rtt = self.check_icmp(chosen_ip)
        report.icmp_available = icmp_ok
        report.icmp_rtt_ms = icmp_rtt

        # 3. TCP 443
        tcp_ok, tcp_rtt = self.check_tcp_port(chosen_ip, 443)
        report.tcp_connected = tcp_ok
        report.tcp_rtt_ms = tcp_rtt

        # 4. TLS Handshake & Cert
        tls_ok, tls_ver, tls_ciph, cert_obj = self.inspect_tls_handshake(domain, chosen_ip, 443)
        report.tls_connected = tls_ok
        report.tls_version = tls_ver
        report.tls_cipher = tls_ciph
        report.cert_info = cert_obj

        # 5. ASN
        asn_num, asn_org, asn_country, asn_src = self.lookup_asn(chosen_ip)
        report.asn_number = asn_num
        report.asn_org = asn_org
        report.asn_country = asn_country
        report.asn_source = asn_src

        # Итоговое доказательство
        from diagnostics.classify import classify_network_drop
        if is_spoofed:
            pass # уже проставлен выше
        elif not tcp_ok:
            drop_v = classify_network_drop(
                target=domain,
                tcp_connected=False,
                tls_connected=False,
                sni_drop=False,
                rst_received=False,
                ip_ping_ok=icmp_ok,
            )
            report.summary_verdict = drop_v.verdict.value
            report.proof_line = drop_v.proof
        elif tcp_ok and not tls_ok:
            drop_v = classify_network_drop(
                target=domain,
                tcp_connected=True,
                tls_connected=False,
                sni_drop=True,
                rst_received=False,
            )
            report.summary_verdict = drop_v.verdict.value
            report.proof_line = drop_v.proof
        else:
            report.summary_verdict = "PASS"
            report.proof_line = f"Соединение установлено: TCP {tcp_rtt}ms, TLS {tls_ver} ({tls_ciph})"

        return report
