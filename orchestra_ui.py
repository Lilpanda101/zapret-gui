#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Orchestra UI & NetworkManager Integration Module for Zapret GUI Linux.

Provides:
- NetworkManagerMonitor: D-Bus connection change tracking with fallback to /proc/net/route.
- OrchestraWidget: Modern GTK3 auto-tuning interface with live progress, per-target
  status (YouTube, Discord, RuTracker) and latency metrics, pause/resume, stop,
  apply winner, quick Top-10 and full catalog auto-tuning.
- OrchestraDialog: Modal/non-modal dialog embedding OrchestraWidget.
- create_orchestra_page: Helper function for stack page integration.
"""

from __future__ import annotations
import logging
import os
import re
import shutil
import socket
import struct
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

try:
    gi.require_version("Gio", "2.0")
    from gi.repository import Gio
    HAS_GIO = True
except Exception:
    HAS_GIO = False

try:
    import dbus
    HAS_DBUS = True
except Exception:
    HAS_DBUS = False

from orchestra.targets import Target, ProbeResult, DEFAULT_TARGETS, default_targets, http_probe
from orchestra.history import HistoryStore, RunRecord
from orchestra.orchestrator import Orchestrator, OrchestratorResult, PresetResult, TargetResult
from catalog.preset_catalog import PresetCatalog, PresetEntry

logger = logging.getLogger("zapret_orchestra_ui")


def is_display_available() -> bool:
    """Checks if a GTK display is available (useful for headless / CI environments)."""
    try:
        res = Gtk.init_check([])
        if isinstance(res, tuple):
            return bool(res[0])
        return bool(res)
    except Exception:
        return False


# ============================================================================
# Network Connection Tracking (NetworkManager D-Bus & Safe Fallback)
# ============================================================================

@dataclass(frozen=True)
class NetworkConnectionInfo:
    """Represents the active network connection state."""
    id: str = ""              # Connection name (e.g. SSID or "Wired connection 1")
    uuid: str = ""            # NetworkManager connection UUID
    conn_type: str = ""       # e.g. "802-11-wireless", "802-3-ethernet"
    ssid: str = ""            # Wi-Fi SSID if applicable
    gateway: str = ""         # Default IPv4 gateway (e.g. "192.168.1.1")
    interface: str = ""       # Network interface name (e.g. "wlan0", "enp5s0")
    is_connected: bool = False

    def summary(self) -> str:
        """Returns a user-friendly summary of the active connection."""
        name = self.ssid or self.id
        parts = []
        if name:
            parts.append(name)
        if self.interface:
            parts.append(f"({self.interface})")
        if self.gateway:
            parts.append(f"шлюз: {self.gateway}")
        return " ".join(parts) if parts else "Нет подключения"


def read_proc_net_route(route_file: str = "/proc/net/route") -> Tuple[str, str]:
    """
    Parses /proc/net/route for the default IPv4 gateway.
    Returns (interface, gateway_ip). If not found, returns ("", "").
    """
    try:
        if not os.path.isfile(route_file):
            return "", ""
        with open(route_file, "r", encoding="utf-8") as f:
            lines = f.readlines()
        for line in lines[1:]:
            parts = line.strip().split()
            if len(parts) >= 3 and parts[1] == "00000000":
                iface = parts[0]
                hex_gw = parts[2]
                if len(hex_gw) == 8:
                    b = bytes.fromhex(hex_gw)
                    # /proc/net/route stores IPv4 in little-endian order
                    gw_ip = f"{b[3]}.{b[2]}.{b[1]}.{b[0]}"
                    return iface, gw_ip
    except Exception as exc:
        logger.debug("Failed reading %s: %s", route_file, exc)
    return "", ""


def get_wifi_ssid_fallback(iface: str = "") -> str:
    """Attempts to read Wi-Fi SSID via iwgetid CLI as fallback."""
    try:
        if shutil.which("iwgetid") is None and not os.environ.get("PYTEST_CURRENT_TEST"):
            return ""
        cmd = ["iwgetid", "-r"]
        if iface:
            cmd.append(iface)
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=1.0)
        if res.returncode == 0:
            return res.stdout.strip()
    except Exception:
        pass
    return ""


class NetworkManagerMonitor:
    """
    Monitors network changes via NetworkManager D-Bus with safe fallback.
    Detects changes in SSID, connection UUID, default gateway, or network interface.
    """

    def __init__(
        self,
        on_network_changed: Optional[Callable[[NetworkConnectionInfo, NetworkConnectionInfo], None]] = None,
        poll_interval_s: int = 5,
        route_file: str = "/proc/net/route",
    ):
        self.on_network_changed = on_network_changed
        self.poll_interval_s = max(1, poll_interval_s)
        self.route_file = route_file
        self.current_connection: Optional[NetworkConnectionInfo] = None
        self._monitoring = False
        self._timer_id: Optional[int] = None
        self._dbus_proxy: Optional[Any] = None
        self._prop_handler_id: Optional[int] = None

        # Initialize current state
        self.current_connection = self.get_active_connection()

    def get_active_connection(self) -> NetworkConnectionInfo:
        """
        Attempts to read connection info from NetworkManager D-Bus;
        if D-Bus is unavailable or fails, falls back to /proc/net/route.
        """
        info = None
        if HAS_GIO:
            info = self._get_gio_nm_connection()
        elif HAS_DBUS:
            info = self._get_dbus_nm_connection()

        if info is None or not info.is_connected:
            fallback = self._get_fallback_connection()
            if fallback.is_connected or info is None:
                info = fallback

        return info

    def _get_gio_nm_connection(self) -> Optional[NetworkConnectionInfo]:
        """Queries NetworkManager via Gio.DBusProxy."""
        try:
            bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
            nm_proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.NetworkManager",
                "/org/freedesktop/NetworkManager",
                "org.freedesktop.NetworkManager",
                None,
            )
            primary_val = nm_proxy.get_cached_property("PrimaryConnection")
            primary_path = primary_val.unpack() if primary_val else None

            if not primary_path or primary_path == "/":
                return NetworkConnectionInfo(is_connected=False)

            conn_proxy = Gio.DBusProxy.new_sync(
                bus,
                Gio.DBusProxyFlags.NONE,
                None,
                "org.freedesktop.NetworkManager",
                primary_path,
                "org.freedesktop.NetworkManager.Connection.Active",
                None,
            )

            id_val = conn_proxy.get_cached_property("Id")
            uuid_val = conn_proxy.get_cached_property("Uuid")
            type_val = conn_proxy.get_cached_property("Type")
            devs_val = conn_proxy.get_cached_property("Devices")
            ip4_val = conn_proxy.get_cached_property("Ip4Config")

            conn_id = id_val.unpack() if id_val else ""
            conn_uuid = uuid_val.unpack() if uuid_val else ""
            conn_type = type_val.unpack() if type_val else ""
            devices = devs_val.unpack() if devs_val else []
            ip4_path = ip4_val.unpack() if ip4_val else "/"

            iface = ""
            if devices:
                dev_proxy = Gio.DBusProxy.new_sync(
                    bus,
                    Gio.DBusProxyFlags.NONE,
                    None,
                    "org.freedesktop.NetworkManager",
                    devices[0],
                    "org.freedesktop.NetworkManager.Device",
                    None,
                )
                iface_val = dev_proxy.get_cached_property("Interface")
                iface = iface_val.unpack() if iface_val else ""

            gateway = ""
            if ip4_path and ip4_path != "/":
                ip4_proxy = Gio.DBusProxy.new_sync(
                    bus,
                    Gio.DBusProxyFlags.NONE,
                    None,
                    "org.freedesktop.NetworkManager",
                    ip4_path,
                    "org.freedesktop.NetworkManager.IP4Config",
                    None,
                )
                gw_val = ip4_proxy.get_cached_property("Gateway")
                gateway = gw_val.unpack() if gw_val else ""

            ssid = conn_id if "wireless" in conn_type.casefold() else ""

            return NetworkConnectionInfo(
                id=conn_id,
                uuid=conn_uuid,
                conn_type=conn_type,
                ssid=ssid,
                gateway=gateway,
                interface=iface,
                is_connected=bool(conn_id or gateway or iface),
            )
        except Exception as exc:
            logger.debug("Gio DBus NM query failed: %s", exc)
            return None

    def _get_dbus_nm_connection(self) -> Optional[NetworkConnectionInfo]:
        """Queries NetworkManager via dbus-python."""
        try:
            bus = dbus.SystemBus()
            nm = bus.get_object("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager")
            props = dbus.Interface(nm, "org.freedesktop.DBus.Properties")
            primary_path = props.Get("org.freedesktop.NetworkManager", "PrimaryConnection")

            if not primary_path or primary_path == "/":
                return NetworkConnectionInfo(is_connected=False)

            conn = bus.get_object("org.freedesktop.NetworkManager", primary_path)
            conn_props = dbus.Interface(conn, "org.freedesktop.DBus.Properties")
            all_props = conn_props.GetAll("org.freedesktop.NetworkManager.Connection.Active")

            conn_id = str(all_props.get("Id", ""))
            conn_uuid = str(all_props.get("Uuid", ""))
            conn_type = str(all_props.get("Type", ""))
            devs = all_props.get("Devices", [])
            ip4_path = str(all_props.get("Ip4Config", "/"))

            iface = ""
            if devs:
                dev = bus.get_object("org.freedesktop.NetworkManager", devs[0])
                dev_props = dbus.Interface(dev, "org.freedesktop.DBus.Properties")
                iface = str(dev_props.Get("org.freedesktop.NetworkManager.Device", "Interface"))

            gateway = ""
            if ip4_path and ip4_path != "/":
                ip4 = bus.get_object("org.freedesktop.NetworkManager", ip4_path)
                ip4_props = dbus.Interface(ip4, "org.freedesktop.DBus.Properties")
                gateway = str(ip4_props.Get("org.freedesktop.NetworkManager.IP4Config", "Gateway"))

            ssid = conn_id if "wireless" in conn_type.casefold() else ""

            return NetworkConnectionInfo(
                id=conn_id,
                uuid=conn_uuid,
                conn_type=conn_type,
                ssid=ssid,
                gateway=gateway,
                interface=iface,
                is_connected=bool(conn_id or gateway or iface),
            )
        except Exception as exc:
            logger.debug("dbus-python NM query failed: %s", exc)
            return None

    def _get_fallback_connection(self) -> NetworkConnectionInfo:
        """Fallback reading default gateway from /proc/net/route and interface."""
        iface, gateway = read_proc_net_route(self.route_file)
        ssid = get_wifi_ssid_fallback(iface) if iface else ""
        is_conn = bool(iface or gateway)
        conn_id = ssid or (f"Интерфейс {iface}" if iface else "")
        return NetworkConnectionInfo(
            id=conn_id,
            uuid="",
            conn_type="802-11-wireless" if ssid else ("802-3-ethernet" if iface else ""),
            ssid=ssid,
            gateway=gateway,
            interface=iface,
            is_connected=is_conn,
        )

    def has_changed(self, old: Optional[NetworkConnectionInfo], new: Optional[NetworkConnectionInfo]) -> bool:
        """Determines if the active network connection has meaningfully changed."""
        if old is None or new is None:
            return False
        if old.is_connected != new.is_connected:
            return True
        if old.ssid and new.ssid and old.ssid != new.ssid:
            return True
        if old.uuid and new.uuid and old.uuid != new.uuid:
            return True
        if old.gateway and new.gateway and old.gateway != new.gateway:
            return True
        if old.interface and new.interface and old.interface != new.interface:
            return True
        if old.id and new.id and old.id != new.id and not (old.ssid or new.ssid):
            return True
        return False

    def check_for_change(self) -> Optional[Tuple[NetworkConnectionInfo, NetworkConnectionInfo]]:
        """
        Polls current connection and compares with previous state.
        If changed, updates self.current_connection and triggers callback.
        """
        new_conn = self.get_active_connection()
        old_conn = self.current_connection
        if old_conn is not None and self.has_changed(old_conn, new_conn):
            self.current_connection = new_conn
            if self.on_network_changed:
                try:
                    self.on_network_changed(old_conn, new_conn)
                except Exception as exc:
                    logger.error("Network change callback error: %s", exc)
            return old_conn, new_conn
        self.current_connection = new_conn
        return None

    def start_monitoring(self, callback: Optional[Callable[[NetworkConnectionInfo, NetworkConnectionInfo], None]] = None) -> None:
        """Starts monitoring network changes via D-Bus properties and polling timer."""
        if callback:
            self.on_network_changed = callback

        if self._monitoring:
            return

        self._monitoring = True

        # 1. Connect Gio DBus signal if available
        if HAS_GIO:
            try:
                bus = Gio.bus_get_sync(Gio.BusType.SYSTEM, None)
                self._dbus_proxy = Gio.DBusProxy.new_sync(
                    bus,
                    Gio.DBusProxyFlags.NONE,
                    None,
                    "org.freedesktop.NetworkManager",
                    "/org/freedesktop/NetworkManager",
                    "org.freedesktop.NetworkManager",
                    None,
                )
                self._prop_handler_id = self._dbus_proxy.connect(
                    "g-properties-changed",
                    self._on_gio_properties_changed,
                )
            except Exception as exc:
                logger.debug("Failed subscribing to Gio DBus signals: %s", exc)

        # 2. Start polling timer as periodic check and safe fallback
        self._timer_id = GLib.timeout_add_seconds(self.poll_interval_s, self._on_poll_timer)

    def _on_gio_properties_changed(self, proxy: Any, changed_props: Any, invalidated_props: Any) -> None:
        """Handles D-Bus properties change signal from NetworkManager."""
        self.check_for_change()

    def _on_poll_timer(self) -> bool:
        """Timer callback for polling network connection changes."""
        if not self._monitoring:
            return False
        self.check_for_change()
        return True

    def stop_monitoring(self) -> None:
        """Stops network monitoring and releases resources."""
        self._monitoring = False
        if self._timer_id is not None:
            GLib.source_remove(self._timer_id)
            self._timer_id = None
        if self._dbus_proxy and self._prop_handler_id:
            try:
                self._dbus_proxy.disconnect(self._prop_handler_id)
            except Exception:
                pass
            self._prop_handler_id = None
            self._dbus_proxy = None


# ============================================================================
# Helpers: Preset Selection & Formatting
# ============================================================================

def get_top_recommended_presets(catalog: Optional[PresetCatalog], limit: int = 10) -> List[str]:
    """
    Returns the top recommended presets (up to limit) for quick auto-tuning.
    Combines canonical top recommended presets with additional recommended entries.
    """
    if catalog is None:
        return []

    results: List[str] = []

    # 1. Primary canonical recommended presets
    canonical = catalog.get_top_recommended(limit=limit)
    for entry in canonical:
        if entry.id not in results:
            results.append(entry.id)

    # 2. If fewer than limit, add other recommended presets (latest per family)
    if len(results) < limit:
        all_rec = catalog.filter(only_recommended=True, only_latest_per_family=True)
        for entry in all_rec:
            if entry.id not in results:
                results.append(entry.id)
                if len(results) >= limit:
                    break

    # 3. If still fewer than limit, add latest per family
    if len(results) < limit:
        all_latest = catalog.filter(only_latest_per_family=True)
        for entry in all_latest:
            if entry.id not in results:
                results.append(entry.id)
                if len(results) >= limit:
                    break

    return results[:limit]


def get_all_catalog_presets(catalog: Optional[PresetCatalog]) -> List[str]:
    """Returns all preset IDs available in the catalog."""
    if catalog is None:
        return []
    return [e.id for e in catalog.all_presets()]


def format_target_status(target_res: Optional[TargetResult]) -> str:
    """Formats TargetResult into a clean status string (e.g. '✓ 45 ms' or '✗ Сбой')."""
    if target_res is None:
        return "—"
    if target_res.stable:
        return f"✓ {target_res.avg_latency_ms} ms"
    elif target_res.successes > 0:
        return f"⚠ {target_res.avg_latency_ms} ms"
    return "✗ Сбой"


def extract_target_metrics(per_target: Tuple[TargetResult, ...]) -> Tuple[str, str, str]:
    """
    Extracts status strings for (YouTube, Discord, RuTracker) targets from per_target results.
    """
    t_map = {t.target_key: t for t in per_target or ()}
    yt = t_map.get("youtube") or t_map.get("googlevideo")
    dc = t_map.get("discord")
    rt = t_map.get("rutracker")
    return format_target_status(yt), format_target_status(dc), format_target_status(rt)


def clear_history_store(history_store: Optional[HistoryStore]) -> bool:
    """Safely removes or truncates the history store file."""
    if history_store and hasattr(history_store, "path"):
        try:
            path = Path(history_store.path)
            if path.exists():
                path.unlink()
            return True
        except Exception as exc:
            logger.error("Failed clearing history store: %s", exc)
    return False


# ============================================================================
# GTK3 UI: OrchestraWidget
# ============================================================================

class OrchestraWidget(Gtk.Box):
    """
    GTK3 Widget for automated preset testing, scoring, and applying winners.
    Includes network change alert banner, live progress bar, tested presets table,
    and control buttons (quick top-10, full catalog, pause/resume, stop, apply).
    """

    def __init__(
        self,
        app: Optional[Any] = None,
        catalog: Optional[PresetCatalog] = None,
        apply_preset: Optional[Callable[[str], Any]] = None,
        probe: Optional[Callable[[Target], Any]] = None,
        targets: Optional[List[Target]] = None,
        history: Optional[HistoryStore] = None,
        network_monitor: Optional[NetworkManagerMonitor] = None,
        settle_s: float = 0.5,
    ):
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        self.app = app
        self.catalog = catalog or self._load_default_catalog()
        self.apply_preset_fn = apply_preset or self._default_apply_preset
        self.probe_fn = probe or http_probe
        self.targets = targets or default_targets()
        self.history_store = history or HistoryStore(
            Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "zapret-gui" / "orchestra_history.jsonl"
        )
        self.settle_s = settle_s

        self.orchestrator: Optional[Orchestrator] = None
        self.latest_result: Optional[OrchestratorResult] = None
        self.is_running: bool = False
        self._worker_thread: Optional[threading.Thread] = None

        # Network monitor
        self.network_monitor = network_monitor or NetworkManagerMonitor(
            on_network_changed=self.on_network_changed
        )
        if not network_monitor:
            self.network_monitor.start_monitoring(self.on_network_changed)

        self._build_ui()

    def _load_default_catalog(self) -> Optional[PresetCatalog]:
        """Loads default presets catalog if available."""
        base_dir = Path(__file__).resolve().parent
        presets_dir = base_dir / "zapret2" / "presets" / "winws2_builtin"
        if presets_dir.is_dir():
            try:
                return PresetCatalog.load_from_directory(presets_dir)
            except Exception as exc:
                logger.debug("Failed loading default PresetCatalog: %s", exc)
        return None

    def _default_apply_preset(self, preset_id: str) -> bool:
        """Default preset application invoking app engine methods if available."""
        if self.app:
            try:
                if hasattr(self.app, "apply_orchestra_preset"):
                    return bool(self.app.apply_orchestra_preset(preset_id))
                if hasattr(self.app, "zapret2_preset"):
                    self.app.zapret2_preset = preset_id
                if hasattr(self.app, "engine_mode"):
                    self.app.engine_mode = "nfqws2"
                if hasattr(self.app, "start_engine"):
                    self.app.start_engine()
                return True
            except Exception as exc:
                logger.error("Failed to apply preset via app: %s", exc)
                return False
        return True

    def _build_ui(self) -> None:
        """Constructs all UI components."""
        self.get_style_context().add_class("content-wrapper")

        # 1. Header
        header_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        lbl_title = Gtk.Label(label="Автоподбор пресетов (Orchestra)", xalign=0)
        lbl_title.get_style_context().add_class("page-title")
        lbl_sub = Gtk.Label(
            label="Автоматический подбор и ранжирование пресетов обхода DPI по доступности ключевых сервисов и минимальной задержке.",
            xalign=0,
        )
        lbl_sub.get_style_context().add_class("page-subtitle")
        header_box.pack_start(lbl_title, False, False, 0)
        header_box.pack_start(lbl_sub, False, False, 0)
        self.pack_start(header_box, False, False, 0)

        # 2. Network Change Alert Banner (hidden by default)
        self.network_banner_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.network_banner_box.get_style_context().add_class("fluent-card")
        self.network_banner_box.set_no_show_all(True)
        self.network_banner_box.set_visible(False)

        self.lbl_net_notice = Gtk.Label(label="", xalign=0, wrap=True)
        self.lbl_net_notice.set_hexpand(True)
        self.network_banner_box.pack_start(self.lbl_net_notice, True, True, 0)

        btn_net_quick = Gtk.Button(label="⚡ Быстрый автоподбор")
        btn_net_quick.get_style_context().add_class("fluent-btn-primary")
        btn_net_quick.connect("clicked", lambda _: self._on_net_banner_quick())
        self.network_banner_box.pack_start(btn_net_quick, False, False, 0)

        btn_net_clear = Gtk.Button(label="🗑 Сбросить кэш")
        btn_net_clear.get_style_context().add_class("fluent-btn-secondary")
        btn_net_clear.connect("clicked", lambda _: self._on_net_banner_clear())
        self.network_banner_box.pack_start(btn_net_clear, False, False, 0)

        btn_net_close = Gtk.Button(label="✕")
        btn_net_close.get_style_context().add_class("fluent-btn-secondary")
        btn_net_close.connect("clicked", lambda _: self.network_banner_box.set_visible(False))
        self.network_banner_box.pack_start(btn_net_close, False, False, 0)

        self.pack_start(self.network_banner_box, False, False, 0)

        # 3. Control Action Bar Card
        controls_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        controls_card.get_style_context().add_class("fluent-card")

        self.btn_run = Gtk.Button(label="▶ Запустить автоподбор")
        self.btn_run.get_style_context().add_class("fluent-btn-primary")
        self.btn_run.set_tooltip_text("Запустить автоподбор с рекомендуемыми пресетами")
        self.btn_run.connect("clicked", lambda _: self.start_quick_autotune())
        controls_card.pack_start(self.btn_run, False, False, 0)

        self.btn_quick = Gtk.Button(label="⚡ Быстрый (Top-10)")
        self.btn_quick.get_style_context().add_class("fluent-btn-secondary")
        self.btn_quick.set_tooltip_text("Быстрый подбор среди 10 лучших проверенных пресетов")
        self.btn_quick.connect("clicked", lambda _: self.start_quick_autotune())
        controls_card.pack_start(self.btn_quick, False, False, 0)

        self.btn_full = Gtk.Button(label="🔍 Полный каталог")
        self.btn_full.get_style_context().add_class("fluent-btn-secondary")
        self.btn_full.set_tooltip_text("Полный перебор всех пресетов каталога")
        self.btn_full.connect("clicked", lambda _: self.start_full_autotune())
        controls_card.pack_start(self.btn_full, False, False, 0)

        self.btn_pause_resume = Gtk.Button(label="⏸ Пауза")
        self.btn_pause_resume.get_style_context().add_class("fluent-btn-secondary")
        self.btn_pause_resume.set_sensitive(False)
        self.btn_pause_resume.connect("clicked", lambda _: self.toggle_pause())
        controls_card.pack_start(self.btn_pause_resume, False, False, 0)

        self.btn_stop = Gtk.Button(label="⏹ Остановить")
        self.btn_stop.get_style_context().add_class("fluent-btn-danger")
        self.btn_stop.set_sensitive(False)
        self.btn_stop.connect("clicked", lambda _: self.stop_autotune())
        controls_card.pack_start(self.btn_stop, False, False, 0)

        # Spacer
        spacer = Gtk.Box()
        spacer.set_hexpand(True)
        controls_card.pack_start(spacer, True, True, 0)

        self.btn_apply_winner = Gtk.Button(label="🏆 Применить победителя")
        self.btn_apply_winner.get_style_context().add_class("fluent-btn-primary")
        self.btn_apply_winner.set_sensitive(False)
        self.btn_apply_winner.connect("clicked", lambda _: self.apply_winner())
        controls_card.pack_start(self.btn_apply_winner, False, False, 0)

        self.btn_clear_cache = Gtk.Button(label="🗑 Сбросить кэш")
        self.btn_clear_cache.get_style_context().add_class("fluent-btn-secondary")
        self.btn_clear_cache.set_tooltip_text("Очистить историю и кэш предыдущих автоподборов")
        self.btn_clear_cache.connect("clicked", lambda _: self.reset_cache())
        controls_card.pack_start(self.btn_clear_cache, False, False, 0)

        self.pack_start(controls_card, False, False, 0)

        # 4. Status & Progress Card
        progress_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        progress_card.get_style_context().add_class("fluent-card")

        status_top_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        self.lbl_status = Gtk.Label(label="<b>Готов к запуску автоподбора</b>", use_markup=True, xalign=0)
        self.lbl_progress_fraction = Gtk.Label(label="0 из 0 (0%)", xalign=1)
        self.lbl_progress_fraction.get_style_context().add_class("page-subtitle")
        status_top_box.pack_start(self.lbl_status, True, True, 0)
        status_top_box.pack_end(self.lbl_progress_fraction, False, False, 0)
        progress_card.pack_start(status_top_box, False, False, 0)

        self.progress_bar = Gtk.ProgressBar()
        self.progress_bar.set_fraction(0.0)
        self.progress_bar.set_show_text(False)
        progress_card.pack_start(self.progress_bar, False, False, 0)

        status_bottom_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.lbl_current_preset = Gtk.Label(label="Текущий пресет: —", xalign=0)
        self.lbl_current_preset.get_style_context().add_class("page-subtitle")
        self.lbl_winner = Gtk.Label(label="Лидер: —", xalign=1)
        self.lbl_winner.get_style_context().add_class("page-subtitle")
        status_bottom_box.pack_start(self.lbl_current_preset, True, True, 0)
        status_bottom_box.pack_end(self.lbl_winner, False, False, 0)
        progress_card.pack_start(status_bottom_box, False, False, 0)

        self.pack_start(progress_card, False, False, 0)

        # 5. Tested Presets Table Card
        table_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        table_card.get_style_context().add_class("fluent-card")
        table_card.set_vexpand(True)

        lbl_table = Gtk.Label(label="<b>Проверенные пресеты</b>", use_markup=True, xalign=0)
        table_card.pack_start(lbl_table, False, False, 0)

        # ListStore columns:
        # 0: Preset Display Name (str)
        # 1: YouTube Status (str)
        # 2: Discord Status (str)
        # 3: RuTracker Status (str)
        # 4: Average Latency (str)
        # 5: Targets OK (str)
        # 6: Verdict / Status (str)
        # 7: Raw Preset ID (str)
        # 8: Score (int, for sorting)
        self.list_store = Gtk.ListStore(str, str, str, str, str, str, str, str, int)

        self.tree_view = Gtk.TreeView(model=self.list_store)
        self.tree_view.set_headers_visible(True)

        columns_def = [
            ("Пресет", 0, 0.0),
            ("YouTube", 1, 0.5),
            ("Discord", 2, 0.5),
            ("RuTracker", 3, 0.5),
            ("Latency", 4, 0.5),
            ("Успех", 5, 0.5),
            ("Статус", 6, 0.5),
        ]

        for col_idx, (col_title, model_idx, align) in enumerate(columns_def):
            renderer = Gtk.CellRendererText()
            renderer.set_property("xalign", align)
            column = Gtk.TreeViewColumn(col_title, renderer, text=model_idx)
            column.set_resizable(True)
            column.set_sort_column_id(model_idx)
            self.tree_view.append_column(column)

        scrolled_table = Gtk.ScrolledWindow()
        scrolled_table.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
        scrolled_table.set_min_content_height(240)
        scrolled_table.add(self.tree_view)
        table_card.pack_start(scrolled_table, True, True, 0)

        self.pack_start(table_card, True, True, 0)

    # ------------------------------------------------------------------------
    # Network Change Event Handlers
    # ------------------------------------------------------------------------

    def on_network_changed(self, old_conn: NetworkConnectionInfo, new_conn: NetworkConnectionInfo) -> None:
        """Callback invoked when NetworkManagerMonitor detects network alteration."""
        GLib.idle_add(self._show_network_change_alert, old_conn, new_conn)

    def _show_network_change_alert(self, old_conn: NetworkConnectionInfo, new_conn: NetworkConnectionInfo) -> None:
        """Updates and displays the network change notification banner."""
        summary = new_conn.summary()
        self.lbl_net_notice.set_markup(
            f"🔔 <b>Обнаружена смена сети:</b> {GLib.markup_escape_text(summary)}. "
            "Для максимальной скорости и стабильности рекомендуется запустить повторный автоподбор пресетов."
        )
        self.network_banner_box.set_visible(True)

    def _on_net_banner_quick(self) -> None:
        """Handles 'Быстрый автоподбор' button inside the network banner."""
        self.network_banner_box.set_visible(False)
        self.start_quick_autotune()

    def _on_net_banner_clear(self) -> None:
        """Handles 'Сбросить кэш' button inside the network banner."""
        self.network_banner_box.set_visible(False)
        self.reset_cache()

    # ------------------------------------------------------------------------
    # Autotune Execution & Threading
    # ------------------------------------------------------------------------

    def start_quick_autotune(self) -> None:
        """Starts auto-tuning with the Top-10 recommended presets."""
        candidates = get_top_recommended_presets(self.catalog, limit=10)
        if not candidates and self.catalog:
            candidates = get_all_catalog_presets(self.catalog)[:10]
        self.start_autotune(candidates)

    def start_full_autotune(self) -> None:
        """Starts auto-tuning with all presets from the catalog."""
        candidates = get_all_catalog_presets(self.catalog)
        self.start_autotune(candidates)

    def start_autotune(self, candidates: Optional[List[str]] = None) -> None:
        """
        Initiates preset testing for the given candidates list in a background thread.
        """
        if self.is_running:
            return

        candidates_list = list(candidates or [])
        if not candidates_list:
            if self.catalog:
                candidates_list = get_top_recommended_presets(self.catalog, limit=10)

        if not candidates_list:
            self.lbl_status.set_markup("<span color='#e53935'><b>Ошибка: список пресетов пуст!</b></span>")
            return

        self.is_running = True
        self.latest_result = None

        # Reset UI controls
        self.btn_run.set_sensitive(False)
        self.btn_quick.set_sensitive(False)
        self.btn_full.set_sensitive(False)
        self.btn_pause_resume.set_sensitive(True)
        self.btn_pause_resume.set_label("⏸ Пауза")
        self.btn_stop.set_sensitive(True)
        self.btn_apply_winner.set_sensitive(False)
        self.btn_clear_cache.set_sensitive(False)

        self.list_store.clear()
        self.progress_bar.set_fraction(0.0)
        self.lbl_status.set_markup("<b>Тестирование пресетов...</b>")
        self.lbl_progress_fraction.set_text(f"0 из {len(candidates_list)} (0%)")
        self.lbl_current_preset.set_text("Текущий пресет: подготовка...")
        self.lbl_winner.set_text("Лидер: —")

        self.orchestrator = Orchestrator(
            apply_preset=self.apply_preset_fn,
            probe=self.probe_fn,
            targets=self.targets,
            settle_s=self.settle_s,
            history=self.history_store,
            on_progress=self._on_orchestrator_progress,
        )

        prev_preset = getattr(self.app, "zapret2_preset", None)

        self._worker_thread = threading.Thread(
            target=self._run_orchestrator_worker,
            args=(candidates_list, prev_preset),
            daemon=True,
        )
        self._worker_thread.start()

    def _run_orchestrator_worker(self, candidates: List[str], prev_preset: Optional[str]) -> None:
        """Worker thread entry point."""
        try:
            result = self.orchestrator.run(candidates, previous_preset=prev_preset)
            GLib.idle_add(self._on_autotune_finished, result)
        except Exception as exc:
            logger.error("Orchestrator worker failed: %s", exc)
            GLib.idle_add(self._on_autotune_error, str(exc))

    def _on_orchestrator_progress(self, index: int, total: int, preset_id: str, best: Optional[PresetResult]) -> None:
        """Progress callback invoked by Orchestrator after each candidate is evaluated."""
        # Find the latest tested PresetResult
        latest_preset_result = None
        if self.orchestrator and self.orchestrator.results:
            latest_preset_result = self.orchestrator.results[-1]

        GLib.idle_add(self._update_progress_ui, index, total, preset_id, best, latest_preset_result)

    def _update_progress_ui(
        self,
        index: int,
        total: int,
        preset_id: str,
        best: Optional[PresetResult],
        preset_result: Optional[PresetResult],
    ) -> None:
        """Dispatches progress updates into the GTK UI."""
        fraction = (index / total) if total > 0 else 0.0
        pct = int(fraction * 100)
        self.progress_bar.set_fraction(fraction)
        self.lbl_progress_fraction.set_text(f"{index} из {total} ({pct}%)")
        self.lbl_current_preset.set_text(f"Текущий пресет: {preset_id}")

        if best and best.ok_count > 0:
            self.lbl_winner.set_text(f"Лидер: {best.preset_id} ({best.ok_count}/{best.total_targets}, {best.avg_latency_ms} ms)")

        if preset_result is not None:
            yt_str, dc_str, rt_str = extract_target_metrics(preset_result.per_target)
            lat_str = f"{preset_result.avg_latency_ms} ms" if preset_result.avg_latency_ms < 9000 else "—"
            targets_ok = f"{preset_result.ok_count} / {preset_result.total_targets}"

            is_best = (best is not None and preset_result.preset_id == best.preset_id and best.ok_count > 0)
            if is_best:
                verdict = "🏆 Лидер"
            elif preset_result.ok_count > 0:
                verdict = "✓ Работает"
            elif preset_result.error:
                verdict = f"✗ Ошибка: {preset_result.error[:18]}"
            else:
                verdict = "✗ Сбой"

            score = (preset_result.ok_count * 10000) - preset_result.avg_latency_ms

            # Append row to TreeView ListStore
            self.list_store.append([
                preset_id,
                yt_str,
                dc_str,
                rt_str,
                lat_str,
                targets_ok,
                verdict,
                preset_id,
                score,
            ])

    def toggle_pause(self) -> None:
        """Toggles between paused and active states during testing."""
        if not self.orchestrator:
            return

        if self.orchestrator.is_paused:
            self.orchestrator.resume()
            self.btn_pause_resume.set_label("⏸ Пауза")
            self.lbl_status.set_markup("<b>Тестирование пресетов (возобновлено)...</b>")
        else:
            self.orchestrator.pause()
            self.btn_pause_resume.set_label("▶ Продолжить")
            self.lbl_status.set_markup("<b>Автоподбор приостановлен (Пауза)</b>")

    def stop_autotune(self) -> None:
        """Requests orchestrator termination."""
        if self.orchestrator:
            self.orchestrator.stop()
            self.lbl_status.set_markup("<b>Остановка автоподбора...</b>")
            self.btn_stop.set_sensitive(False)
            self.btn_pause_resume.set_sensitive(False)

    def _on_autotune_finished(self, result: OrchestratorResult) -> None:
        """Invoked on the main thread when auto-tuning is done."""
        self.is_running = False
        self.latest_result = result

        # Restore controls
        self.btn_run.set_sensitive(True)
        self.btn_quick.set_sensitive(True)
        self.btn_full.set_sensitive(True)
        self.btn_pause_resume.set_sensitive(False)
        self.btn_pause_resume.set_label("⏸ Пауза")
        self.btn_stop.set_sensitive(False)
        self.btn_clear_cache.set_sensitive(True)

        # Ensure all results from the run are represented in list_store
        existing_pids = {row[7] for row in self.list_store}
        for preset_res in (result.results or []):
            if preset_res.preset_id not in existing_pids:
                yt_str, dc_str, rt_str = extract_target_metrics(preset_res.per_target)
                lat_str = f"{preset_res.avg_latency_ms} ms" if preset_res.avg_latency_ms < 9000 else "—"
                targets_ok = f"{preset_res.ok_count} / {preset_res.total_targets}"
                verdict = "✓ Работает" if preset_res.ok_count > 0 else "✗ Сбой"
                score = (preset_res.ok_count * 10000) - preset_res.avg_latency_ms
                self.list_store.append([
                    preset_res.preset_id,
                    yt_str,
                    dc_str,
                    rt_str,
                    lat_str,
                    targets_ok,
                    verdict,
                    preset_res.preset_id,
                    score,
                ])
                existing_pids.add(preset_res.preset_id)

        if result.winner:
            self.btn_apply_winner.set_sensitive(True)
            self.btn_apply_winner.set_label(f"🏆 Применить: {result.winner}")
            self.lbl_status.set_markup(f"<span color='#2e7d32'><b>Автоподбор завершён! Победитель: {result.winner}</b></span>")
            self.lbl_winner.set_text(f"Победитель: {result.winner} ({result.best.ok_count}/{result.best.total_targets})")
            # Update row in ListStore for winner
            for row in self.list_store:
                if row[7] == result.winner:
                    row[6] = "🏆 Победитель"
        elif result.stopped:
            self.btn_apply_winner.set_sensitive(False)
            self.lbl_status.set_markup("<span color='#f57c00'><b>Автоподбор остановлен пользователем</b></span>")
        else:
            self.btn_apply_winner.set_sensitive(False)
            self.lbl_status.set_markup("<span color='#e53935'><b>Все пресеты провалили проверку</b></span>")

    def _on_autotune_error(self, err_msg: str) -> None:
        """Handles runtime errors during worker execution."""
        self.is_running = False
        self.btn_run.set_sensitive(True)
        self.btn_quick.set_sensitive(True)
        self.btn_full.set_sensitive(True)
        self.btn_pause_resume.set_sensitive(False)
        self.btn_stop.set_sensitive(False)
        self.btn_clear_cache.set_sensitive(True)
        self.lbl_status.set_markup(f"<span color='#e53935'><b>Ошибка: {GLib.markup_escape_text(err_msg)}</b></span>")

    def apply_winner(self) -> bool:
        """Applies the winning preset to the app engine."""
        if not self.latest_result or not self.latest_result.winner:
            return False

        winner_id = self.latest_result.winner
        ok = self.apply_preset_fn(winner_id)
        if ok:
            if self.app and hasattr(self.app, "on_orchestra_winner_applied"):
                try:
                    self.app.on_orchestra_winner_applied(winner_id)
                except Exception as exc:
                    logger.error("Failed to notify app of winner preset: %s", exc)
            self.lbl_status.set_markup(f"<span color='#2e7d32'><b>Пресет '{winner_id}' успешно применён!</b></span>")
        else:
            self.lbl_status.set_markup(f"<span color='#e53935'><b>Не удалось применить пресет '{winner_id}'</b></span>")
        return bool(ok)

    def reset_cache(self) -> None:
        """Clears the history store and resets UI results."""
        if self.is_running:
            return

        clear_history_store(self.history_store)
        self.list_store.clear()
        self.latest_result = None
        self.progress_bar.set_fraction(0.0)
        self.lbl_progress_fraction.set_text("0 из 0 (0%)")
        self.lbl_status.set_markup("<b>Кэш результатов успешно сброшен</b>")
        self.lbl_current_preset.set_text("Текущий пресет: —")
        self.lbl_winner.set_text("Лидер: —")
        self.btn_apply_winner.set_sensitive(False)
        self.btn_apply_winner.set_label("🏆 Применить победителя")


# ============================================================================
# Dialog & Page Factory
# ============================================================================

class OrchestraDialog(Gtk.Dialog):
    """Modal/modeless dialog hosting the OrchestraWidget."""

    def __init__(self, parent_window: Optional[Gtk.Window] = None, **kwargs: Any):
        super().__init__(
            title="Автоподбор пресетов — Zapret Orchestra",
            transient_for=parent_window,
            flags=0,
        )
        self.set_default_size(900, 640)
        self.orchestra_widget = OrchestraWidget(**kwargs)
        box = self.get_content_area()
        box.pack_start(self.orchestra_widget, True, True, 0)
        self.add_button("Закрыть", Gtk.ResponseType.CLOSE)
        self.connect("response", lambda d, r: d.destroy())
        self.show_all()


def create_orchestra_page(app: Optional[Any] = None, **kwargs: Any) -> Tuple[Gtk.ScrolledWindow, OrchestraWidget]:
    """
    Creates an embeddable page container with OrchestraWidget suitable for Gtk.Stack.
    Returns (scrolled_window, orchestra_widget).
    """
    widget = OrchestraWidget(app=app, **kwargs)
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)
    scrolled.add(widget)
    return scrolled, widget
