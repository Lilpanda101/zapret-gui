#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Canonical single source of truth for engine.sh parameters and CLI contracts.
"""

from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Mapping, Tuple

logger = logging.getLogger("zapret_gui.params")


def _as_bool(val: Any, default: bool = True) -> bool:
    """Strictly parses boolean values from bool, int, or string representations."""
    if val is None:
        return default
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        v = val.strip().lower()
        if v in ("1", "true", "yes", "y", "on", "enable", "enabled"):
            return True
        if v in ("0", "false", "no", "n", "off", "disable", "disabled"):
            return False
    return default


def _as_int(val: Any, default: int = 12, min_val: int = 1, max_val: int = 128) -> int:
    """Safely converts to int and clamps to [min_val, max_val] with warnings."""
    if val is None:
        return default
    try:
        ival = int(val)
    except (ValueError, TypeError):
        logger.warning("Invalid int parameter %r, defaulting to %d", val, default)
        return default

    if ival < min_val:
        logger.warning("conntrack_limit %d is below min %d; clamping to %d", ival, min_val, min_val)
        return min_val
    if ival > max_val:
        logger.warning("conntrack_limit %d exceeds max %d; clamping to %d", ival, max_val, max_val)
        return max_val
    return ival


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
        self.conntrack_limit = _as_int(self.conntrack_limit, default=12, min_val=1, max_val=128)

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
        """Constructs EngineParams from dictionary, strictly parsing booleans and clamping int."""
        ct = _as_int(data.get("conntrack_limit", 12), default=12, min_val=1, max_val=128)

        ai_hosts_val = data.get("enable_ai_hosts", data.get("ai_hosts"))

        return cls(
            preset=str(data.get("preset") or data.get("active_preset") or "general"),
            iface=str(data.get("iface") or data.get("active_iface") or "any"),
            dns=str(data.get("dns") or data.get("active_dns") or "cloudflare"),
            enable_ai_hosts=_as_bool(ai_hosts_val, default=True),
            enable_quic=_as_bool(data.get("enable_quic"), default=True),
            enable_discord_voice=_as_bool(data.get("enable_discord_voice"), default=True),
            conntrack_limit=ct,
            hostlist_mode=str(data.get("hostlist_mode") or "all_except_exclude"),
            engine_mode=str(data.get("engine_mode") or "nfqws2"),
            custom_params=str(data.get("custom_params") or ""),
            zapret2_preset=str(data.get("zapret2_preset") or "Default (circular)"),
            enable_youtube=_as_bool(data.get("enable_youtube"), default=True),
            enable_discord_tcp=_as_bool(data.get("enable_discord_tcp"), default=True),
            enable_general_https=_as_bool(data.get("enable_general_https"), default=True),
        )

    @classmethod
    def from_app(cls, app: Any) -> EngineParams:
        """Constructs EngineParams from Zapret2App instance."""
        return cls(
            preset=getattr(app, "active_preset", "general"),
            iface=getattr(app, "active_iface", "any"),
            dns=getattr(app, "active_dns", "cloudflare"),
            enable_ai_hosts=_as_bool(getattr(app, "enable_ai_hosts", True), default=True),
            enable_quic=_as_bool(getattr(app, "enable_quic", True), default=True),
            enable_discord_voice=_as_bool(getattr(app, "enable_discord_voice", True), default=True),
            conntrack_limit=_as_int(getattr(app, "conntrack_limit", 12), default=12, min_val=1, max_val=128),
            hostlist_mode=getattr(app, "hostlist_mode", "all_except_exclude"),
            engine_mode=getattr(app, "engine_mode", "nfqws2"),
            custom_params=getattr(app, "custom_params", ""),
            zapret2_preset=getattr(app, "zapret2_preset", "Default (circular)"),
            enable_youtube=_as_bool(getattr(app, "enable_youtube", True), default=True),
            enable_discord_tcp=_as_bool(getattr(app, "enable_discord_tcp", True), default=True),
            enable_general_https=_as_bool(getattr(app, "enable_general_https", True), default=True),
        )
