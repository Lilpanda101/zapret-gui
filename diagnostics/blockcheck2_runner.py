"""
diagnostics/blockcheck2_runner.py - Надежный запуск и разбор Blockcheck2 (/opt/zapret2/blockcheck2.sh).
- Запуск с таймаутом и контролем returncode
- Частичный лог при превышении таймаута
- Разбор найденных стратегий из stdout
- Обязательное восстановление DNS и параметров движка в блоке finally
- Честный статус «Тест не завершен» вместо ложного успеха
"""

from dataclasses import dataclass, field
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple


@dataclass
class BlockCheck2Result:
    completed: bool
    returncode: int
    output: str
    discovered_strategies: List[str] = field(default_factory=list)
    timeout_hit: bool = False
    status_summary: str = ""
    restore_error: str = ""


class BlockCheck2Runner:
    """Управляет жизненным циклом выполнения глубокого тестирования BlockCheck2."""

    def __init__(
        self,
        run_engine_fn: Callable[..., Any],
        engine_was_running: bool,
        engine_restore_args: Tuple[Any, ...],
        active_iface: str = "any",
        active_dns: str = "cloudflare",
        timeout_s: int = 900,
    ):
        self.run_engine = run_engine_fn
        self.was_running = engine_was_running
        self.restore_args = engine_restore_args
        self.active_iface = active_iface
        self.active_dns = active_dns
        self.timeout_s = timeout_s

    def parse_strategies(self, text: str) -> List[str]:
        """Парсит рекомендованные параметры запуска nfqws/nfqws2 из вывода blockcheck."""
        found = []
        for line in text.splitlines():
            # Поиск строк вида: - AVAILABLE: --dpi-desync=... или * working:
            if "--dpi-desync" in line or "--wf-tcp" in line or "working:" in line.lower():
                cleaned = line.strip()
                if cleaned not in found:
                    found.append(cleaned)
        return found

    def run(self, domain: str) -> BlockCheck2Result:
        domain = domain.strip() or "rutracker.org"
        output_chunks = []
        returncode = -1
        timeout_hit = False
        restore_error = ""

        try:
            # 1. Если движок был запущен - останавливаем для чистоты теста
            if self.was_running:
                stopped = self.run_engine("stop", self.active_iface)
                if getattr(stopped, "returncode", 0) != 0:
                    err = getattr(stopped, "stderr", "") or getattr(stopped, "stdout", "")
                    raise RuntimeError(f"Не удалось остановить движок перед тестом:\n{err}")

            # 2. Запуск blockcheck2 через engine.sh
            res = self.run_engine("blockcheck2", domain, self.active_iface, self.active_dns)
            returncode = getattr(res, "returncode", -1)
            stdout = getattr(res, "stdout", "")
            stderr = getattr(res, "stderr", "")
            raw_output = (stdout + "\n" + stderr).strip()

            if returncode == 124:
                timeout_hit = True
                status_summary = "Тест не завершен: лимит времени 15 минут исчерпан (частичный лог)"
                output_chunks.append("ВНИМАНИЕ: лимит времени 15 минут исчерпан. Перебор стратегий не завершён.\n")
                output_chunks.append(raw_output)
            elif returncode == 0:
                status_summary = "Blockcheck2 успешно завершен"
                output_chunks.append(raw_output)
            else:
                status_summary = f"Тест не завершен: ошибка выполнения (код {returncode})"
                output_chunks.append(f"ОШИБКА: Blockcheck2 завершился с кодом {returncode}.\n")
                output_chunks.append(raw_output)

        except Exception as exc:
            returncode = -1
            status_summary = f"Тест не завершен: исключение при запуске ({exc})"
            output_chunks.append(f"ОШИБКА ЗАПУСКА BLOCKCHECK2:\n{exc}")

        finally:
            # 3. ВСЕГДА восстанавливаем состояние системы
            if self.was_running:
                try:
                    restored = self.run_engine(*self.restore_args)
                    if getattr(restored, "returncode", 0) != 0:
                        err = getattr(restored, "stderr", "") or getattr(restored, "stdout", "")
                        restore_error = f"\n\nОШИБКА ВОССТАНОВЛЕНИЯ ДВИЖКА:\n{err}"
                except Exception as exc:
                    restore_error = f"\n\nОШИБКА ВОССТАНОВЛЕНИЯ ДВИЖКА:\n{exc}"
            else:
                # Движок не был запущен -> обязательно восстанавливаем системный DNS
                try:
                    self.run_engine("dns", self.active_iface, "system")
                except Exception:
                    pass

        full_output = "\n".join(output_chunks)
        strategies = self.parse_strategies(full_output)

        return BlockCheck2Result(
            completed=(returncode == 0 and not timeout_hit),
            returncode=returncode,
            output=full_output,
            discovered_strategies=strategies,
            timeout_hit=timeout_hit,
            status_summary=status_summary,
            restore_error=restore_error,
        )
