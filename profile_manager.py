#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Profile Templates Manager for Zapret GUI.
Loads predefined service profile templates from system/templates/all_profiles.txt
and allows overlaying service-specific profiles on top of active presets without
overwriting user manual customizations.
"""

from __future__ import annotations
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import zapret2_core as core

TEMPLATES_FILE = Path(__file__).resolve().parent / "system" / "templates" / "all_profiles.txt"


@dataclass(frozen=True)
class ServiceProfileTemplate:
    id: str
    name: str
    service: str
    category: str
    raw_text: str
    filter_tcp: Optional[str] = None
    filter_udp: Optional[str] = None
    hostlist: Optional[str] = None
    ipset: Optional[str] = None


class ProfileManager:
    """Manages service profile templates and application to presets."""

    def __init__(self, templates: List[ServiceProfileTemplate]):
        self._templates = templates
        self._by_id = {t.id: t for t in templates}
        self._by_service: Dict[str, List[ServiceProfileTemplate]] = {}
        self._by_category: Dict[str, List[ServiceProfileTemplate]] = {}

        for t in templates:
            self._by_service.setdefault(t.service, []).append(t)
            self._by_category.setdefault(t.category, []).append(t)

    @classmethod
    def load(cls, file_path: Optional[Path | str] = None) -> ProfileManager:
        path = Path(file_path) if file_path else TEMPLATES_FILE
        if not path.is_file():
            return cls([])

        content = path.read_text(encoding="utf-8-sig", errors="ignore")
        raw_sections = re.split(r"(?:^|\n)--new\b", content)

        templates: List[ServiceProfileTemplate] = []
        counter = 0

        for sec in raw_sections:
            sec_clean = sec.strip()
            if not sec_clean:
                continue

            # Skip Discord/Telegram (strict project rule)
            if "discord" in sec_clean.lower() or "telegram" in sec_clean.lower():
                continue

            name = ""
            name_match = re.search(r"^--name=(.+)$", sec_clean, re.MULTILINE)
            if name_match:
                name = name_match.group(1).strip()
            else:
                name = f"Профиль {counter + 1}"

            counter += 1
            service = cls._detect_service(name, sec_clean)
            category = cls._detect_category(name, service)

            tcp_m = re.search(r"^--filter-tcp=(.+)$", sec_clean, re.MULTILINE)
            udp_m = re.search(r"^--filter-udp=(.+)$", sec_clean, re.MULTILINE)
            hl_m = re.search(r"^--(?:hostlist|hostlist-domains)=(.+)$", sec_clean, re.MULTILINE)
            ip_m = re.search(r"^--(?:ipset|ipset-ip)=(.+)$", sec_clean, re.MULTILINE)

            t_id = f"tpl_{counter:03d}_{re.sub(r'[^a-zA-Z0-9_]+', '_', service.lower())}"

            templates.append(
                ServiceProfileTemplate(
                    id=t_id,
                    name=name,
                    service=service,
                    category=category,
                    raw_text=sec_clean,
                    filter_tcp=tcp_m.group(1).strip() if tcp_m else None,
                    filter_udp=udp_m.group(1).strip() if udp_m else None,
                    hostlist=hl_m.group(1).strip() if hl_m else None,
                    ipset=ip_m.group(1).strip() if ip_m else None,
                )
            )

        return cls(templates)

    @staticmethod
    def _detect_service(name: str, text: str) -> str:
        lower = f"{name} {text}".lower()
        if "youtube" in lower or "googlevideo" in lower or "ytimg" in lower:
            return "YouTube"
        if "twitch" in lower:
            return "Twitch"
        if "steam" in lower:
            return "Steam"
        if "roblox" in lower:
            return "Roblox"
        if "rutracker" in lower:
            return "Rutracker"
        if "rutor" in lower:
            return "Rutor"
        if "cloudflare" in lower:
            return "Cloudflare"
        if "whatsapp" in lower:
            return "WhatsApp"
        if "facebook" in lower or "instagram" in lower or "meta" in lower:
            return "Social/Meta"
        if "twitter" in lower or "x.com" in lower:
            return "Twitter/X"
        if "openai" in lower or "chatgpt" in lower or "claude" in lower or "gemini" in lower:
            return "AI / LLM"
        if "sound" in lower:
            return "SoundCloud"
        if "riot" in lower or "valorant" in lower or "league of legends" in lower:
            return "Riot Games"
        if "epic" in lower or "fortnite" in lower:
            return "Epic Games"
        return name.split("·")[0].strip() if "·" in name else (name[:24] if name else "Общий сервис")

    @staticmethod
    def _detect_category(name: str, service: str) -> str:
        s = f"{name} {service}".lower()
        if any(w in s for w in ("steam", "roblox", "riot", "game", "игра", "valorant", "fortnite", "tanki")):
            return "игры"
        if any(w in s for w in ("youtube", "video", "видео", "lordfilm", "tiktok")):
            return "видео"
        if any(w in s for w in ("twitch", "stream", "стрим", "soundcloud", "rtmps")):
            return "стриминг"
        if any(w in s for w in ("rutracker", "rutor", "торрент", "torrent")):
            return "торренты"
        return "веб"

    @property
    def total_count(self) -> int:
        return len(self._templates)

    @property
    def templates(self) -> List[ServiceProfileTemplate]:
        return self._templates

    @property
    def services(self) -> Dict[str, List[ServiceProfileTemplate]]:
        return self._by_service

    @property
    def categories(self) -> Dict[str, List[ServiceProfileTemplate]]:
        return self._by_category

    def get(self, template_id: str) -> Optional[ServiceProfileTemplate]:
        return self._by_id.get(template_id)

    def attach_to_preset_doc(
        self,
        doc: core.PresetDocument,
        template: ServiceProfileTemplate,
        strategy_lines: Optional[List[str]] = None,
    ) -> core.PresetDocument:
        """
        Overlays service template profile on top of preset document without breaking manual user settings.
        If profile with same --name exists, updates its filters; otherwise appends as new profile.
        """
        lines = list(doc.lines)
        tpl_lines = [l.strip() for l in template.raw_text.splitlines() if l.strip()]

        # Ensure strategy lines (if not present in template) are inherited from first profile
        has_strategy = any(l.startswith(("--lua-desync=", "--dpi-desync=")) for l in tpl_lines)
        if not has_strategy and strategy_lines:
            tpl_lines.extend(strategy_lines)
        elif not has_strategy and doc.profiles:
            first_prof = doc.profiles[0]
            first_text = doc.profile_text(first_prof.index)
            strat = [
                l.strip()
                for l in first_text.splitlines()
                if l.strip().startswith(("--lua-desync=", "--dpi-desync=", "--payload=", "--blob="))
            ]
            if strat:
                tpl_lines.extend(strat)

        new_profile_block = "\n--new\n" + "\n".join(tpl_lines) + "\n"
        full_text = doc.text().rstrip() + new_profile_block
        return core.PresetDocument.parse(full_text)
