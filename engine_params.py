#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canonical single source of truth for engine.sh parameters and CLI contracts.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Tuple


@dataclass(slots=True)
class EngineParams:
    preset: str = "general"
    iface: str = "any"
    dns: str = "cloudflare"
    enable_ai_hosts: bool = True
    enable_quic: bool = True
    enable_discord_voice: bool = True
    conntrack_limit: int = 12
    hostlist_mode: str = "all_except_exclude"
    engine_mode: str = "nfqws2"
    custom_params: str = ""
    zapret2_preset: str = "Default (circular)"
    enable_youtube: bool = True
    enable_discord_tcp: bool = True
    enable_general_https: bool = True

    def __post_init__(self):
        # Protect against mistaken kernel conntrack sysctl max (e.g. 1048576)
        if not isinstance(self.conntrack_limit, int) or self.conntrack_limit > 128 or self.conntrack_limit < 1:
            self.conntrack_limit = 12

    def to_argv(self, command: str = "start") -> Tuple[str, ...]:
        """Returns the canonical 15-element argument tuple for engine.sh."""
        return (
            command,
            str(self.preset or "general"),
            str(self.iface or "any"),
            str(self.dns or "cloudflare"),
            "1" if self.enable_ai_hosts else "0",
            "1" if self.enable_quic else "0",
            "1" if self.enable_discord_voice else "0",
            str(self.conntrack_limit),
            str(self.hostlist_mode or "all_except_exclude"),
            str(self.engine_mode or "nfqws2"),
            str(self.custom_params or ""),
            str(self.zapret2_preset or "Default (circular)"),
            "1" if self.enable_youtube else "0",
            "1" if self.enable_discord_tcp else "0",
            "1" if self.enable_general_https else "0",
        )

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> EngineParams:
        """Constructs EngineParams from dictionary, supporting aliases."""
        raw_ct = data.get("conntrack_limit", 12)
        try:
            ct = int(raw_ct)
            if ct > 128 or ct < 1:
                ct = 12
        except (ValueError, TypeError):
            ct = 12

        # Support explicit False vs missing key default (True)
        voice_val = data.get("enable_discord_voice")
        if voice_val is None:
            voice_val = True
        else:
            voice_val = bool(voice_val)

        return cls(
            preset=str(data.get("preset") or data.get("active_preset") or "general"),
            iface=str(data.get("iface") or data.get("active_iface") or "any"),
            dns=str(data.get("dns") or data.get("active_dns") or "cloudflare"),
            enable_ai_hosts=bool(data.get("ai_hosts", data.get("enable_ai_hosts", True))),
            enable_quic=bool(data.get("enable_quic", True)),
            enable_discord_voice=voice_val,
            conntrack_limit=ct,
            hostlist_mode=str(data.get("hostlist_mode") or "all_except_exclude"),
            engine_mode=str(data.get("engine_mode") or "nfqws2"),
            custom_params=str(data.get("custom_params") or ""),
            zapret2_preset=str(data.get("zapret2_preset") or "Default (circular)"),
            enable_youtube=bool(data.get("enable_youtube", True)),
            enable_discord_tcp=bool(data.get("enable_discord_tcp", True)),
            enable_general_https=bool(data.get("enable_general_https", True)),
        )

    @classmethod
    def from_app(cls, app: Any) -> EngineParams:
        """Constructs EngineParams from Zapret2App instance."""
        return cls(
            preset=getattr(app, "active_preset", "general"),
            iface=getattr(app, "active_iface", "any"),
            dns=getattr(app, "active_dns", "cloudflare"),
            enable_ai_hosts=getattr(app, "enable_ai_hosts", True),
            enable_quic=getattr(app, "enable_quic", True),
            enable_discord_voice=getattr(app, "enable_discord_voice", True),
            conntrack_limit=getattr(app, "conntrack_limit", 12),
            hostlist_mode=getattr(app, "hostlist_mode", "all_except_exclude"),
            engine_mode=getattr(app, "engine_mode", "nfqws2"),
            custom_params=getattr(app, "custom_params", ""),
            zapret2_preset=getattr(app, "zapret2_preset", "Default (circular)"),
            enable_youtube=getattr(app, "enable_youtube", True),
            enable_discord_tcp=getattr(app, "enable_discord_tcp", True),
            enable_general_https=getattr(app, "enable_general_https", True),
        )
