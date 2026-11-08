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
    author: Optional[str] = None
    stability: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None

    def matches_search(self, query: str) -> bool:
        """Case-insensitive substring search across id, family, author, description and tags."""
        q = query.strip().casefold()
        if not q:
            return True
        return (
            q in self.id.casefold()
            or q in self.family.casefold()
            or q in self.display_name.casefold()
            or (self.author and q in self.author.casefold())
            or (self.description and q in self.description.casefold())
            or any(q in t.casefold() for t in self.tags)
        )


_STRATEGY_META_CACHE: Dict[str, dict] = {}


def _get_strategy_metadata_map() -> Dict[str, dict]:
    """Loads and caches strategy metadata from system/strategy_catalogs."""
    global _STRATEGY_META_CACHE
    if _STRATEGY_META_CACHE:
        return _STRATEGY_META_CACHE

    res: Dict[str, dict] = {}
    app_root = Path(__file__).resolve().parent.parent
    catalogs_dir = app_root / "system" / "strategy_catalogs"

    if catalogs_dir.is_dir():
        for engine in ("winws2", "winws1"):
            edir = catalogs_dir / engine
            if not edir.is_dir():
                continue
            for cfile in edir.glob("*.txt"):
                try:
                    content = cfile.read_text(encoding="utf-8-sig", errors="ignore")
                    current_sec = None
                    sec_data = {}
                    for line in content.splitlines():
                        line = line.strip()
                        if line.startswith("[") and line.endswith("]"):
                            if current_sec and sec_data:
                                _index_strategy_meta(res, current_sec, sec_data, engine)
                            current_sec = line[1:-1].strip()
                            sec_data = {}
                        elif current_sec and "=" in line and not line.startswith(("--", "#")):
                            k, _, v = line.partition("=")
                            k = k.strip().lower()
                            v = v.strip()
                            if k in ("name", "old_name", "author", "label", "stability", "description"):
                                sec_data[k] = v
                    if current_sec and sec_data:
                        _index_strategy_meta(res, current_sec, sec_data, engine)
                except Exception:
                    pass

    _STRATEGY_META_CACHE = res
    return _STRATEGY_META_CACHE


def _index_strategy_meta(target_map: Dict[str, dict], section_id: str, data: dict, engine: str):
    author = data.get("author") or ("Flowseal" if "flowseal" in section_id.lower() else None)
    stability = data.get("label") or data.get("stability")
    description = data.get("description")
    source = f"strategy_catalogs/{engine}"

    entry_data = {
        "author": author,
        "stability": stability,
        "description": description,
        "source": source,
    }

    # Index by clean keys
    target_map[section_id.casefold()] = entry_data
    if "name" in data:
        target_map[data["name"].casefold()] = entry_data
        # also normalized without dots / badges
        norm_name = re.sub(r"[·\(\)]", "", data["name"]).strip().casefold()
        target_map[norm_name] = entry_data
    if "old_name" in data:
        target_map[data["old_name"].casefold()] = entry_data


