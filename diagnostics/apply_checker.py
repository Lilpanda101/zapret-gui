"""
diagnostics/apply_checker.py - Автопроверка открытия сайта после применения стратегии/пресета.
При провале диагностирует причину и предлагает альтернативную стратегию в один клик.
"""

from dataclasses import dataclass
import time
from typing import Callable, List, Optional, Tuple


@dataclass
class ApplyCheckOutcome:
    success: bool
    status_code: Optional[int]
    rtt_ms: Optional[float]
    error: Optional[str]
    suggested_preset: Optional[str]
    suggestion_reason: Optional[str]


class ApplyChecker:
    """Проверяет работоспособность сети после смены пресета."""

    # Карта переключения при типичных сбоях для nfqws и nfqws2
    FALLBACK_SUGGESTIONS = {
        "general": ("general ALT", "Высокая агрессивность TLS сплита в general ALT помогает обойти жесткий ТСПУ drop"),
        "general ALT": ("Default (circular)", "Циклический фейк обходит фильтрацию с проверкой контрольных сумм TCP"),
        "Default (circular)": ("ALL TCP & UDP hostfakesplit", "Глубокий фейксплит хостов стабилизирует как TCP, так и UDP потоки"),
        "youtube_discord": ("multidisorder", "Мультисегментный disorder устраняет сбросы стриминга"),
    }

    def __init__(
        self,
        probe_fn: Optional[Callable[[str, float], Tuple[bool, Optional[int], Optional[float], Optional[str]]]] = None,
        test_url: str = "https://rutracker.org",
        timeout: float = 3.5,
    ):
        self.probe_fn = probe_fn
        self.test_url = test_url
        self.timeout = timeout

    def check(self, current_preset: str, target_url: Optional[str] = None) -> ApplyCheckOutcome:
        """Выполняет пробу целевого ресурса и предлагает альтернативу при сбое."""
        url = target_url or self.test_url

        if self.probe_fn is not None:
            ok, st, rtt, err = self.probe_fn(url, self.timeout)
        else:
            from orchestra.targets import select_probe, Target
            probe = select_probe()
            t0 = time.time()
            try:
                res = probe(Target(key="apply_check", name="Apply Check", url=url), timeout=self.timeout)
                ok = res.ok
                st = res.status
                rtt = res.latency_ms
                err = res.error
            except Exception as exc:
                ok = False
                st = None
                rtt = None
                err = str(exc)

        if ok:
            return ApplyCheckOutcome(
                success=True,
                status_code=st or 200,
                rtt_ms=rtt,
                error=None,
                suggested_preset=None,
                suggestion_reason=None,
            )

        # Выбираем рекомендацию
        suggested, reason = self.FALLBACK_SUGGESTIONS.get(
            current_preset,
            ("Default (circular)", "Стандартная проверенная стратегия Zapret2 для нестабильных каналов")
        )

        return ApplyCheckOutcome(
            success=False,
            status_code=st,
            rtt_ms=rtt,
            error=err or "Таймаут соединения или сброс RST",
            suggested_preset=suggested,
            suggestion_reason=reason,
        )
