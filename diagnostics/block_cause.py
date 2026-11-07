"""
diagnostics/block_cause.py - Определение причин блокировки: сбор (collect) и чистый вывод (judge).
По архитектуре оригинального zapretgui (diagnostics/block_cause.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re
import socket
import ssl
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

__all__ = [
    "NEUTRAL_NAME",
    "ALLOWED_NAMES",
    "STAGGER_S",
    "HELLO_OK",
    "HELLO_ALERT",
    "HELLO_RESET",
    "HELLO_TIMEOUT",
    "HELLO_CONNECT",
    "HELLO_CANCELLED",
    "CauseFacts",
    "CauseVerdict",
    "case_variant",
    "is_reply_window_proven",
    "judge_cause",
]

NEUTRAL_NAME = "example.com"
ALLOWED_NAMES = ("max.ru", "ya.ru", "vk.com")
STAGGER_S = 0.25

HELLO_OK = "ok"
HELLO_ALERT = "alert"
HELLO_RESET = "reset"
HELLO_TIMEOUT = "timeout"
HELLO_CONNECT = "connect"
HELLO_CANCELLED = "cancelled"

SMALL_WINDOW_BYTES = 1
CONTROL_WINDOW_BYTES = 1024


def case_variant(name: str) -> str:
    """То же имя другими буквами: последняя часть заглавными («googlevideo.COM»).

    Имена сайтов регистр не различают, и сервер ответит на оба написания одинаково.
    Если одно проходит, а другое нет, их различает фильтр: он ищет имя буква в букву.
    """
    head, dot, tail = str(name or "").rpartition(".")
    if not dot or not head or not tail.isascii() or not any(c.isalpha() for c in tail):
        return ""
    flipped = tail.upper() if tail != tail.upper() else tail.lower()
    return f"{head}.{flipped}"


@dataclass(frozen=True)
class HelloResult:
    kind: str
    rtt_ms: Optional[float] = None
    data_len: int = 0

    @property
    def answered(self) -> bool:
        return self.kind in (HELLO_OK, HELLO_ALERT)


@dataclass(frozen=True)
class HttpFacts:
    status: Optional[int] = None
    location: str = ""
    body: str = ""


@dataclass(frozen=True)
class CauseFacts:
    """Факты, собранные сетевыми пробами."""

    host: str
    ip: str
    # Проба с настоящим именем
    real_hello: HelloResult
    # Проба с посторонним именем (example.com)
    neutral_hello: HelloResult
    # Проба без SNI
    nameless_hello: HelloResult
    # Проба с разрешёнными именами (max.ru, ya.ru, vk.com)
    allowed_hellos: Dict[str, HelloResult] = field(default_factory=dict)
    # Проба с тем же именем другим регистром
    recased_name: str = ""
    recased_hello: Optional[HelloResult] = None
    # HTTP 80
    http: Optional[HttpFacts] = None
    # ICMP ping
    ping_ok: Optional[bool] = None
    # Окно приёма 1 байт (две попытки) и контроль 1 КБ
    small_window_1: Optional[HelloResult] = None
    small_window_2: Optional[HelloResult] = None
    window_control: Optional[HelloResult] = None


@dataclass(frozen=True)
class CauseVerdict:
    cause_code: str
    proof: str
    recommendation: str
    confident: bool = False


def is_reply_window_proven(
    small_1: Optional[HelloResult],
    small_2: Optional[HelloResult],
    control: Optional[HelloResult],
) -> bool:
    """Малое окно 1 байт ответило дважды подряд, а окно в 1 КБ оборвали или заглушили."""
    return bool(
        small_1 and small_1.answered
        and small_2 and small_2.answered
        and control and control.kind in (HELLO_RESET, HELLO_TIMEOUT)
    )


def judge_cause(facts: CauseFacts) -> CauseVerdict:
    """
    Чистая функция принятия решения над фактами CauseFacts без сетевых вызовов.
    """
    # 1. HTTP 80: заглушка провайдера или 451
    if facts.http is not None:
        if facts.http.status == 451:
            return CauseVerdict(
                cause_code="HTTP_BLOCKPAGE",
                proof="HTTP 80 вернул статус 451 (Unavailable For Legal Reasons): официальная блокировка реестра",
                recommendation="Используйте HTTPS или desync для HTTP (модуль tpws/nfqws)",
                confident=True,
            )
        loc = facts.http.location.lower()
        body = facts.http.body.lower()
        if any(sig in loc or sig in body for sig in ("rkn.gov.ru", "zapret", "blocked", "warning.rt.ru", "blackhole")):
            return CauseVerdict(
                cause_code="HTTP_BLOCKPAGE",
                proof=f"HTTP 80 перенаправляет на страницу заглушки: {facts.http.location or 'сигнатура РКН'}",
                recommendation="Используйте защищенное HTTPS соединение или десинхронизацию HTTP заголовков",
                confident=True,
            )

    # 2. Проверка окна ответа (wssize)
    if is_reply_window_proven(facts.small_window_1, facts.small_window_2, facts.window_control):
        return CauseVerdict(
            cause_code="TLS_REPLY_WINDOW",
            proof=(
                "С окном 1 байт начало ответа сервера получено дважды, а с окном 1 КБ соединение оборвано: "
                "фильтр режет TLS по первым байтам ответа сервера в пределах окна приёма"
            ),
            recommendation="Примените модификацию окна TCP (параметр wssize в nfqws/winws2)",
            confident=True,
        )

    # 3. Разрешённые имена (режим «белых списков»)
    allowed_answered = [name for name, res in facts.allowed_hellos.items() if res.answered]
    if allowed_answered and not facts.real_hello.answered and not facts.neutral_hello.answered:
        winner = allowed_answered[0]
        return CauseVerdict(
            cause_code="WHITELIST_RESTRICTION",
            proof=(
                f"К этому адресу проходят только разрешённые имена: с именем {winner} сервер отвечает, "
                f"а с {facts.host} и посторонним {NEUTRAL_NAME} соединение сброшено"
            ),
            recommendation="Связь ограничена белыми списками провайдера; требуется внешний туннель или прокси",
            confident=True,
        )

    # 4. Другой регистр SNI (case_variant)
    if (
        facts.recased_hello is not None
        and facts.recased_hello.answered
        and not facts.real_hello.answered
    ):
        return CauseVerdict(
            cause_code="TLS_SNI_DROP",
            proof=(
                f"С оригинальным именем {facts.host} соединение оборвано, но проходит с изменённым регистром "
                f"{facts.recased_name}: фильтр ищет имя сайта строго буква в букву"
            ),
            recommendation="Используйте изменение регистра SNI (модуль tls_sni case или faker)",
            confident=True,
        )

    # 5. Постороннее имя или без имени проходит -> блокировка строго по имени (SNI)
    if not facts.real_hello.answered and (facts.neutral_hello.answered or facts.nameless_hello.answered):
        helper = NEUTRAL_NAME if facts.neutral_hello.answered else "без SNI"
        return CauseVerdict(
            cause_code="TLS_SNI_DROP",
            proof=(
                f"С именем сайта {facts.host} соединение сброшено, тогда как проба {helper} успешно ответила: "
                "фильтр блокирует целевой домен по полю TLS SNI"
            ),
            recommendation="Примените сплит TLS ClientHello (split, multidisorder, fakesplit)",
            confident=True,
        )

    # 6. Если реальное соединение успешно прошло
    if facts.real_hello.answered:
        return CauseVerdict(
            cause_code="PASS",
            proof="TLS рукопожатие с целевым адресом и оригинальным SNI успешно завершено",
            recommendation="Обход блокировок не требуется",
            confident=True,
        )

    # 7. Ни одно имя не прошло
    if facts.ping_ok is False and facts.real_hello.kind == HELLO_TIMEOUT:
        return CauseVerdict(
            cause_code="IP_BLOCK",
            proof="Адрес не отвечает ни на пинг, ни на TCP/TLS запросы: полная блокировка маршрута к IP",
            recommendation="ТСПУ глушит весь IP-адрес; требуется альтернативный IP или VPN/прокси",
            confident=True,
        )

    return CauseVerdict(
        cause_code="UNKNOWN",
        proof="Характер блокировки неоднозначен: ни одно имя не ответило, сброс происходит на уровне адреса или сервера",
        recommendation="Запустите полный перебор Blockcheck2",
        confident=False,
    )
