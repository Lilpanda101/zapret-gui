#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
orchestra/learning.py - Circular Learning System for Zapret Orchestra on Linux.

Implements adaptive strategy learning without copying winws2 Lua:
- Separate stats storage (JSON/JSONL) isolated from general app settings.
- Strategy lock on target/group after 3 consecutive successes.
- Strategy unlock after 2 consecutive failures.
- Ignored targets handling (e.g. Telegram Proxy relays).
- Automatic subdomain grouping (e.g. *.googlevideo.com -> googlevideo.com).
- Russian white domains filter: *.ru, *.su, *.рф and major RU portals are never intercepted.
- Export of learned strategies into a dedicated user learned preset without touching built-in presets/.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
from pathlib import Path
import tempfile
import time
from typing import Dict, List, Optional, Set, Tuple


RUSSIAN_WHITE_TLDS = (".ru", ".su", ".xn--p1ai")

RUSSIAN_WHITE_DOMAINS = {
    "vk.com",
    "ya.ru",
    "yandex.ru",
    "mail.ru",
    "ok.ru",
    "dzen.ru",
    "gosuslugi.ru",
    "mos.ru",
    "sberbank.ru",
    "tbank.ru",
    "tinkoff.ru",
    "kinopoisk.ru",
    "ozon.ru",
    "wildberries.ru",
    "avito.ru",
    "max.ru",
    "rutube.ru",
    "habr.com",
}

DEFAULT_IGNORED_TARGETS = {
    "web.telegram.org",
    "vesta.web.telegram.org",
    "zws4.web.telegram.org",
    "vesta-1.web.telegram.org",
    "venus-1.web.telegram.org",
    "venus.web.telegram.org",
    "kws2-1.web.telegram.org",
    "kws2.web.telegram.org",
    "kws4-1.web.telegram.org",
    "kws4.web.telegram.org",
    "zws2-1.web.telegram.org",
    "zws2.web.telegram.org",
    "zws4-1.web.telegram.org",
    "core.telegram.org",
    "api.telegram.org",
    "my.telegram.org",
    "td.telegram.org",
}

KNOWN_SERVICE_GROUPS = {
    "googlevideo.com": "googlevideo.com",
    "youtube.com": "youtube.com",
    "youtu.be": "youtube.com",
    "ytimg.com": "youtube.com",
    "ggpht.com": "youtube.com",
    "discord.gg": "discord.com",
    "discordapp.com": "discord.com",
    "discordapp.net": "discord.com",
    "discord.media": "discord.com",
    "discord.com": "discord.com",
    "rutracker.org": "rutracker.org",
}


def is_russian_white_domain(domain_or_url: str) -> bool:
    """Returns True if domain is in Russian white-list or has a Russian TLD."""
    d = domain_or_url.strip().lower()
    if "//" in d:
        d = d.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0]
    else:
        d = d.split("/", 1)[0].split(":", 1)[0]

    if d in RUSSIAN_WHITE_DOMAINS:
        return True
    if any(d.endswith(tld) for tld in RUSSIAN_WHITE_TLDS):
        return True
    for w in RUSSIAN_WHITE_DOMAINS:
        if d.endswith("." + w):
            return True
    return False


def is_ignored_target(target_or_domain: str, custom_ignored: Optional[Set[str]] = None) -> bool:
    """Returns True if target is a relay or explicitly ignored host."""
    d = target_or_domain.strip().lower()
    if "//" in d:
        d = d.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0]
    else:
        d = d.split("/", 1)[0].split(":", 1)[0]

    if d in DEFAULT_IGNORED_TARGETS:
        return True
    if custom_ignored and d in custom_ignored:
        return True
    return False


def group_subdomains(domain_or_url: str) -> str:
    """
    Groups subdomains into their parent domain or service bucket.
    E.g. rr1---sn-xxx.googlevideo.com -> googlevideo.com
         gateway.discord.gg -> discord.com
         sub.example.com -> example.com
    """
    d = domain_or_url.strip().lower()
    if "//" in d:
        d = d.split("//", 1)[1].split("/", 1)[0].split(":", 1)[0]
    else:
        d = d.split("/", 1)[0].split(":", 1)[0]

    for pattern, group in KNOWN_SERVICE_GROUPS.items():
        if d == pattern or d.endswith("." + pattern):
            return group

    parts = d.split(".")
    if len(parts) <= 2:
        return d
    # Handle eTLD like .co.uk, .com.ru
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "edu") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


