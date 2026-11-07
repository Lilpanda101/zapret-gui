"""
diagnostics/quic_analyzer.py - Замер и вердикт доступности QUIC / HTTP/3.
Сравнивает задержки и доступность с включенным QUIC и при отказе от QUIC.
Формирует понятный вердикт пользователю о целесообразности отключения QUIC.
"""

from dataclasses import dataclass
import socket
import time
from typing import Callable, Optional, Tuple


@dataclass
class QuicVerdict:
    domain: str
    quic_available: bool
    quic_rtt_ms: Optional[float]
    tcp_available: bool
    tcp_rtt_ms: Optional[float]
    penalty_ms: Optional[float]
    verdict_text: str
    recommendation: str
    price_of_refusal: str

    def to_dict(self):
        return {
            "domain": self.domain,
            "quic_available": self.quic_available,
            "quic_rtt_ms": self.quic_rtt_ms,
            "tcp_available": self.tcp_available,
            "tcp_rtt_ms": self.tcp_rtt_ms,
            "penalty_ms": self.penalty_ms,
            "verdict_text": self.verdict_text,
            "recommendation": self.recommendation,
            "price_of_refusal": self.price_of_refusal,
        }


class QuicAnalyzer:
    """Анализирует доступность протокола QUIC (UDP 443) и TCP 443."""

    def __init__(
        self,
        quic_probe_fn: Optional[Callable[[str, int], Tuple[bool, Optional[float]]]] = None,
        tcp_probe_fn: Optional[Callable[[str, int], Tuple[bool, Optional[float]]]] = None,
        timeout: float = 3.0,
    ):
        self.quic_probe_fn = quic_probe_fn
        self.tcp_probe_fn = tcp_probe_fn
        self.timeout = timeout

    def probe_quic(self, host: str, port: int = 443) -> Tuple[bool, Optional[float]]:
        """Отправляет тестовый QUIC Initial пакет и замеряет RTT."""
        if self.quic_probe_fn is not None:
            return self.quic_probe_fn(host, port)

        from dpi_classifier import make_quic_initial_packet
        try:
            ip = socket.gethostbyname(host)
            pkt = make_quic_initial_packet(host)
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.settimeout(self.timeout)
            t0 = time.time()
            s.sendto(pkt, (ip, port))
            # Ожидаем ответный пакет Version Negotiation или Handshake
            s.recvfrom(2048)
            dt = round((time.time() - t0) * 1000, 1)
            s.close()
            return True, dt
        except socket.timeout:
            return False, None
        except Exception:
            return False, None

    def probe_tcp(self, host: str, port: int = 443) -> Tuple[bool, Optional[float]]:
        """Проверяет TCP 443."""
        if self.tcp_probe_fn is not None:
            return self.tcp_probe_fn(host, port)

        try:
            ip = socket.gethostbyname(host)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self.timeout)
            t0 = time.time()
            s.connect((ip, port))
            dt = round((time.time() - t0) * 1000, 1)
            s.close()
            return True, dt
        except Exception:
            return False, None

    def analyze(self, domain: str) -> QuicVerdict:
        """Сравнивает QUIC и TCP, выдает вердикт и цену отказа от QUIC."""
        domain = domain.strip().lower()
        quic_ok, quic_rtt = self.probe_quic(domain, 443)
        tcp_ok, tcp_rtt = self.probe_tcp(domain, 443)

        penalty = None
        if quic_ok and tcp_ok and quic_rtt is not None and tcp_rtt is not None:
            penalty = round(tcp_rtt - quic_rtt, 1)

        # Сценарии
        if not quic_ok and tcp_ok:
            verdict_text = "QUIC (UDP 443) заблокирован ТСПУ (Blackhole). TCP доступен."
            recommendation = (
                "Рекомендуется включить «Блокировку QUIC» в настройках zapret. "
                "Браузеры мгновенно переключатся на TCP без ожидания таймаутов (2–3 сек)."
            )
            price_of_refusal = (
                "Нулевая: QUIC все равно заглушен оператором. "
                "Отказ от QUIC устранит зависания видео (YouTube/Discord) при старте."
            )
        elif quic_ok and tcp_ok:
            verdict_text = "QUIC и TCP работают без помех."
            recommendation = "Блокировать QUIC не требуется."
            if penalty is not None and penalty > 10:
                price_of_refusal = (
                    f"При отказе от QUIC соединение станет медленнее на ~{penalty} мс (RTT TCP выше, чем у UDP)."
                )
            else:
                price_of_refusal = "Минимальная разница: задержки QUIC и TCP сопоставимы."
        elif quic_ok and not tcp_ok:
            verdict_text = "QUIC доступен, но TCP 443 заблокирован."
            recommendation = "Ни в коем случае не отключайте QUIC: через него сайт продолжает работать!"
            price_of_refusal = "Критическая: отказ от QUIC полностью лишит доступа к сайту."
        else:
            verdict_text = "И QUIC, и TCP недоступны для данного ресурса."
            recommendation = "Ресурс заблокирован на уровне IP или доменного фильтра."
            price_of_refusal = "Не применимо: оба протокола не отвечают."

        return QuicVerdict(
            domain=domain,
            quic_available=quic_ok,
            quic_rtt_ms=quic_rtt,
            tcp_available=tcp_ok,
            tcp_rtt_ms=tcp_rtt,
            penalty_ms=penalty,
            verdict_text=verdict_text,
            recommendation=recommendation,
            price_of_refusal=price_of_refusal,
        )