def parse_preset_id(filename: str, text: str = "", source_type: str = "builtin") -> PresetEntry:
    """
    Parses a preset filename into structured attributes with metadata from headers
    or system strategy catalogs.
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
    version_match = re.search(r"\s+([vV]?\d+(?:\.\d+)*(?:_\d+)?)$", clean_stem)
    if version_match:
        version = version_match.group(1)
        family = clean_stem[:version_match.start()].strip()
    else:
        version = None
        family = clean_stem

    tags_list = []
    lower_name = clean_id.casefold()
    lower_text = text.casefold() if text else ""
    if game_filter:
        tags_list.append("game")

    import zapret2_core as core
    cat = core.categorize_preset(clean_id, text)
    if cat == "circular" or "circular" in lower_name or "--lua-desync=circular" in lower_text:
        tags_list.append("circular")
    if cat in ("recommended", "top") or any(k in lower_name for k in ("general alt", "default (circular)", "fake tls auto", "hostfakesplit")):
        tags_list.append("recommended")
    if "discord" in lower_name:
        tags_list.append("discord")
    if "youtube" in lower_name or "ytdisbystro" in lower_name:
        tags_list.append("youtube")
    if "alt" in lower_name:
        tags_list.append("alt")

    # Extract metadata from file comments
    author = None
    stability = None
    description = None
    source = source_type

    if text:
        for line in text.splitlines():
            line_str = line.strip()
            if not line_str.startswith("#"):
                continue
            lower_line = line_str.lower()
            if lower_line.startswith("# author:"):
                author = line_str.split(":", 1)[1].strip() or author
            elif lower_line.startswith(("# stability:", "# label:")):
                stability = line_str.split(":", 1)[1].strip() or stability
            elif lower_line.startswith("# description:"):
                desc_val = line_str.split(":", 1)[1].strip()
                if desc_val and not desc_val.startswith("Imported from"):
                    description = desc_val
            elif lower_line.startswith("# source:"):
                source = line_str.split(":", 1)[1].strip() or source

    # If missing, enrich from strategy catalog map
    meta_map = _get_strategy_metadata_map()
    lookup_candidates = [
        lower_name,
        clean_stem.casefold(),
        family.casefold(),
        re.sub(r"\s+", "_", family.casefold()),
    ]
    for cand in lookup_candidates:
        if cand in meta_map:
            meta = meta_map[cand]
            author = author or meta.get("author")
            stability = stability or meta.get("stability")
            description = description or meta.get("description")
            source = source or meta.get("source")
            break

    # Additional heuristics for standard families
    if not author:
        if any(k in lower_name for k in ("general alt", "ytdisbystro", "fake tls auto", "bolvan")):
            author = "Flowseal / Community"
        elif "dronatar" in lower_name:
            author = "Dronatar"
        elif "loop-uh" in lower_name:
            author = "loop-uh"

    if not stability:
        if "recommended" in tags_list:
            stability = "recommended"
        elif game_filter:
            stability = "game"
        else:
            stability = "stable"

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
        author=author,
        stability=stability,
        description=description,
        source=source,
    )


def _version_sort_key(entry: PresetEntry) -> tuple:
    """
    Sort key for presets within a family:
    1. Base presets without version come first (0, ()).
    2. Versioned presets are sorted numerically by version components (e.g. 1.10.3 > 1.9.9, v3_1 > v2).
    3. Plain presets come before game-filter variants.
    """
    if not entry.version:
        ver_order = (0, ())
    else:
        nums = tuple(int(x) for x in re.findall(r"\d+", entry.version))
        ver_order = (1, nums)
    return (ver_order, entry.game_filter)


class PresetCatalog:
    """Catalog of Zapret 2 presets grouped by families and searchable."""

    def __init__(self, entries: List[PresetEntry]):
        self._entries: Dict[str, PresetEntry] = {e.id: e for e in entries}
        self._families: Dict[str, List[PresetEntry]] = {}
        for e in entries:
            self._families.setdefault(e.family, []).append(e)

        # Sort presets inside families: base first, then numerically by version
        for fam, items in self._families.items():
            items.sort(key=_version_sort_key)

    @classmethod
    def load_from_directory(cls, dir_path: Path | str, user_dir: Optional[Path | str] = None) -> PresetCatalog:
        p = Path(dir_path)
        entries = []
        seen = set()
        if p.is_dir():
            for f in sorted(p.glob("*.txt")):
                if not f.name.startswith("."):
                    text = f.read_text(encoding="utf-8-sig", errors="ignore")
                    entries.append(parse_preset_id(f.name, text=text, source_type="builtin"))
                    seen.add(f.name)
        if user_dir:
            up = Path(user_dir)
            if up.is_dir():
                for f in sorted(up.glob("*.txt")):
                    if not f.name.startswith(".") and f.name not in seen:
                        text = f.read_text(encoding="utf-8-sig", errors="ignore")
                        entries.append(parse_preset_id(f.name, text=text, source_type="user"))
                        seen.add(f.name)
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

    def get_top_recommended(self, limit: int = 4) -> List[PresetEntry]:
        """Returns top recommended canonical presets for auto-healing and quick selection."""
        priority_families = ["general ALT", "Default (circular)", "general FAKE TLS AUTO", "ALL TCP & UDP hostfakesplit"]
        results = []
        for fam in priority_families:
            items = self.get_family(fam)
            if items:
                plain_items = [it for it in items if not it.game_filter]
                chosen = plain_items[-1] if plain_items else items[-1]
                results.append(chosen)
        return results[:limit]

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
                # Prefer plain non-game-filter preset; show game filter only if family has no plain variants
                plain = [e for e in items if not e.game_filter]
                items = [(plain or items)[-1]]

            for item in items:
                if only_game_filter and not item.game_filter:
                    continue
                if only_recommended and "recommended" not in item.tags:
                    continue
                if query and not item.matches_search(query):
                    continue
                results.append(item)

        return results