@dataclass
class TargetStrategyStat:
    """Tracks consecutive successes and failures for strategy locking."""
    target_group: str
    strategy: str
    consecutive_successes: int = 0
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    locked: bool = False
    last_updated: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> TargetStrategyStat:
        return cls(
            target_group=str(data.get("target_group", "")),
            strategy=str(data.get("strategy", "")),
            consecutive_successes=int(data.get("consecutive_successes", 0)),
            consecutive_failures=int(data.get("consecutive_failures", 0)),
            total_successes=int(data.get("total_successes", 0)),
            total_failures=int(data.get("total_failures", 0)),
            locked=bool(data.get("locked", False)),
            last_updated=float(data.get("last_updated", 0.0) or time.time()),
        )


class LearningStore:
    """
    Adaptive circular learning manager.
    Maintains lock/unlock states, blocked strategies, and generates learned strategy mappings.
    Stored independently in a JSON file to prevent settings pollution.
    """

    LOCK_SUCCESS_THRESHOLD = 3
    UNLOCK_FAILURE_THRESHOLD = 2
    BLOCK_FAILURE_THRESHOLD = 5  # consecutive failures on target group without prior success triggers auto-block

    def __init__(
        self,
        storage_path: Path | str,
        learned_rules_path: Optional[Path | str] = None,
        learned_preset_path: Optional[Path | str] = None,
    ):
        self.storage_path = Path(storage_path)
        active_rules_path = learned_rules_path or learned_preset_path
        self.learned_rules_path = (
            Path(active_rules_path)
            if active_rules_path
            else self.storage_path.parent / "learned_rules.conf"
        )
        self.learned_preset_path = self.learned_rules_path  # backward-compatible alias
        self._stats: Dict[Tuple[str, str], TargetStrategyStat] = {}
        self._blocked: Dict[str, Set[str]] = {}  # target_group -> set of blocked strategies
        self._custom_ignored: Set[str] = set()
        self.load()

    def get_stats(self) -> Dict[Tuple[str, str], TargetStrategyStat]:
        return dict(self._stats)

    def get_locked_strategies(self) -> Dict[str, str]:
        """Returns map of {target_group: locked_strategy}."""
        locked = {}
        for (grp, strat), stat in self._stats.items():
            if stat.locked:
                locked[grp] = strat
        return locked

    def get_blocked_strategies(self, target_group: Optional[str] = None) -> Dict[str, Set[str]]:
        """Returns dict of target_group -> set of blocked strategy IDs."""
        if target_group is not None:
            grp = group_subdomains(target_group)
            return {grp: set(self._blocked.get(grp, set()))}
        return {grp: set(strats) for grp, strats in self._blocked.items()}

    def is_strategy_blocked(self, target_or_group: str, strategy: str) -> bool:
        """Checks if a strategy is prohibited for a target or target group."""
        grp = group_subdomains(target_or_group)
        return strategy in self._blocked.get(grp, set())

    def block_strategy(self, target_or_group: str, strategy: str) -> None:
        """Adds a strategy to the blocked set for a target group."""
        grp = group_subdomains(target_or_group)
        if grp not in self._blocked:
            self._blocked[grp] = set()
        self._blocked[grp].add(strategy)
        # If currently locked with this strategy, unlock it
        key = (grp, strategy)
        if key in self._stats and self._stats[key].locked:
            self._stats[key].locked = False
        self.save()

    def unblock_strategy(self, target_or_group: str, strategy: str) -> None:
        """Removes a strategy from the blocked set."""
        grp = group_subdomains(target_or_group)
        if grp in self._blocked:
            self._blocked[grp].discard(strategy)
            if not self._blocked[grp]:
                del self._blocked[grp]
        self.save()

    def record_attempt(
        self,
        target_domain: str,
        strategy: str,
        success: bool,
    ) -> Optional[TargetStrategyStat]:
        """
        Records attempt outcome for target and strategy.
        Applies lock (3 consecutive successes) or unlock (2 consecutive failures).
        Ignores white Russian domains and relay targets.
        """
        if is_russian_white_domain(target_domain):
            return None
        if is_ignored_target(target_domain, self._custom_ignored):
            return None

        grp = group_subdomains(target_domain)
        key = (grp, strategy)

        stat = self._stats.get(key)
        if stat is None:
            stat = TargetStrategyStat(target_group=grp, strategy=strategy)
            self._stats[key] = stat

        stat.last_updated = time.time()

        if success:
            stat.consecutive_successes += 1
            stat.consecutive_failures = 0
            stat.total_successes += 1

            if stat.consecutive_successes >= self.LOCK_SUCCESS_THRESHOLD:
                stat.locked = True
                # Unlock any other strategy for this same group
                for (other_grp, other_strat), other_stat in self._stats.items():
                    if other_grp == grp and other_strat != strategy and other_stat.locked:
                        other_stat.locked = False
        else:
            stat.consecutive_failures += 1
            stat.consecutive_successes = 0
            stat.total_failures += 1

            if stat.locked and stat.consecutive_failures >= self.UNLOCK_FAILURE_THRESHOLD:
                stat.locked = False

            # Auto-block strategy for this target group after reaching failure threshold
            if stat.consecutive_failures >= self.BLOCK_FAILURE_THRESHOLD and stat.total_successes == 0:
                if grp not in self._blocked:
                    self._blocked[grp] = set()
                self._blocked[grp].add(strategy)

        return stat

    def reset_learning(self) -> None:
        """
        Clears all learned locks, stats, and blocked strategies (both manual and auto-blocked).
        Preserves HistoryStore run history records!
        """
        self._stats.clear()
        self._blocked.clear()
        self._custom_ignored.clear()
        self.save()
        if self.learned_rules_path.exists():
            try:
                self.learned_rules_path.unlink()
            except OSError:
                pass

    def export_learned_rules(self, output_path: Optional[Path | str] = None) -> Path:
        """
        Exports currently locked strategies into a separate learned mapping file.
        Built-in presets/ are strictly unmodified.
        """
        target_path = Path(output_path) if output_path else self.learned_rules_path
        target_path.parent.mkdir(parents=True, exist_ok=True)

        locked = self.get_locked_strategies()
        lines = [
            "# Zapret Orchestra - Карта стратегий обучения (Target => Strategy)",
            f"# Сгенерировано: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            "# Встроенные пресеты не изменены. Данный файл содержит адаптивную карту правил для целей.",
            "",
        ]

        if not locked:
            lines.append("# На данный момент нет зафиксированных стратегий (требуется >= 3 успехов подряд).")
        else:
            for grp, strat in sorted(locked.items()):
                lines.append(f"target: {grp} => strategy: {strat}")

        content = "\n".join(lines) + "\n"
        with open(target_path, "w", encoding="utf-8") as f:
            f.write(content)

        return target_path

    export_learned_preset = export_learned_rules  # backward-compatible alias

    def load(self) -> None:
        """Loads state from JSON storage."""
        if not self.storage_path.exists():
            return

        try:
            with open(self.storage_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            stats_data = data.get("stats", [])
            self._stats = {}
            for item in stats_data:
                st = TargetStrategyStat.from_dict(item)
                self._stats[(st.target_group, st.strategy)] = st

            blocked_raw = data.get("blocked", {})
            self._blocked = {grp: set(strats) for grp, strats in blocked_raw.items()}
            self._custom_ignored = set(data.get("custom_ignored", []))
        except Exception:
            # Corrupted storage: fallback to empty state
            self._stats = {}
            self._blocked = {}
            self._custom_ignored = set()

    def save(self) -> None:
        """Atomically saves state to JSON storage."""
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)

        payload = {
            "version": 1,
            "saved_at": time.time(),
            "stats": [stat.to_dict() for stat in self._stats.values()],
            "blocked": {grp: list(strats) for grp, strats in self._blocked.items()},
            "custom_ignored": list(self._custom_ignored),
        }

        tmp_dir = self.storage_path.parent
        with tempfile.NamedTemporaryFile("w", dir=tmp_dir, delete=False, encoding="utf-8") as tf:
            json.dump(payload, tf, ensure_ascii=False, indent=2)
            tmp_name = tf.name

        os.replace(tmp_name, self.storage_path)
