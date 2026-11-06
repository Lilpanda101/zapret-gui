#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Log analyzer for zapret-gui.

Analyzes application logs, systemd journal, and engine logs to detect common incidents:
- Binding and permission errors (CAP_NET_ADMIN missing, EACCES, port conflicts)
- Conntrack table overflow and limit warnings
- nftables syntax and chain/table errors
- DNS resolution and resolv.conf failures
- nfqws and tpws process crashes and segmentation faults

Outputs structured incidents and actionable recommendations in Russian.
"""

from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

DEFAULT_LOG_PATHS: Sequence[Path] = (
    Path("/run/zapret-gui/zapret-gui.log"),
    Path("/tmp/zapret-gui.log"),
    Path("/tmp/zapret-healer.log"),
)


@dataclass
class LogIncident:
    """Structured incident detected in logs."""

    category: str
    severity: str  # "CRITICAL", "ERROR", "WARNING", "INFO"
    title: str
    description: str
    recommendation: str
    matched_lines: List[str] = field(default_factory=list)
    count: int = 1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalysisReport:
    """Comprehensive analysis report."""

    total_lines: int
    source: str
    incidents: List[LogIncident] = field(default_factory=list)

    @property
    def has_critical(self) -> bool:
        return any(i.severity == "CRITICAL" for i in self.incidents)

    @property
    def has_errors(self) -> bool:
        return any(i.severity in ("CRITICAL", "ERROR") for i in self.incidents)

    @property
    def has_warnings(self) -> bool:
        return any(i.severity == "WARNING" for i in self.incidents)

    @property
    def summary(self) -> str:
        if not self.incidents:
            return f"Анализ завершен успешно ({self.total_lines} строк). Критических ошибок и инцидентов не обнаружено."
        return (
            f"Анализ выявил {len(self.incidents)} инцидент(ов) на {self.total_lines} строк лога "
            f"(критических: {sum(1 for i in self.incidents if i.severity == 'CRITICAL')}, "
            f"ошибок: {sum(1 for i in self.incidents if i.severity == 'ERROR')}, "
            f"предупреждений: {sum(1 for i in self.incidents if i.severity == 'WARNING')})."
        )

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "total_lines": self.total_lines,
            "summary": self.summary,
            "has_critical": self.has_critical,
            "has_errors": self.has_errors,
            "has_warnings": self.has_warnings,
            "incidents": [i.to_dict() for i in self.incidents],
        }

    def format_text(self) -> str:
        """Format report into human-readable Russian text."""
        lines = [
            "=" * 60,
            "ОТЧЕТ АНАЛИЗАТОРА ЛОГОВ ZAPRET-GUI",
            "=" * 60,
            f"Источник логов: {self.source}",
            f"Всего строк обработано: {self.total_lines}",
            f"Итог: {self.summary}",
            "-" * 60,
        ]

        if not self.incidents:
            lines.append("Все сетевые подсистемы и процессы работают штатно.")
            lines.append("=" * 60)
            return "\n".join(lines)

        for idx, inc in enumerate(self.incidents, 1):
            lines.extend([
                f"[{idx}] {inc.severity}: {inc.title}",
                f"    Категория: {inc.category}",
                f"    Повторений: {inc.count}",
                f"    Описание: {inc.description}",
                f"    Рекомендация: {inc.recommendation}",
                "    Примеры строк лога:",
            ])
            for m in inc.matched_lines[:5]:
                lines.append(f"      * {m}")
            lines.append("-" * 60)

        lines.append("=" * 60)
        return "\n".join(lines)


class _IncidentPattern:
    def __init__(
        self,
        category: str,
        severity: str,
        title: str,
        description: str,
        recommendation: str,
        patterns: Sequence[str],
    ) -> None:
        self.category = category
        self.severity = severity
        self.title = title
        self.description = description
        self.recommendation = recommendation
        self.compiled = [re.compile(p, re.IGNORECASE) for p in patterns]

    def matches(self, line: str) -> bool:
        return any(c.search(line) for c in self.compiled)


PATTERNS: Sequence[_IncidentPattern] = (
    _IncidentPattern(
        category="permission_binding",
        severity="CRITICAL",
        title="Ошибка прав доступа или биндинга портов (CAP_NET_ADMIN / EACCES)",
        description=(
            "Обнаружены ошибки нехватки сетевых привилегий (CAP_NET_ADMIN / root), "
            "отказ в доступе к сокетам (Permission denied / Operation not permitted) "
            "или конфликт занятых портов (Address already in use)."
        ),
        recommendation=(
            "1. Убедитесь, что zapret-gui запущен с правами администратора (через pkexec/sudo).\n"
            "2. Выдайте необходимые capabilities бинарным файлам:\n"
            "   sudo setcap cap_net_admin,cap_net_raw+eip /path/to/nfqws\n"
            "3. Проверьте занятость портов командой: sudo ss -tulpn"
        ),
        patterns=[
            r"permission denied",
            r"cap_net_admin",
            r"operation not permitted",
            r"address already in use",
            r"cannot bind socket",
            r"failed to bind",
            r"bind\(\) failed",
            r"eacces|eperm",
            r"socket bind error",
        ],
    ),
    _IncidentPattern(
        category="conntrack_overflow",
        severity="WARNING",
        title="Переполнение таблицы отслеживания соединений (nf_conntrack overflow)",
        description=(
            "Таблица отслеживания соединений Netfilter заполнена или достигла установленного лимита. "
            "Ядро может сбрасывать входящие и исходящие пакеты."
        ),
        recommendation=(
            "1. Увеличьте размер таблицы conntrack в ядре:\n"
            "   sudo sysctl -w net.netfilter.nf_conntrack_max=262144\n"
            "2. Уменьшите параметр conntrack_limit в настройках zapret-gui."
        ),
        patterns=[
            r"nf_conntrack:\s*table\s*full",
            r"conntrack\s*table\s*(?:full|limit)",
            r"table\s*limit\s*reached",
            r"net\.netfilter\.nf_conntrack_max",
            r"conntrack.*dropping\s*packet",
        ],
    ),
    _IncidentPattern(
        category="nftables_failure",
        severity="ERROR",
        title="Сбой применения правил или конфигурации nftables",
        description=(
            "Обнаружены сбои при загрузке или модификации правил nftables: "
            "синтаксические ошибки, отсутствие таблицы/цепочки или конфликт существующих правил."
        ),
        recommendation=(
            "1. Проверьте доступность и версию пакета nftables: nft -v\n"
            "2. Очистите возможные остаточные таблицы zapret:\n"
            "   sudo nft delete table inet zapret 2>/dev/null || true\n"
            "3. Проверьте корректность синтаксиса правил в кастомных параметрах."
        ),
        patterns=[
            r"nft(?:ables)?.*syntax\s*error",
            r"syntax\s*error.*nft",
            r"error:\s*could\s*not\s*process\s*rule",
            r"table\s*already\s*exists",
            r"chain.*missing",
            r"failed\s*to\s*load\s*nftables",
            r"nftables\s*error",
            r"no\s*such\s*file\s*or\s*directory.*nft",
        ],
    ),
    _IncidentPattern(
        category="dns_failure",
        severity="WARNING",
        title="Сбой службы DNS или конфигурации resolv.conf",
        description=(
            "Обнаружены проблемы разрешения доменных имен (NXDOMAIN / SERVFAIL / REFUSED), "
            "сбои демона systemd-resolved или повреждение файла /etc/resolv.conf."
        ),
        recommendation=(
            "1. Проверьте статус локального резолвера: systemctl status systemd-resolved\n"
            "2. Проверьте целостность симлинка /etc/resolv.conf:\n"
            "   ls -la /etc/resolv.conf\n"
            "3. Переключите профиль DNS в настройках zapret-gui (например, на Cloudflare или Quad9)."
        ),
        patterns=[
            r"resolv\.conf.*(?:broken|missing|invalid|failed)",
            r"\b(?:nxdomain|servfail|refused)\b",
            r"dns\s*(?:query|lookup)\s*fail",
            r"failed\s*to\s*resolve",
            r"temporary\s*failure\s*in\s*name\s*resolution",
            r"systemd-resolved.*(?:failure|failed|timed?\s*out)",
            r"nameserver\s*unreachable",
        ],
    ),
    _IncidentPattern(
        category="process_crash",
        severity="CRITICAL",
        title="Аварийное завершение процесса nfqws/tpws (Crash / Core dump)",
        description=(
            "Рабочий процесс обхода DPI (nfqws или tpws) завершил выполнение аварийно "
            "(Segmentation fault, завершение по сигналу или сбойный код возврата)."
        ),
        recommendation=(
            "1. Убедитесь в совместимости бинарного файла zapret с вашей архитектурой процессора и ядром.\n"
            "2. Попробуйте сменить режим движка (например, с nfqws2 на классический nfqws или tpws).\n"
            "3. Проверьте корректность аргументов и параметров запуска в редакторе пресетов."
        ),
        patterns=[
            r"(?:nfqws|tpws|zapret).*(?:crashed|segmentation\s*fault|segfault|core\s*dumped|died|terminated\s*with\s*signal)",
            r"(?:nfqws|tpws)\[\d+\]:?\s*segfault",
            r"process\s*died",
            r"terminated\s*with\s*signal\s*(?:11|9|6|sigsegv|sigabrt|sigkill)",
            r"(?:nfqws|tpws).*(?:exit\s*(?:status|code)\s*[1-9]\d*)",
        ],
    ),
)


class LogAnalyzer:
    """Analyzer for inspecting zapret-gui and system network logs."""

    def __init__(self, patterns: Optional[Sequence[_IncidentPattern]] = None) -> None:
        self.patterns = patterns or PATTERNS

    @classmethod
    def get_default_log_paths(cls) -> List[Path]:
        """Return list of standard log file paths."""
        return list(DEFAULT_LOG_PATHS)

    @classmethod
    def find_existing_log_file(cls) -> Optional[Path]:
        """Find the first existing log file from the default list."""
        for path in DEFAULT_LOG_PATHS:
            if path.is_file():
                return path
        return None

    def analyze_lines(self, lines: Iterable[str], source: str = "custom") -> AnalysisReport:
        """Analyze a collection of log lines and produce a structured report."""
        line_list = [line.rstrip("\r\n") for line in lines if line.strip()]
        total_lines = len(line_list)

        matched_data: dict[str, dict] = {}

        for line in line_list:
            for pat in self.patterns:
                if pat.matches(line):
                    cat = pat.category
                    if cat not in matched_data:
                        matched_data[cat] = {
                            "pattern": pat,
                            "matched_lines": [],
                            "count": 0,
                        }
                    matched_data[cat]["count"] += 1
                    if len(matched_data[cat]["matched_lines"]) < 10:
                        matched_data[cat]["matched_lines"].append(line)

        incidents: List[LogIncident] = []
        for cat, data in matched_data.items():
            pat: _IncidentPattern = data["pattern"]
            incident = LogIncident(
                category=cat,
                severity=pat.severity,
                title=pat.title,
                description=pat.description,
                recommendation=pat.recommendation,
                matched_lines=data["matched_lines"],
                count=data["count"],
            )
            incidents.append(incident)

        # Sort incidents by severity priority: CRITICAL -> ERROR -> WARNING -> INFO
        severity_order = {"CRITICAL": 0, "ERROR": 1, "WARNING": 2, "INFO": 3}
        incidents.sort(key=lambda x: (severity_order.get(x.severity, 99), -x.count))

        return AnalysisReport(total_lines=total_lines, source=source, incidents=incidents)

    def analyze_text(self, text: str, source: str = "text") -> AnalysisReport:
        """Analyze raw text containing log output."""
        return self.analyze_lines(text.splitlines(), source=source)

    def analyze_file(
        self,
        path: Optional[os.PathLike | str] = None,
        max_bytes: int = 5 * 1024 * 1024,
    ) -> AnalysisReport:
        """Analyze a log file on disk.

        If path is omitted, attempts to find the first existing default log file.
        """
        target_path: Optional[Path] = Path(path) if path else self.find_existing_log_file()
        if not target_path or not target_path.is_file():
            source_desc = str(target_path) if target_path else "не найден"
            return AnalysisReport(
                total_lines=0,
                source=f"Файл {source_desc}",
                incidents=[],
            )

        try:
            with target_path.open("rb") as stream:
                stream.seek(0, os.SEEK_END)
                size = stream.tell()
                stream.seek(max(0, size - max_bytes))
                raw = stream.read()
            text = raw.decode("utf-8", errors="replace")
            return self.analyze_lines(text.splitlines(), source=str(target_path))
        except Exception as exc:
            incident = LogIncident(
                category="read_error",
                severity="WARNING",
                title="Не удалось прочитать файл журнала",
                description=f"Ошибка чтения файла {target_path}: {exc}",
                recommendation="Проверьте права на чтение файла журнала.",
                matched_lines=[],
                count=1,
            )
            return AnalysisReport(
                total_lines=0,
                source=str(target_path),
                incidents=[incident],
            )

    def analyze_journal(
        self,
        unit: str = "zapret-gui",
        lines: int = 500,
    ) -> AnalysisReport:
        """Fetch and analyze systemd journal logs for a specified unit."""
        source_desc = f"journalctl -u {unit} -n {lines}"
        try:
            cmd = ["journalctl", "-u", unit, "-n", str(lines), "--no-pager"]
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=5,
            )
            if res.returncode != 0 and not res.stdout:
                return AnalysisReport(
                    total_lines=0,
                    source=source_desc,
                    incidents=[],
                )
            return self.analyze_lines(res.stdout.splitlines(), source=source_desc)
        except Exception as exc:
            return AnalysisReport(
                total_lines=0,
                source=f"{source_desc} (ошибка запуска: {exc})",
                incidents=[],
            )


# Default module instance for convenience
default_analyzer = LogAnalyzer()


def analyze_log_file(path: Optional[os.PathLike | str] = None) -> AnalysisReport:
    """Convenience helper to analyze a log file."""
    return default_analyzer.analyze_file(path)


def analyze_log_text(text: str, source: str = "text") -> AnalysisReport:
    """Convenience helper to analyze text."""
    return default_analyzer.analyze_text(text, source=source)
