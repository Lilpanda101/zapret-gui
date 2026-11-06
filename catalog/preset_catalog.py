#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Preset catalog model and normalization for Zapret 2 presets.
Ensures preset ID is strictly the immutable filename, while providing
normalized display, family grouping, and version classification.
"""

from __future__ import annotations
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass(frozen=True, slots=True)
class PresetEntry:
    id: str
    family: str
    version: Optional[str]
    game_filter: bool
    tags: Tuple[str, ...]
    display_name: str

    def matches_search(self, query: str) -> bool:
        """Case-insensitive substring search across id, family and tags."""
        q = query.strip().casefold()
        if not q:
            return True
        return (
            q in self.id.casefold()
            or q in self.family.casefold()
            or q in self.display_name.casefold()
            or any(q in t.casefold() for t in self.tags)
        )


def parse_preset_id(filename: str) -> PresetEntry:
    """
    Parses a preset filename into structured attributes without modifying the ID.
    Guarantees word-boundary separation between family and version (e.g. ALT1 vs ALT10).
    """
    clean_id = filename.strip()
    if clean_id.endswith(".txt"):
        stem = clean_id[:-4]
    else:
        stem = clean_id

    # Detect game filter flag
    game_filter = bool(re.search(r"\s*\((?:game filter|game)\)", stem, re.IGNORECASE))
    clean_stem = re.sub(r"\s*\((?:game filter|game)\)", "", stem, flags=re.IGNORECASE).strip()

    # Detect version at end of clean stem:
    # Matches: ' 1.10.3', ' 1.9.9', ' v2', ' v3_1', ' V5', etc.
    # Notice: requires leading whitespace, preserving 'ALT1' or 'ALT10' in family!
    version_match = re.search(r"\s+([vV]?\d+(?:\.\d+)*(?:_\d+)?)$", clean_stem)
    if version_match:
        version = version_match.group(1)
        family = clean_stem[:version_match.start()].strip()
    else:
        version = None
        family = clean_stem

    tags_list = []
    lower_name = clean_id.casefold()
    if game_filter:
        tags_list.append("game")
    if "circular" in lower_name:
        tags_list.append("circular")
    if "discord" in lower_name:
        tags_list.append("discord")
    if "youtube" in lower_name or "ytdisbystro" in lower_name:
        tags_list.append("youtube")
    if "alt" in lower_name:
        tags_list.append("alt")
    if any(k in lower_name for k in ("general alt", "default (circular)", "fake tls auto", "hostfakesplit")):
        tags_list.append("recommended")

    # Display name: family + version if present + [Game] badge if game_filter
    parts = [family]
    if version:
        parts.append(version)
    if game_filter:
        parts.append("🎮")
    display_name = " ".join(parts)

    return PresetEntry(
        id=clean_id if clean_id.endswith(".txt") else f"{clean_id}.txt",
        family=family,
        version=version,
        game_filter=game_filter,
        tags=tuple(tags_list),
        display_name=display_name,
    )


class PresetCatalog:
    """Catalog of Zapret 2 presets grouped by families and searchable."""

    def __init__(self, entries: List[PresetEntry]):
        self._entries: Dict[str, PresetEntry] = {e.id: e for e in entries}
        self._families: Dict[str, List[PresetEntry]] = {}
        for e in entries:
            self._families.setdefault(e.family, []).append(e)

        # Sort presets inside families: base first, then by version
        for fam, items in self._families.items():
            items.sort(key=lambda x: (x.version is not None, x.version or "", x.game_filter))

    @classmethod
    def load_from_directory(cls, dir_path: Path | str) -> PresetCatalog:
        p = Path(dir_path)
        if not p.is_dir():
            return cls([])

        files = sorted(f.name for f in p.glob("*.txt") if not f.name.startswith("."))
        entries = [parse_preset_id(f) for f in files]
        return cls(entries)

    @property
    def total_count(self) -> int:
        return len(self._entries)

    @property
    def family_count(self) -> int:
        return len(self._families)

    @property
    def families(self) -> Dict[str, List[PresetEntry]]:
        return self._families

    def all_presets(self) -> List[PresetEntry]:
        return list(self._entries.values())

    def get(self, preset_id: str) -> Optional[PresetEntry]:
        pid = preset_id.strip()
        if not pid.endswith(".txt"):
            pid = f"{pid}.txt"
        return self._entries.get(pid)

    def get_family(self, family_name: str) -> List[PresetEntry]:
        return self._families.get(family_name, [])

    def filter(
        self,
        query: str = "",
        family: Optional[str] = None,
        only_game_filter: bool = False,
        only_recommended: bool = False,
        only_latest_per_family: bool = False,
    ) -> List[PresetEntry]:
        """Filters catalog items based on criteria."""
        results = []
        target_families = [family] if family and family in self._families else list(self._families.keys())

        for fam in target_families:
            items = self._families[fam]
            if only_latest_per_family and items:
                # Last item in sorted family is latest version
                items = [items[-1]]

            for item in items:
                if only_game_filter and not item.game_filter:
                    continue
                if only_recommended and "recommended" not in item.tags:
                    continue
                if query and not item.matches_search(query):
                    continue
                results.append(item)

        return results
