#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zapret 2 GUI for Arch Linux / CachyOS.
Modern Fluent-style DPI bypass & diagnostics suite inspired by Windows Zapret 2.
"""

import os
import sys
import json
import subprocess
import threading
import time
import socket
import urllib.request
import urllib.error
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gtk, Gdk, GLib, Pango

from updater import ZapretUpdater, get_update_meta, MirrorHealthMonitor
from healer import get_healer, HEALER_LOG
from zapret2_ui import Zapret2Page
from version import __version__, APP_TITLE, APP_SUBTITLE, APP_DESCRIPTION

AppIndicator = None
try:
    gi.require_version("AyatanaAppIndicator3", "0.1")
    from gi.repository import AyatanaAppIndicator3 as AppIndicator
except Exception:
    try:
        gi.require_version("AppIndicator3", "0.1")
        from gi.repository import AppIndicator3 as AppIndicator
    except Exception:
        AppIndicator = None

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINE_SH = os.path.join(APP_DIR, "engine.sh")
LOG_FILE = "/run/zapret-gui/zapret-gui.log" if os.path.exists("/run/zapret-gui/zapret-gui.log") or os.path.isdir("/run/zapret-gui") else "/tmp/zapret-gui.log"
CONFIG_FILE = os.path.expanduser("~/.config/zapret-gui/config.json")
AUTOSTART_FILE = os.path.expanduser("~/.config/autostart/zapret-gui.desktop")


def check_installation_security() -> bool:
    """Verifies directory security in system-wide installations."""
    real_app_dir = os.path.realpath(APP_DIR)
    is_system = real_app_dir.startswith(("/usr/libexec/zapret-gui", "/usr/share/zapret-gui", "/usr/lib/zapret-gui", "/opt/zapret-gui"))
    if is_system and os.getuid() != 0:
        if os.access(real_app_dir, os.W_OK):
            print("SECURITY ERROR: System-wide directory is writable by unprivileged user! Aborting.", file=sys.stderr)
            sys.exit(1)
    return is_system


def get_network_interfaces():
    """Scans /sys/class/net/ excluding lo, returns list starting with any."""
    ifaces = ["any"]
    try:
        if os.path.exists("/sys/class/net"):
            for dev in sorted(os.listdir("/sys/class/net")):
                if dev != "lo":
                    ifaces.append(dev)
    except Exception:
        pass
    return ifaces


def run_engine(*args):
    """
    Executes engine.sh with root privileges.
    Tries passwordless sudo (sudo -n) first, and falls back to pkexec if needed.
    """
    cmd = [ENGINE_SH] + list(args)
    try:
        res = subprocess.run(["sudo", "-n"] + cmd, capture_output=True, text=True)
        # If sudo executed without asking for a password, return its result directly
        if res.returncode == 0 or not ("password is required" in res.stderr or "a terminal is required" in res.stderr or "not allowed to execute" in res.stderr):
            return res
    except Exception:
        pass
    return subprocess.run(["pkexec"] + cmd, capture_output=True, text=True)


# Modern Windows 11 Fluent Design Dark Theme CSS
FLUENT_CSS = b"""
* {
    font-family: "Segoe UI", "Inter", "Ubuntu", "Cantarell", "Noto Sans", sans-serif;
    outline: none;
}

window {
    background-color: #14141c;
    color: #f3f3f3;
}

/* Universal button reset to eliminate white background bugs */
button {
    background-image: none;
    background-color: #262636;
    color: #f0f0f5;
    border: 1px solid #38384e;
    border-radius: 7px;
    padding: 7px 16px;
    font-weight: 500;
    font-size: 13px;
    transition: all 120ms ease;
    box-shadow: none;
    text-shadow: none;
}

button:hover {
    background-color: #323247;
    border-color: #4f4f6b;
    color: #ffffff;
}

button:active {
    background-color: #1c1c28;
}

button:disabled {
    opacity: 0.55;
}

/* Switch styling - prevents stretching deformities */
switch {
    min-width: 44px;
    min-height: 22px;
    border-radius: 12px;
    background-color: #2b2b3a;
    border: 1px solid #3d3d52;
}

switch:checked {
    background-color: #0078d4;
    border-color: #60cdff;
}

switch slider {
    min-width: 16px;
    min-height: 16px;
    border-radius: 50%;
    background-color: #ffffff;
    margin: 3px;
}

/* Sidebar styling */
.fluent-sidebar {
    background-color: #101016;
    border-right: 1px solid #1f1f2c;
    padding: 12px 6px;
}

.nav-section-title {
    font-size: 10px;
    font-weight: 700;
    color: #6a6a84;
    letter-spacing: 0.6px;
    margin-top: 14px;
    margin-bottom: 2px;
    margin-left: 12px;
}

.fluent-nav-item {
    padding: 8px 12px;
    margin: 1px 4px;
    border-radius: 6px;
    font-size: 13px;
    color: #9a9ab0;
    background: transparent;
    border: none;
    box-shadow: none;
    background-image: none;
    transition: all 120ms ease;
}

.fluent-nav-item:hover {
    background-color: rgba(255, 255, 255, 0.06);
    color: #ffffff;
}

.fluent-nav-item:checked, .fluent-nav-item:active {
    background-color: #1d1d2b;
    color: #ffffff;
    font-weight: 600;
    border-left: 3px solid #60cdff;
}

/* Header & Titles */
.page-title {
    font-size: 21px;
    font-weight: 700;
    color: #ffffff;
    margin-bottom: 2px;
}

.page-subtitle {
    font-size: 12px;
    color: #8f8fa4;
    margin-bottom: 16px;
}

/* Fluent Cards */
.fluent-card {
    background-color: #1c1c28;
    border: 1px solid #28283a;
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 12px;
}

.fluent-card:hover {
    border-color: #38384f;
}

.fluent-tile {
    background-color: #232332;
    border: 1px solid #2e2e42;
    border-radius: 8px;
    padding: 12px 14px;
    transition: all 120ms ease;
}

.fluent-tile:hover {
    background-color: #28283a;
    border-color: #3b3b54;
}

.tile-title {
    font-size: 11px;
    color: #8e8ea4;
    font-weight: 600;
    margin-bottom: 4px;
}

.tile-value {
    font-size: 13px;
    font-weight: 600;
    color: #ffffff;
}

/* Metric Tiles Row (Top of Dashboard) */
.metric-tile {
    background-color: #1c1c28;
    border: 1px solid #28283a;
    border-radius: 8px;
    padding: 10px 14px;
    transition: all 120ms ease;
}

.metric-tile:hover {
    border-color: #3a3a52;
}

.metric-tile-label {
    font-size: 10px;
    font-weight: 600;
    color: #7b7b92;
    letter-spacing: 0.4px;
}

.metric-tile-val {
    font-size: 13px;
    font-weight: 600;
    color: #f0f0f5;
    margin-top: 2px;
}

/* Fluent Setting Row Card (Windows 11 Settings style) */
.fluent-setting-row {
    background-color: #1c1c28;
    border: 1px solid #28283a;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 6px;
    transition: all 120ms ease;
}

.fluent-setting-row:hover {
    border-color: #38384f;
    background-color: #20202e;
}

.setting-icon-box {
    background-color: rgba(96, 205, 255, 0.12);
    border-radius: 7px;
    padding: 6px 9px;
    margin-right: 12px;
}

/* Status Banner */
.status-banner-active {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(28, 28, 40, 0.95) 100%);
    border: 1px solid rgba(16, 185, 129, 0.55);
    border-radius: 10px;
    padding: 18px;
    box-shadow: 0 4px 20px rgba(16, 185, 129, 0.08);
}

.status-banner-inactive {
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.08) 0%, rgba(28, 28, 40, 0.95) 100%);
    border: 1px solid rgba(239, 68, 68, 0.45);
    border-radius: 10px;
    padding: 18px;
    box-shadow: 0 4px 20px rgba(239, 68, 68, 0.05);
}

/* Button Variants */
.fluent-btn-primary {
    background-image: none;
    background-color: #0078d4;
    color: #ffffff;
    border: 1px solid #1084d8;
    font-weight: 600;
    padding: 8px 20px;
    box-shadow: 0 2px 8px rgba(0, 120, 212, 0.35);
}

.fluent-btn-primary:hover {
    background-color: #1084d8;
    border-color: #2b95e0;
    box-shadow: 0 4px 14px rgba(0, 120, 212, 0.5);
}

.fluent-btn-danger {
    background-image: none;
    background-color: #c42b1c;
    color: #ffffff;
    border: 1px solid #d13438;
    font-weight: 600;
    padding: 8px 20px;
    box-shadow: 0 2px 8px rgba(196, 43, 28, 0.35);
}

.fluent-btn-danger:hover {
    background-color: #d13438;
    border-color: #ea393e;
}

.fluent-btn-secondary {
    background-image: none;
    background-color: #272738;
    color: #f0f0f5;
    border: 1px solid #3c3c54;
    border-radius: 7px;
    padding: 7px 16px;
}

.fluent-btn-secondary:hover {
    background-color: #333349;
    border-color: #525272;
    color: #ffffff;
}

/* Badges / Pills */
.badge-ok {
    background-color: rgba(16, 185, 129, 0.16);
    border: 1px solid rgba(16, 185, 129, 0.45);
    color: #34d399;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-warn {
    background-color: rgba(245, 158, 11, 0.16);
    border: 1px solid rgba(245, 158, 11, 0.45);
    color: #fbbf24;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-bad {
    background-color: rgba(239, 68, 68, 0.16);
    border: 1px solid rgba(239, 68, 68, 0.45);
    color: #f87171;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-accent {
    background-color: rgba(96, 205, 255, 0.14);
    border: 1px solid rgba(96, 205, 255, 0.4);
    color: #60cdff;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-neutral {
    background-color: rgba(160, 160, 180, 0.12);
    border: 1px solid rgba(160, 160, 180, 0.3);
    color: #c4c4d4;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

/* Logs and Text Area */
textview, textview text, .log-view, .log-view text {
    background-color: #0e0e14;
    color: #a5b4fc;
    font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", monospace;
    font-size: 12px;
}

.log-view {
    padding: 10px;
    border: 1px solid #262638;
    border-radius: 8px;
}

/* Progress bar */
progressbar trough {
    background-color: #232332;
    border: 1px solid #333346;
    border-radius: 4px;
    min-height: 8px;
}

progressbar progress {
    background-color: #0078d4;
    border-radius: 4px;
}

/* Scrolled window */
scrolledwindow viewport {
    background-color: transparent;
}

/* ComboBox */
combobox button.combo {
    background-color: #222230;
    border: 1px solid #323246;
    color: #f0f0f5;
    border-radius: 6px;
    padding: 4px 10px;
}

combobox menu {
    background-color: #1c1c28;
    border: 1px solid #323246;
    color: #f0f0f5;
}

/* Content width limiter for ultrawide screens */
.content-wrapper {
    margin: 22px 32px;
}
"""

PRESETS = {
    "general": {
        "title": "General (YouTube, Discord, Все сайты)",
        "badge": "Рекомендовано",
        "desc": "Мультистратегия fake,multidisorder с ts fooling. Обходит замедление YouTube, Discord и блокировки ТСПУ.",
        "params": "--filter-tcp=443 --dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld --dpi-desync-repeats=6 --dpi-desync-fooling=ts"
    },
    "youtube_discord": {
        "title": "YouTube & Discord Max",
        "badge": "Скорость",
        "desc": "Оптимизация для 4K/8K видеопотоков YouTube (QUIC + TCP) и голосовых шлюзов Discord (UDP).",
        "params": "--filter-tcp=443 --dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld --new --filter-udp=443 --dpi-desync=fake"
    },
    "alt_fakedsplit": {
        "title": "ALT (Ростелеком, Дом.ру)",
        "badge": "Провайдеры",
        "desc": "Стратегия fake,fakesplit с позицией split-pos=1,midsld для провайдеров со строгим ТСПУ фильтром.",
        "params": "--filter-tcp=443 --dpi-desync=fake,split2 --dpi-desync-split-pos=1,midsld --dpi-desync-repeats=6 --dpi-desync-fooling=badsum"
    },
    "alt_split": {
        "title": "ALT Split (Мегафон, Йота, МТС)",
        "badge": "Мобильные",
        "desc": "Десинхронизация через split2 с рандомизацией SNI для сотовых сетей.",
        "params": "--filter-tcp=443 --dpi-desync=fake,split2 --dpi-desync-split-pos=1,midsld --dpi-desync-fooling=ts"
    },
    "multidisorder": {
        "title": "Multi-Disorder Universal",
        "badge": "Стабильность",
        "desc": "Смешивание последовательности пакетов (disorder) для обхода DPI без отправки фейкового ClientHello.",
        "params": "--filter-tcp=443 --dpi-desync=multidisorder --dpi-desync-split-pos=1,midsld"
    },
    "game_filter": {
        "title": "Game Filter (Игровой режим)",
        "badge": "Низкий пинг",
        "desc": "Минимальная задержка: не трогает порт 80, чистый UDP для Steam, Battle.net, Riot, Discord Voice.",
        "params": "--filter-tcp=443 --dpi-desync=fake,multidisorder --filter-udp=19294-19344,50000-50100"
    },
    "custom": {
        "title": "Пользовательский пресет",
        "badge": "Эксперт",
        "desc": "Ручная настройка параметров desync и выбор собственных списков хостов.",
        "params": "--filter-tcp=443,2053,2083,2087,2096,8443 --dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld"
    }
}

DNS_SERVERS = {
    "cloudflare": {
        "title": "Cloudflare DNS (DoT 1.1.1.1)",
        "ip": "1.1.1.1#cloudflare-dns.com",
        "badge": "Быстрый",
        "desc": "DNS-over-TLS с минимальной задержкой, защитой приватности и отказом от AAAA для избежания таймаутов IPv6."
    },
    "dns_ai": {
        "title": "DNS-AI (Нейросети DoT)",
        "ip": "194.87.196.13#dns-ai.ru",
        "badge": "Разблокировка ИИ",
        "desc": "Специализированный DoT резолвер с автоматической маршрутизацией ChatGPT, Gemini, Claude, Cursor, Copilot."
    },
    "geohide": {
        "title": "Geohide DNS (Обход гео-блокировок)",
        "ip": "37.230.192.51#geohide.ru",
        "badge": "Геоблокировки",
        "desc": "Умный DoT резолвер, возвращающий незаблокированные зарубежные IP для Spotify, Canva, Notion, Figma."
    },
    "xbox": {
        "title": "Xbox / PlayStation Shecan DNS",
        "ip": "178.22.122.100#free.shecan.ir",
        "badge": "Консоли и Игры",
        "desc": "Шлюз для онлайн-сервисов Xbox Live, PlayStation Network, EA App и Ubisoft Connect без блокировок."
    },
    "quad9": {
        "title": "Quad9 (DoT 9.9.9.9)",
        "ip": "9.9.9.9#dns.quad9.net",
        "badge": "Безопасность",
        "desc": "Швейцарский DoT резолвер с автоматической блокировкой вредоносных фишинговых сайтов."
    },
    "adguard": {
        "title": "AdGuard DNS (DoT)",
        "ip": "94.140.14.14#dns.adguard-dns.com",
        "badge": "Блокировка рекламы",
        "desc": "Фильтрация трекеров и рекламных сетей на уровне DNS-запросов операционной системы."
    },
    "google": {
        "title": "Google Public DNS (DoT 8.8.8.8)",
        "ip": "8.8.8.8#dns.google",
        "badge": "Универсальный",
        "desc": "Глобальная сеть DNS-серверов Google с поддержкой шифрования DNS-over-TLS."
    },
    "system": {
        "title": "Системный DNS (NetworkManager / Провайдер)",
        "ip": "none",
        "badge": "По умолчанию",
        "desc": "Использовать стандартные DNS серверы, выданные вашим роутером или провайдером по DHCP."
    }
}


class Zapret2App(Gtk.Window):
    def __init__(self, minimized=False):
        super().__init__(title=APP_TITLE)
        self.is_system_mode = check_installation_security()
        self.set_default_size(1080, 720)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_icon_name("network-vpn")
        self.minimized = minimized

        # State
        self.active_preset = "general"
        self.active_dns = "cloudflare"
        self.active_iface = "any"
        self.enable_ai_hosts = True
        self.dpi_auto = True
        self.enable_quic = True
        self.enable_discord_voice = True
        self.conntrack_limit = 12
        self.hostlist_mode = "all_except_exclude"
        self.engine_mode = "nfqws2"
        self.zapret2_preset = "Default (circular)"
        self.zapret2_page = None
        self.custom_params = "--filter-tcp=443,2053,2083,2087,2096,8443 --dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld"
        self.enable_youtube = True
        self.enable_discord_tcp = True
        self.enable_general_https = True
        self.enable_auto_hostlist = False
        self.is_running = False
        self._syncing_ai_hosts = False
        self._syncing_iface = False
        self._syncing_quic = False
        self._syncing_autostart = False
        self._refreshing_status = False
        self.updater = ZapretUpdater(APP_DIR)
        self.mirror_monitor = MirrorHealthMonitor(self.updater)
        self.mirror_monitor.on_mirror_change = self.on_mirror_change
        self.mirror_monitor.start()
        self.healer = get_healer()
        self.healer.on_status_change = self.on_healer_status
        self.healer_enabled = True

        # Intercept window close to minimize to tray
        self.connect("delete-event", self.on_delete_event)

        # Load persisted config
        self.load_config()
        self.healer_enabled = getattr(self, 'healer_enabled', True)
        if self.healer_enabled:
            self.healer.start()

        # Load styling
        self.load_css()

        # Build UI layout
        main_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        self.add(main_box)

        # 1. Main Content Stack
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.NONE)
        self.stack.set_transition_duration(0)

        # Pages
        self.stack.add_named(self.create_dashboard_page(), "dashboard")
        self.stack.add_named(self.create_presets_page(), "presets")
        self.stack.add_named(self.create_profiles_page(), "profiles")
        self.stack.add_named(self.create_zapret2_page(), "zapret2")
        self.stack.add_named(self.create_dpi_mode_page(), "dpi_mode")
        self.stack.add_named(self.create_monitor_page(), "monitor")
        self.stack.add_named(self.create_dns_page(), "dns")
        self.stack.add_named(self.create_hosts_page(), "hosts")
        self.stack.add_named(self.create_updates_page(), "updates")
        self.stack.add_named(self.create_blockcheck_page(), "blockcheck")
        self.stack.add_named(self.create_logs_page(), "logs")
        self.stack.add_named(self.create_settings_page(), "settings")

        # 2. Left Navigation Sidebar
        self.sidebar_box = self.create_sidebar()
        main_box.pack_start(self.sidebar_box, False, False, 0)
        main_box.pack_start(self.stack, True, True, 0)

        if "dashboard" in self.nav_buttons:
            self.nav_buttons["dashboard"].set_active(True)

        # Initialize System Tray
        self.setup_tray()

        # Initial status check & auto-start if dpi_auto
        def initial_kickoff():
            try:
                result = subprocess.run([ENGINE_SH, "status"], capture_output=True, text=True, timeout=3)
                state = result.stdout.strip()
            except Exception:
                state = "INACTIVE"
            self._apply_status(state)
            if self.dpi_auto and state not in ("ACTIVE", "NFQWS_ONLY"):
                self.start_engine()
            return False

        GLib.timeout_add(1000, initial_kickoff)
        GLib.timeout_add(3000, self._on_status_timer)

    def _on_status_timer(self):
        self.refresh_status()
        return True

    def load_config(self):
        try:
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    loaded_preset = data.get("preset", self.active_preset)
                    self.active_preset = loaded_preset if loaded_preset in PRESETS else "general"
                    loaded_dns = data.get("dns", self.active_dns)
                    self.active_dns = loaded_dns if loaded_dns in DNS_SERVERS else "cloudflare"
                    self.active_iface = data.get("iface", self.active_iface)
                    self.enable_ai_hosts = data.get("ai_hosts", self.enable_ai_hosts)
                    self.dpi_auto = data.get("dpi_auto", self.dpi_auto)
                    self.enable_quic = data.get("enable_quic", self.enable_quic)
                    self.enable_discord_voice = data.get("enable_discord_voice", self.enable_discord_voice)
                    self.conntrack_limit = data.get("conntrack_limit", self.conntrack_limit)
                    self.hostlist_mode = data.get("hostlist_mode", self.hostlist_mode)
                    loaded_engine = data.get("engine_mode", self.engine_mode)
                    self.engine_mode = loaded_engine if loaded_engine in ("tpws", "nfqws", "nfqws2") else "nfqws2"
                    self.zapret2_preset = data.get("zapret2_preset", self.zapret2_preset)
                    self.custom_params = data.get("custom_params", self.custom_params)
                    self.enable_youtube = data.get("enable_youtube", self.enable_youtube)
                    self.enable_discord_tcp = data.get("enable_discord_tcp", self.enable_discord_tcp)
                    self.enable_general_https = data.get("enable_general_https", self.enable_general_https)
                    self.enable_auto_hostlist = data.get("enable_auto_hostlist", self.enable_auto_hostlist)
                    self.healer_enabled = data.get("healer_enabled", True)
                    self.minimize_to_tray = data.get("minimize_to_tray", None)
        except Exception as e:
            print("Config load error:", e)

    def save_config(self):
        try:
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            data = {
                "preset": self.active_preset,
                "dns": self.active_dns,
                "iface": self.active_iface,
                "ai_hosts": self.enable_ai_hosts,
                "dpi_auto": self.dpi_auto,
                "enable_quic": self.enable_quic,
                "enable_discord_voice": self.enable_discord_voice,
                "conntrack_limit": self.conntrack_limit,
                "hostlist_mode": self.hostlist_mode,
                "engine_mode": self.engine_mode,
                "zapret2_preset": self.zapret2_preset,
                "custom_params": self.custom_params,
                "enable_youtube": self.enable_youtube,
                "enable_discord_tcp": self.enable_discord_tcp,
                "enable_general_https": self.enable_general_https,
                "enable_auto_hostlist": getattr(self, "enable_auto_hostlist", False),
                "healer_enabled": self.healer_enabled
            }
            temporary = CONFIG_FILE + ".tmp"
            with open(temporary, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(temporary, CONFIG_FILE)
        except Exception as e:
            print("Config save error:", e)

    def load_css(self):
        provider = Gtk.CssProvider()
        provider.load_from_data(FLUENT_CSS)
        Gtk.StyleContext.add_provider_for_screen(
            Gdk.Screen.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )

    def create_page_container(self, title_text, subtitle_text):
        """Creates a scrolled page with a constrained, centered content width for ultrawide displays."""
        scrolled = Gtk.ScrolledWindow()
        scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

        outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        outer_box.set_halign(Gtk.Align.CENTER)
        outer_box.set_hexpand(True)
        outer_box.set_size_request(920, -1)
        outer_box.set_margin_top(22)
        outer_box.set_margin_bottom(24)
        outer_box.set_margin_start(32)
        outer_box.set_margin_end(32)
        outer_box.get_style_context().add_class("content-wrapper")

        t_lbl = Gtk.Label(label=title_text)
        t_lbl.get_style_context().add_class("page-title")
        t_lbl.set_xalign(0)
        outer_box.pack_start(t_lbl, False, False, 0)

        if subtitle_text:
            s_lbl = Gtk.Label(label=subtitle_text)
            s_lbl.get_style_context().add_class("page-subtitle")
            s_lbl.set_xalign(0)
            outer_box.pack_start(s_lbl, False, False, 0)

        scrolled.add(outer_box)
        return scrolled, outer_box

    def create_sidebar(self):
        sidebar = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        sidebar.get_style_context().add_class("fluent-sidebar")
        sidebar.set_size_request(240, -1)

        # App Brand Header
        brand_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        brand_box.set_margin_bottom(12)
        brand_box.set_margin_start(10)
        brand_box.set_margin_top(6)

        icon_lbl = Gtk.Label()
        icon_lbl.set_markup("<span font='18'>🛡️</span>")
        brand_box.pack_start(icon_lbl, False, False, 0)

        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        brand_title = Gtk.Label()
        brand_title.set_markup("<span font='13' weight='bold' color='#60cdff'>Zapret 2</span>")
        brand_title.set_xalign(0)
        brand_ver = Gtk.Label(label=APP_SUBTITLE)
        brand_ver.get_style_context().add_class("page-subtitle")
        brand_ver.set_xalign(0)
        title_box.pack_start(brand_title, False, False, 0)
        title_box.pack_start(brand_ver, False, False, 0)
        brand_box.pack_start(title_box, False, False, 0)
        sidebar.pack_start(brand_box, False, False, 0)

        # Navigation items grouped like Windows Zapret 2 UI
        nav_structure = [
            ("main", [("dashboard", "⚡ Управление Zapret 2")]),
            ("НАСТРОЙКИ ЗАПРЕТА", [
                ("zapret2", "🧩 Пресеты Zapret 2 (136)"),
                ("dpi_mode", "⚡ Режим DPI и скорость"),
                ("presets", "📁 Профили (Legacy v1)"),
                ("profiles", "▷ Параметры (Legacy v1)"),
            ]),
            ("ИНСТРУМЕНТЫ", [
                ("monitor", "📊 Монитор сети / Статус"),
                ("dns", "📶 Настройки DNS"),
                ("hosts", "📝 Редактор хостов"),
                ("updates", "🔄 Обновления баз Zapret 2"),
            ]),
            ("ДИАГНОСТИКА", [
                ("blockcheck", "🔍 BlockCheck & Диагностика"),
                ("logs", "📜 Журнал работы"),
            ]),
            ("СИСТЕМА", [
                ("settings", "⚙️ Настройки программы"),
            ])
        ]

        self.nav_buttons = {}
        for section_title, items in nav_structure:
            if section_title != "main":
                sec_lbl = Gtk.Label(label=section_title)
                sec_lbl.get_style_context().add_class("nav-section-title")
                sec_lbl.set_xalign(0)
                sidebar.pack_start(sec_lbl, False, False, 0)

            for name, label in items:
                btn = Gtk.ToggleButton(label=label)
                btn.get_style_context().add_class("fluent-nav-item")
                if btn.get_child() and hasattr(btn.get_child(), "set_xalign"):
                    btn.get_child().set_xalign(0)
                btn.connect("toggled", self.on_nav_toggled, name)
                sidebar.pack_start(btn, False, False, 0)
                self.nav_buttons[name] = btn

        # Bottom exit button
        btn_exit = Gtk.Button(label="🚪 Закрыть Zapret GUI")
        btn_exit.get_style_context().add_class("fluent-nav-item")
        if btn_exit.get_child() and hasattr(btn_exit.get_child(), "set_xalign"):
            btn_exit.get_child().set_xalign(0)
        btn_exit.connect("clicked", lambda _: self.quit_app(None))
        btn_exit.set_margin_top(12)
        sidebar.pack_end(btn_exit, False, False, 6)

        return sidebar

    def on_nav_toggled(self, button, name):
        if not button.get_active():
            if not any(b.get_active() for b in self.nav_buttons.values()):
                button.set_active(True)
            return
        if getattr(self, "_updating_nav", False):
            return
        self._updating_nav = True
        try:
            for key, btn in self.nav_buttons.items():
                if key != name and btn.get_active():
                    btn.set_active(False)
            if hasattr(self, "stack"):
                self.stack.set_visible_child_name(name)
        finally:
            self._updating_nav = False

    # ================= PAGE 1: DASHBOARD =================
    def create_dashboard_page(self):
        page, vbox = self.create_page_container(
            "Управление Zapret 2",
            "Настройка и запуск Zapret 2 на Linux (Arch / CachyOS). Обход блокировок ТСПУ без VPN."
        )

        meta = get_update_meta()

        # Top Metric Tiles Row (matching Windows Zapret 2)
        metric_grid = Gtk.Grid()
        metric_grid.set_column_spacing(10)
        metric_grid.set_row_spacing(10)
        metric_grid.set_column_homogeneous(True)
        metric_grid.set_margin_bottom(12)

        # Tile 1: Preset
        t1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        t1.get_style_context().add_class("metric-tile")
        l1 = Gtk.Label(label="📁 ТЕКУЩИЙ PRESET", xalign=0)
        l1.get_style_context().add_class("metric-tile-label")
        safe_preset_info = PRESETS.get(self.active_preset, PRESETS.get("general", {"title": "General"}))
        initial_preset = os.path.splitext(os.path.basename(self.zapret2_preset))[0] if self.engine_mode == "nfqws2" else safe_preset_info["title"].split("(")[0].strip()
        self.top_tile_preset = Gtk.Label(label=initial_preset, xalign=0)
        self.top_tile_preset.get_style_context().add_class("metric-tile-val")
        t1.pack_start(l1, False, False, 0)
        t1.pack_start(self.top_tile_preset, False, False, 0)
        metric_grid.attach(t1, 0, 0, 1, 1)

        # Tile 2: DPI Mode
        t2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        t2.get_style_context().add_class("metric-tile")
        l2 = Gtk.Label(label="⚡ ТЕКУЩИЙ РЕЖИМ", xalign=0)
        l2.get_style_context().add_class("metric-tile-label")
        mode_str = {"tpws": "TPWS (SOCKS5 1080)", "nfqws2": "NFQWS2 + Lua"}.get(self.engine_mode, "NFQWS v1")
        self.top_tile_mode = Gtk.Label(label=mode_str, xalign=0)
        self.top_tile_mode.get_style_context().add_class("metric-tile-val")
        t2.pack_start(l2, False, False, 0)
        t2.pack_start(self.top_tile_mode, False, False, 0)
        metric_grid.attach(t2, 1, 0, 1, 1)

        # Tile 3: DNS
        t3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        t3.get_style_context().add_class("metric-tile")
        l3 = Gtk.Label(label="🌐 DNS РЕЗОЛВЕР", xalign=0)
        l3.get_style_context().add_class("metric-tile-label")
        safe_dns_info = DNS_SERVERS.get(self.active_dns, DNS_SERVERS.get("cloudflare", {"title": "Cloudflare"}))
        self.top_tile_dns = Gtk.Label(label=safe_dns_info["title"].split("(")[0].strip(), xalign=0)
        self.top_tile_dns.get_style_context().add_class("metric-tile-val")
        t3.pack_start(l3, False, False, 0)
        t3.pack_start(self.top_tile_dns, False, False, 0)
        metric_grid.attach(t3, 2, 0, 1, 1)

        # Tile 4: Bases
        t4 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        t4.get_style_context().add_class("metric-tile")
        l4 = Gtk.Label(label="🔄 БАЗЫ ZAPRET 2", xalign=0)
        l4.get_style_context().add_class("metric-tile-label")
        self.top_tile_ver = Gtk.Label(label=f"v{meta.get('version', __version__)}", xalign=0)
        self.top_tile_ver.get_style_context().add_class("metric-tile-val")
        t4.pack_start(l4, False, False, 0)
        t4.pack_start(self.top_tile_ver, False, False, 0)
        metric_grid.attach(t4, 3, 0, 1, 1)

        vbox.pack_start(metric_grid, False, False, 0)

        # Status Banner Card ("Статус работы")
        self.status_banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self.status_banner.get_style_context().add_class("status-banner-inactive")

        banner_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)

        # Pill badges line
        pill_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.pill_status = Gtk.Label(label="○ Обход DPI выключен")
        self.pill_status.get_style_context().add_class("badge-bad")
        pill_box.pack_start(self.pill_status, False, False, 0)

        self.pill_preset = Gtk.Label(label=f"⚡ {initial_preset}")
        self.pill_preset.get_style_context().add_class("badge-accent")
        pill_box.pack_start(self.pill_preset, False, False, 0)

        self.pill_dns = Gtk.Label(label=f"🌐 {DNS_SERVERS[self.active_dns]['title'].split('(')[0].strip()}")
        self.pill_dns.get_style_context().add_class("badge-neutral")
        pill_box.pack_start(self.pill_dns, False, False, 0)

        banner_info.pack_start(pill_box, False, False, 0)

        self.status_title = Gtk.Label()
        self.status_title.set_markup("<span font='15' weight='bold'>Обход DPI остановлен</span>")
        self.status_title.set_xalign(0)
        self.status_desc = Gtk.Label(label="Нажмите «Запустить обход», чтобы включить десинхронизацию для YouTube, Discord и заблокированных сайтов.")
        self.status_desc.set_xalign(0)
        banner_info.pack_start(self.status_title, False, False, 0)
        banner_info.pack_start(self.status_desc, False, False, 0)
        self.status_banner.pack_start(banner_info, True, True, 0)

        self.btn_toggle = Gtk.Button(label="Запустить обход")
        self.btn_toggle.get_style_context().add_class("fluent-btn-primary")
        self.btn_toggle.set_valign(Gtk.Align.CENTER)
        self.btn_toggle.connect("clicked", self.on_toggle_engine)
        self.status_banner.pack_end(self.btn_toggle, False, False, 0)
        vbox.pack_start(self.status_banner, False, False, 0)

        # Quick Actions Card ("Управление службой")
        qa_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        qa_card.get_style_context().add_class("fluent-card")

        btn_restart = Gtk.Button(label="🔄 Перезапустить обход")
        btn_restart.get_style_context().add_class("fluent-btn-secondary")
        btn_restart.connect("clicked", lambda _: self.restart_engine())
        qa_card.pack_start(btn_restart, False, False, 0)

        btn_sync = Gtk.Button(label="⚡ Синхронизировать базы")
        btn_sync.get_style_context().add_class("fluent-btn-secondary")
        btn_sync.connect("clicked", lambda _: self.switch_to_tab("updates"))
        qa_card.pack_start(btn_sync, False, False, 0)

        btn_test = Gtk.Button(label="🔍 Быстрый тест доступности")
        btn_test.get_style_context().add_class("fluent-btn-secondary")
        btn_test.connect("clicked", lambda _: self.switch_to_tab("blockcheck"))
        qa_card.pack_start(btn_test, False, False, 0)

        btn_logs = Gtk.Button(label="📜 Журнал работы")
        btn_logs.get_style_context().add_class("fluent-btn-secondary")
        btn_logs.connect("clicked", lambda _: self.switch_to_tab("logs"))
        qa_card.pack_start(btn_logs, False, False, 0)

        vbox.pack_start(qa_card, False, False, 0)

        # Settings Rows Section (matching Windows Zapret 2 UI settings)
        sec_header = Gtk.Label(label="Быстрые параметры программы", xalign=0)
        sec_header.get_style_context().add_class("nav-section-title")
        sec_header.set_margin_top(8)
        sec_header.set_margin_bottom(6)
        vbox.pack_start(sec_header, False, False, 0)

        # Row 1: Autostart ZapretGUI
        self.sw_autostart = Gtk.Switch()
        self.sw_autostart.set_active(os.path.exists(AUTOSTART_FILE))
        self.sw_autostart.set_halign(Gtk.Align.END)
        self.sw_autostart.set_valign(Gtk.Align.CENTER)
        self.sw_autostart.connect("notify::active", self.on_autostart_toggled)
        r1 = self.create_setting_row(
            "🔌",
            "Автозапуск ZapretGUI при входе в систему",
            "Автоматический фоновый запуск службы при старте сессии Linux",
            self.sw_autostart
        )
        vbox.pack_start(r1, False, False, 0)

        # Row 2: Autostart DPI bypass
        self.sw_dpi_auto = Gtk.Switch()
        self.sw_dpi_auto.set_active(self.dpi_auto)
        self.sw_dpi_auto.set_halign(Gtk.Align.END)
        self.sw_dpi_auto.set_valign(Gtk.Align.CENTER)
        self.sw_dpi_auto.connect("notify::active", self.on_dpi_auto_toggled)
        r2 = self.create_setting_row(
            "⚡",
            "Автозапуск обхода DPI после старта программы",
            "Сразу переводить десинхронизатор в активный режим без ручного запуска",
            self.sw_dpi_auto
        )
        vbox.pack_start(r2, False, False, 0)

        # Row 3: Network Interface
        self.combo_iface_quick = Gtk.ComboBoxText()
        self.populate_iface_combo(self.combo_iface_quick)
        self.combo_iface_quick.set_halign(Gtk.Align.END)
        self.combo_iface_quick.set_valign(Gtk.Align.CENTER)
        self.combo_iface_quick.connect("changed", self.on_iface_changed)
        r3 = self.create_setting_row(
            "🌐",
            "Сетевой интерфейс перехвата",
            f"Фильтрация исходящего сетевого трафика на адаптере (текущий: {self.active_iface})",
            self.combo_iface_quick
        )
        vbox.pack_start(r3, False, False, 0)

        # Row 4: TCP BBR
        self.sw_bbr = Gtk.Switch()
        self.sw_bbr.set_active(True)
        self.sw_bbr.set_halign(Gtk.Align.END)
        self.sw_bbr.set_valign(Gtk.Align.CENTER)
        self.sw_bbr.connect("notify::active", lambda s, _: self.apply_network_tune())
        r4 = self.create_setting_row(
            "🚀",
            "Оптимизация сети (Google BBR + conntrack liberal)",
            "Тюнинг ядра Linux для гигабитных скоростей и защиты от сброса desync пакетов",
            self.sw_bbr
        )
        vbox.pack_start(r4, False, False, 0)

        # Row 5: AI Hosts
        self.sw_ai_hosts = Gtk.Switch()
        self.sw_ai_hosts.set_active(self.enable_ai_hosts)
        self.sw_ai_hosts.set_halign(Gtk.Align.END)
        self.sw_ai_hosts.set_valign(Gtk.Align.CENTER)
        self.sw_ai_hosts.connect("notify::active", self.on_ai_hosts_toggled)
        r5 = self.create_setting_row(
            "🤖",
            "Разблокировка нейросетей (AI Smart Proxy в hosts)",
            "Автоматический обход блокировок для ChatGPT, Claude, Gemini и OpenAI",
            self.sw_ai_hosts
        )
        vbox.pack_start(r5, False, False, 0)

        return page

    def create_setting_row(self, icon_str, title_text, desc_text, control_widget):
        """Creates a modern Windows 11 style setting row."""
        row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row_box.get_style_context().add_class("fluent-setting-row")

        # Icon
        icon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        icon_box.get_style_context().add_class("setting-icon-box")
        lbl_icon = Gtk.Label()
        lbl_icon.set_markup(f"<span font='14'>{icon_str}</span>")
        icon_box.pack_start(lbl_icon, True, True, 0)
        row_box.pack_start(icon_box, False, False, 0)

        # Title & Description
        txt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        lbl_title = Gtk.Label(label=f"<b>{GLib.markup_escape_text(title_text)}</b>", use_markup=True, xalign=0)
        lbl_desc = Gtk.Label(label=desc_text, xalign=0)
        lbl_desc.get_style_context().add_class("page-subtitle")
        txt_box.pack_start(lbl_title, False, False, 0)
        txt_box.pack_start(lbl_desc, False, False, 0)
        row_box.pack_start(txt_box, True, True, 0)

        # Control widget (Switch, Combo, etc.) aligned to end
        control_widget.set_halign(Gtk.Align.END)
        control_widget.set_valign(Gtk.Align.CENTER)
        row_box.pack_end(control_widget, False, False, 0)

        return row_box

    # ================= PAGE 2: PRESETS =================
    def create_presets_page(self):
        page, vbox = self.create_page_container(
            "Профили работы",
            "Выберите готовую стратегию десинхронизации пакетов под вашего интернет-провайдера"
        )

        self.preset_radios = {}
        first_radio = None

        for key, p in PRESETS.items():
            card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
            card.get_style_context().add_class("fluent-card")

            h_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)

            radio = Gtk.RadioButton(group=first_radio)
            if first_radio is None:
                first_radio = radio
            if key == self.active_preset:
                radio.set_active(True)
            radio.set_valign(Gtk.Align.CENTER)
            radio.connect("toggled", self.on_preset_radio_toggled, key)
            self.preset_radios[key] = radio
            h_card.pack_start(radio, False, False, 0)

            c_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            t = Gtk.Label(label=f"<b>{GLib.markup_escape_text(p['title'])}</b>")
            t.set_use_markup(True)
            t.set_xalign(0)
            h_box.pack_start(t, False, False, 0)

            badge = Gtk.Label(label=p["badge"])
            badge.get_style_context().add_class("badge-ok")
            h_box.pack_start(badge, False, False, 0)
            c_info.pack_start(h_box, False, False, 0)

            d = Gtk.Label(label=p["desc"])
            d.get_style_context().add_class("page-subtitle")
            d.set_xalign(0)
            c_info.pack_start(d, False, False, 0)

            h_card.pack_start(c_info, True, True, 0)
            card.pack_start(h_card, False, False, 0)

            if key == "custom":
                custom_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                custom_box.set_margin_start(32)
                custom_box.pack_start(Gtk.Label(label="<b>Пользовательские параметры nfqws:</b>", use_markup=True, xalign=0), False, False, 0)
                self.entry_custom_params = Gtk.Entry()
                self.entry_custom_params.set_text(self.custom_params)
                self.entry_custom_params.set_placeholder_text("--filter-tcp=443,2053,2083,2087,2096,8443 --dpi-desync=fake,multidisorder ...")
                self.entry_custom_params.connect("changed", self.on_custom_params_changed)
                custom_box.pack_start(self.entry_custom_params, False, False, 0)
                card.pack_start(custom_box, False, False, 0)

            vbox.pack_start(card, False, False, 0)

        # Hostlist Mode Card
        h_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        h_card.get_style_context().add_class("fluent-card")
        h_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        h_info.pack_start(Gtk.Label(label="<b>Режим фильтрации доменов (Hostlist Mode)</b>", use_markup=True, xalign=0), False, False, 0)
        h_info.pack_start(Gtk.Label(label="Десинхронизировать все сайты (кроме exclude.txt) или только входящие в list-general.txt", xalign=0), False, False, 0)
        h_card.pack_start(h_info, True, True, 0)

        self.combo_hostlist = Gtk.ComboBoxText()
        self.combo_hostlist.append("all_except_exclude", "Все сайты (кроме exclude.txt)")
        self.combo_hostlist.append("strict_list", "Только по списку (list-general.txt)")
        self.combo_hostlist.set_active_id(self.hostlist_mode)
        self.combo_hostlist.connect("changed", self.on_hostlist_mode_changed)
        self.combo_hostlist.set_valign(Gtk.Align.CENTER)
        h_card.pack_end(self.combo_hostlist, False, False, 0)
        vbox.pack_start(h_card, False, False, 0)

        # Apply Preset Button
        btn_apply = Gtk.Button(label="💾 Применить выбранный пресет")
        btn_apply.get_style_context().add_class("fluent-btn-primary")
        btn_apply.connect("clicked", lambda _: self.restart_engine())
        vbox.pack_start(btn_apply, False, False, 8)

        return page

    def on_custom_params_changed(self, entry):
        self.custom_params = entry.get_text()
        self.save_config()

    def on_hostlist_mode_changed(self, combo):
        self.hostlist_mode = combo.get_active_id() or "all_except_exclude"
        self.save_config()

    def on_preset_radio_toggled(self, radio, key):
        if radio.get_active():
            self.active_preset = key
            p_info = PRESETS.get(key, {"title": key})
            if hasattr(self, "top_tile_preset"):
                self.top_tile_preset.set_text(p_info["title"].split("(")[0].strip())
            if hasattr(self, "pill_preset"):
                self.pill_preset.set_text(f"⚡ {p_info['title']}")
            self.save_config()

    # ================= PAGE 3: PROFILES =================
    def create_profiles_page(self):
        page, vbox = self.create_page_container(
            "Профили пресета",
            "Сервисы и правила обработки трафика в текущем профиле"
        )

        profiles = [
            ("youtube", "🎬 YouTube (TCP 443, 80)", "fake,multidisorder + ts fooling", "Обход замедления веб-интерфейса и видеосерверов googlevideo", self.enable_youtube),
            ("discord_tcp", "💬 Discord (TCP 443)", "fake,multidisorder + ts fooling", "Обход блокировки API, авторизации и шлюза Discord", self.enable_discord_tcp),
            ("discord_voice", "🎙️ Discord Voice / STUN", "UDP 19294-19344, 50000-50100 (fake discord, stun)", "Разблокировка голосовых каналов и звонков в Discord", self.enable_discord_voice),
            ("quic", "⚡ YouTube QUIC / HTTP/3", "UDP 443 (fake-quic google)", "Ускорение буферизации видео через протокол QUIC", self.enable_quic),
            ("general_https", "🌐 Общий HTTPS трафик", "Порты 443, 2053, 2083, 2087, 8443", "Разблокировка всех остальных веб-сайтов под цензурой", self.enable_general_https)
        ]

        self.profile_switches = {}

        for p_key, title, spec, desc, enabled in profiles:
            card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            card.get_style_context().add_class("fluent-card")

            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            t = Gtk.Label(label=f"<b>{GLib.markup_escape_text(title)}</b>")
            t.set_use_markup(True)
            t.set_xalign(0)
            h_box.pack_start(t, False, False, 0)

            badge = Gtk.Label(label=spec)
            badge.get_style_context().add_class("badge-ok")
            h_box.pack_start(badge, False, False, 0)
            box.pack_start(h_box, False, False, 0)

            d = Gtk.Label(label=desc)
            d.get_style_context().add_class("page-subtitle")
            d.set_xalign(0)
            box.pack_start(d, False, False, 0)

            card.pack_start(box, True, True, 0)

            sw = Gtk.Switch()
            sw.set_active(enabled)
            sw.set_halign(Gtk.Align.END)
            sw.set_valign(Gtk.Align.CENTER)
            sw.connect("notify::active", self.on_profile_switch_toggled, p_key)
            self.profile_switches[p_key] = sw
            if p_key == "quic":
                self.sw_prof_quic = sw
            elif p_key == "discord_voice":
                self.sw_prof_discord_voice = sw

            card.pack_end(sw, False, False, 0)
            vbox.pack_start(card, False, False, 0)

        btn_apply = Gtk.Button(label="💾 Применить параметры профилей")
        btn_apply.get_style_context().add_class("fluent-btn-primary")
        btn_apply.connect("clicked", lambda _: self.restart_engine() if self.is_running else None)
        vbox.pack_start(btn_apply, False, False, 8)

        return page

    def on_profile_switch_toggled(self, switch, _, p_key):
        active = switch.get_active()
        if p_key == "quic":
            self.on_quic_toggled(switch, None)
        elif p_key == "discord_voice":
            self.enable_discord_voice = active
            self.save_config()
        elif p_key == "youtube":
            self.enable_youtube = active
            self.save_config()
        elif p_key == "discord_tcp":
            self.enable_discord_tcp = active
            self.save_config()
        elif p_key == "general_https":
            self.enable_general_https = active
            self.save_config()

    def on_quic_toggled(self, switch, _):
        if self._syncing_quic:
            return
        active = switch.get_active()
        self.enable_quic = active
        self._syncing_quic = True
        try:
            if hasattr(self, "sw_quic") and self.sw_quic != switch:
                self.sw_quic.set_active(active)
            if hasattr(self, "sw_prof_quic") and self.sw_prof_quic != switch:
                self.sw_prof_quic.set_active(active)
        finally:
            self._syncing_quic = False
        self.save_config()

    def create_zapret2_page(self):
        self.zapret2_page = Zapret2Page(self)
        return self.zapret2_page.create()

    # ================= PAGE 4: DPI MODE & TUNING =================
    def create_dpi_mode_page(self):
        page, vbox = self.create_page_container(
            "Скорость / Режим DPI",
            "Тонкая настройка сетевого стека, параметров десинхронизации и протоколов"
        )

        # Card 0: Engine Mode (NFQWS vs TPWS)
        c0 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        c0.get_style_context().add_class("fluent-card")
        b0 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        b0.pack_start(Gtk.Label(label="<b>Архитектура десинхронизатора (Движок)</b>", use_markup=True, xalign=0), False, False, 0)
        b0.pack_start(Gtk.Label(label="NFQWS (Netfilter Queue — ядро Linux) vs TPWS (Локальный SOCKS5 прокси 127.0.0.1:1080)", xalign=0), False, False, 0)
        c0.pack_start(b0, True, True, 0)

        self.combo_engine_mode = Gtk.ComboBoxText()
        self.combo_engine_mode.append("nfqws2", "NFQWS2 + Lua (Zapret2, по умолчанию)")
        self.combo_engine_mode.append("tpws", "TPWS (только SOCKS5 127.0.0.1:1080)")
        self.combo_engine_mode.append("nfqws", "NFQWS v1 (устаревший legacy)")
        self.combo_engine_mode.set_active_id(self.engine_mode)
        self.combo_engine_mode.connect("changed", self.on_engine_mode_changed)
        self.combo_engine_mode.set_valign(Gtk.Align.CENTER)
        c0.pack_end(self.combo_engine_mode, False, False, 0)
        vbox.pack_start(c0, False, False, 0)

        # Card 1: QUIC / UDP 443
        c1 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        c1.get_style_context().add_class("fluent-card")
        b1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        b1.pack_start(Gtk.Label(label="<b>Ускорение YouTube через QUIC (HTTP/3)</b>", use_markup=True, xalign=0), False, False, 0)
        b1.pack_start(Gtk.Label(label="Пропускает первые 6 UDP пакетов через десинхронизатор вместо жесткого сброса", xalign=0), False, False, 0)
        c1.pack_start(b1, True, True, 0)
        self.sw_quic = Gtk.Switch()
        self.sw_quic.set_active(self.enable_quic)
        self.sw_quic.set_halign(Gtk.Align.END)
        self.sw_quic.set_valign(Gtk.Align.CENTER)
        self.sw_quic.connect("notify::active", self.on_quic_toggled)
        c1.pack_end(self.sw_quic, False, False, 0)
        vbox.pack_start(c1, False, False, 0)

        # Card 2: Conntrack Cutoff Limit
        c2 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        c2.get_style_context().add_class("fluent-card")
        b2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        b2.pack_start(Gtk.Label(label="<b>Ограничение перехвата conntrack (пакетов)</b>", use_markup=True, xalign=0), False, False, 0)
        b2.pack_start(Gtk.Label(label="Обрабатывает только TLS Handshake, затем передает соединение ядру на полной скорости 1Gbps+", xalign=0), False, False, 0)
        c2.pack_start(b2, True, True, 0)

        spin_adj = Gtk.Adjustment(value=float(self.conntrack_limit), lower=1, upper=64, step_increment=1, page_increment=4)
        self.spin_conntrack = Gtk.SpinButton(adjustment=spin_adj, climb_rate=1, digits=0)
        self.spin_conntrack.set_valign(Gtk.Align.CENTER)
        self.spin_conntrack.connect("value-changed", self.on_conntrack_changed)
        c2.pack_end(self.spin_conntrack, False, False, 0)
        vbox.pack_start(c2, False, False, 0)

        # Card 3: Kernel TCP BBR
        c3 = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        c3.get_style_context().add_class("fluent-card")
        b3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        b3.pack_start(Gtk.Label(label="<b>Алгоритм перегрузки TCP BBR + FQ</b>", use_markup=True, xalign=0), False, False, 0)
        b3.pack_start(Gtk.Label(label="Устраняет потери пакетов и скачки задержки на высоконагруженных каналах связи", xalign=0), False, False, 0)
        c3.pack_start(b3, True, True, 0)
        lbl_bbr = Gtk.Label(label="Активен")
        lbl_bbr.get_style_context().add_class("badge-ok")
        lbl_bbr.set_valign(Gtk.Align.CENTER)
        c3.pack_end(lbl_bbr, False, False, 0)
        vbox.pack_start(c3, False, False, 0)

        # Action: Re-apply tuning
        btn_tune = Gtk.Button(label="⚡ Применить оптимизации ядра Linux")
        btn_tune.get_style_context().add_class("fluent-btn-primary")
        btn_tune.connect("clicked", lambda _: self.apply_network_tune())
        vbox.pack_start(btn_tune, False, False, 8)

        return page

    def on_engine_mode_changed(self, combo):
        mid = combo.get_active_id() or "nfqws"
        if mid == self.engine_mode:
            return
        self.engine_mode = mid
        self.save_config()
        self.update_top_tile_mode()
        if self.is_running:
            self.restart_engine()

    def update_top_tile_mode(self):
        if hasattr(self, "top_tile_mode"):
            if self.engine_mode == "tpws":
                self.top_tile_mode.set_text("TPWS (SOCKS5 1080)")
            elif self.engine_mode == "nfqws2":
                self.top_tile_mode.set_text("NFQWS2 + Lua")
                self.top_tile_preset.set_text(os.path.splitext(os.path.basename(self.zapret2_preset))[0])
                if hasattr(self, "pill_preset"):
                    self.pill_preset.set_text(f"⚡ {os.path.splitext(os.path.basename(self.zapret2_preset))[0]}")
            else:
                self.top_tile_mode.set_text("NFQWS v1 (Netfilter Queue)")

    def on_conntrack_changed(self, spin):
        self.conntrack_limit = int(spin.get_value())
        self.save_config()

    def populate_iface_combo(self, combo):
        combo.remove_all()
        ifaces = get_network_interfaces()
        for ifc in ifaces:
            if ifc == "any":
                combo.append("any", "any (Автоопределение маршрута)")
            else:
                combo.append(ifc, f"{ifc} (Сетевой адаптер)")
        if self.active_iface in ifaces:
            combo.set_active_id(self.active_iface)
        else:
            combo.set_active_id("any")
            self.active_iface = "any"

    def apply_network_tune(self):
        run_engine("tune")
        self.show_dialog("Успех", "Оптимизации TCP BBR, FQ qdisc и conntrack успешно применены к ядру Linux!")

    # ================= PAGE 5: NETWORK MONITOR =================
    def create_monitor_page(self):
        page, vbox = self.create_page_container(
            "Монитор сети и Статус",
            "Информация о сетевых интерфейсах, задержках и правилах фильтрации nftables"
        )

        # Card 1: Network Interface Info
        card1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card1.get_style_context().add_class("fluent-card")
        card1.pack_start(Gtk.Label(label="<b>Сетевой интерфейс и шлюз</b>", use_markup=True, xalign=0), False, False, 0)

        grid_net = Gtk.Grid()
        grid_net.set_column_spacing(16)
        grid_net.set_row_spacing(6)

        self.lbl_net_iface = Gtk.Label(label=f"Интерфейс: {self.active_iface}", xalign=0)
        self.lbl_net_ip = Gtk.Label(label="IPv4 адрес: определяется...", xalign=0)
        self.lbl_net_gw = Gtk.Label(label="Шлюз по умолчанию: определяется...", xalign=0)
        self.lbl_net_bbr = Gtk.Label(label="TCP Congestion: BBR (FQ qdisc)", xalign=0)

        grid_net.attach(self.lbl_net_iface, 0, 0, 1, 1)
        grid_net.attach(self.lbl_net_ip, 1, 0, 1, 1)
        grid_net.attach(self.lbl_net_gw, 0, 1, 1, 1)
        grid_net.attach(self.lbl_net_bbr, 1, 1, 1, 1)
        card1.pack_start(grid_net, False, False, 0)
        vbox.pack_start(card1, False, False, 0)

        # Card 2: Ping & Latency Monitor
        card2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card2.get_style_context().add_class("fluent-card")

        h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        h_box.pack_start(Gtk.Label(label="<b>Задержка до ключевых серверов (Latency)</b>", use_markup=True, xalign=0), True, True, 0)
        btn_refresh_ping = Gtk.Button(label="🔄 Измерить задержку")
        btn_refresh_ping.get_style_context().add_class("fluent-btn-secondary")
        btn_refresh_ping.connect("clicked", lambda _: self.refresh_network_monitor())
        h_box.pack_end(btn_refresh_ping, False, False, 0)
        card2.pack_start(h_box, False, False, 0)

        grid_ping = Gtk.Grid()
        grid_ping.set_column_spacing(12)
        grid_ping.set_row_spacing(8)
        grid_ping.set_column_homogeneous(True)

        self.ping_targets = [
            ("youtube", "YouTube Video (142.250.x.x)", "142.250.180.206"),
            ("discord", "Discord Gateway (162.159.x.x)", "162.159.135.232"),
            ("cloudflare", "Cloudflare DNS (1.1.1.1)", "1.1.1.1"),
            ("telegram", "Telegram Core (149.154.x.x)", "149.154.167.50")
        ]

        self.ping_labels = {}
        col = 0
        row = 0
        for key, name, ip in self.ping_targets:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.get_style_context().add_class("fluent-tile")
            box.pack_start(Gtk.Label(label=name, xalign=0), False, False, 0)

            p_badge = Gtk.Label(label="-- ms")
            p_badge.get_style_context().add_class("badge-neutral")
            p_badge.set_xalign(0)
            self.ping_labels[key] = p_badge
            box.pack_start(p_badge, False, False, 0)

            grid_ping.attach(box, col, row, 1, 1)
            col += 1
            if col > 1:
                col = 0
                row += 1

        card2.pack_start(grid_ping, False, False, 0)
        vbox.pack_start(card2, False, False, 0)

        # Card 3: Firewall Rules Status
        card3 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        card3.get_style_context().add_class("fluent-card")
        card3.pack_start(Gtk.Label(label="<b>Статус таблицы nftables (zapret_gui)</b>", use_markup=True, xalign=0), False, False, 0)
        self.lbl_nft_status = Gtk.Label(label="Таблица mangle: активна (перехват TCP 443, UDP 443, UDP Discord)", xalign=0)
        card3.pack_start(self.lbl_nft_status, False, False, 0)
        vbox.pack_start(card3, False, False, 0)

        GLib.timeout_add(500, self.refresh_network_monitor)
        GLib.timeout_add_seconds(10, self._on_network_periodic_timer)
        return page

    def _on_network_periodic_timer(self):
        if hasattr(self, "lbl_net_gw"):
            self.refresh_network_monitor()
        return True

    def refresh_network_monitor(self):
        if getattr(self, "_refreshing_network", False):
            return False
        self._refreshing_network = True

        def worker():
            try:
                gw_res = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
                gw_line = gw_res.stdout.strip().split("\n")[0] if gw_res.stdout else ""
                gw = "Не определен"
                real_dev = None
                parts = gw_line.split()
                if "via" in parts:
                    idx = parts.index("via")
                    if idx + 1 < len(parts):
                        gw = parts[idx + 1]
                if "dev" in parts:
                    idx = parts.index("dev")
                    if idx + 1 < len(parts):
                        real_dev = parts[idx + 1]

                target_dev = self.active_iface
                if target_dev == "any" or not target_dev:
                    target_dev = real_dev if real_dev else "lo"

                ip_res = subprocess.run(["ip", "-4", "addr", "show", target_dev], capture_output=True, text=True)
                my_ip = "Не назначен"
                for line in ip_res.stdout.splitlines():
                    if "inet " in line:
                        my_ip = line.strip().split()[1]
                        break

                display_iface = f"{self.active_iface} ({target_dev})" if self.active_iface == "any" and real_dev else self.active_iface

                GLib.idle_add(self.lbl_net_gw.set_text, f"Шлюз по умолчанию: {gw}")
                GLib.idle_add(self.lbl_net_ip.set_text, f"IPv4 адрес: {my_ip}")
                GLib.idle_add(self.lbl_net_iface.set_text, f"Интерфейс: {display_iface}")

                for key, name, ip in self.ping_targets:
                    p_res = subprocess.run(["ping", "-c", "1", "-W", "1", ip], capture_output=True, text=True)
                    if p_res.returncode == 0:
                        for line in p_res.stdout.splitlines():
                            if "time=" in line:
                                val = line.split("time=")[1].split()[0]
                                ms = float(val)
                                txt = f"{int(ms)} ms"
                                cls = "badge-ok" if ms < 60 else ("badge-warn" if ms < 150 else "badge-bad")
                                GLib.idle_add(self.update_ping_badge, key, txt, cls)
                                break
                    else:
                        GLib.idle_add(self.update_ping_badge, key, "Таймаут", "badge-bad")
            except Exception:
                pass
            finally:
                self._refreshing_network = False
        threading.Thread(target=worker, daemon=True).start()
        return False

    def update_ping_badge(self, key, text, css_cls):
        badge = self.ping_labels.get(key)
        if badge:
            badge.set_text(text)
            for c in ["badge-neutral", "badge-ok", "badge-warn", "badge-bad"]:
                badge.get_style_context().remove_class(c)
            badge.get_style_context().add_class(css_cls)

    # ================= PAGE 6: DNS SETTINGS =================
    def create_dns_page(self):
        page, vbox = self.create_page_container(
            "Настройки DNS (DNS-over-TLS)",
            "Выбор защищенного DoT резолвера с защитой от подмены ответов провайдером"
        )

        self.dns_radios = {}
        first_radio = None

        for key, d in DNS_SERVERS.items():
            card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            card.get_style_context().add_class("fluent-card")

            radio = Gtk.RadioButton(group=first_radio)
            if first_radio is None:
                first_radio = radio
            if key == self.active_dns:
                radio.set_active(True)
            radio.set_valign(Gtk.Align.CENTER)
            radio.connect("toggled", self.on_dns_radio_toggled, key)
            self.dns_radios[key] = radio
            card.pack_start(radio, False, False, 0)

            c_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            t = Gtk.Label(label=f"<b>{GLib.markup_escape_text(d['title'])}</b>")
            t.set_use_markup(True)
            t.set_xalign(0)
            h_box.pack_start(t, False, False, 0)

            badge = Gtk.Label(label=d["badge"])
            badge.get_style_context().add_class("badge-accent")
            h_box.pack_start(badge, False, False, 0)
            c_info.pack_start(h_box, False, False, 0)

            desc_lbl = Gtk.Label(label=d["desc"])
            desc_lbl.get_style_context().add_class("page-subtitle")
            desc_lbl.set_xalign(0)
            c_info.pack_start(desc_lbl, False, False, 0)

            card.pack_start(c_info, True, True, 0)
            vbox.pack_start(card, False, False, 0)

        # Apply & Test DNS Buttons
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_apply = Gtk.Button(label="💾 Применить DNS")
        btn_apply.get_style_context().add_class("fluent-btn-primary")
        btn_apply.connect("clicked", lambda _: self.restart_engine())
        btn_box.pack_start(btn_apply, False, False, 0)

        btn_test = Gtk.Button(label="🔍 Проверить DoT резолвинг")
        btn_test.get_style_context().add_class("fluent-btn-secondary")
        btn_test.connect("clicked", self.on_test_dns)
        btn_box.pack_start(btn_test, False, False, 0)
        vbox.pack_start(btn_box, False, False, 8)

        return page

    def on_dns_radio_toggled(self, radio, key):
        if radio.get_active():
            self.active_dns = key
            if hasattr(self, "top_tile_dns"):
                self.top_tile_dns.set_text(DNS_SERVERS[key]["title"].split("(")[0].strip())
            if hasattr(self, "pill_dns"):
                self.pill_dns.set_text(f"🌐 {DNS_SERVERS[key]['title'].split('(')[0].strip()}")
            self.save_config()

    def on_test_dns(self, _):
        def worker():
            try:
                res = subprocess.run(["resolvectl", "query", "cloudflare.com"], capture_output=True, text=True, timeout=3)
                if res.returncode == 0:
                    GLib.idle_add(self.show_dialog, "Тест DNS", "DoT резолвинг успешно функционирует!\ncloudflare.com успешно разрешен.")
                else:
                    GLib.idle_add(self.show_dialog, "Тест DNS", f"Ошибка резолвинга:\n{res.stderr or res.stdout}")
            except Exception as e:
                GLib.idle_add(self.show_dialog, "Тест DNS", f"Ошибка: {e}")
        threading.Thread(target=worker, daemon=True).start()

    # ================= PAGE 7: HOSTS EDITOR =================
    def create_hosts_page(self):
        page, vbox = self.create_page_container(
            "Редактор хостов и списков",
            "Управление списками исключений, Badsum-хостами и базой Smart Proxy в /etc/hosts"
        )

        # Master Switch Card
        master_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        master_card.get_style_context().add_class("fluent-card")
        m_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        m_info.pack_start(Gtk.Label(label="<b>Разблокировка сервисов ИИ и сайтов через /etc/hosts</b>", use_markup=True, xalign=0), False, False, 0)
        m_info.pack_start(Gtk.Label(label="Автоматически внедряет базу Smart Proxy (Gemini, ChatGPT, Claude, Spotify и 90+ сервисов)", xalign=0), False, False, 0)
        master_card.pack_start(m_info, True, True, 0)

        self.sw_ai_master = Gtk.Switch()
        self.sw_ai_master.set_active(self.enable_ai_hosts)
        self.sw_ai_master.set_halign(Gtk.Align.END)
        self.sw_ai_master.set_valign(Gtk.Align.CENTER)
        self.sw_ai_master.connect("notify::active", self.on_ai_hosts_toggled)
        master_card.pack_end(self.sw_ai_master, False, False, 0)
        vbox.pack_start(master_card, False, False, 0)

        # File Selector Bar
        file_sel_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        file_sel_card.get_style_context().add_class("fluent-card")
        file_sel_card.pack_start(Gtk.Label(label="<b>Выберите файл:</b>", use_markup=True), False, False, 0)

        self.hosts_files = {
            "hosts": os.path.join(APP_DIR, "hosts.txt"),
            "badsum": os.path.join(APP_DIR, "badsum_hosts.txt"),
            "exclude": os.path.join(APP_DIR, "exclude.txt"),
            "general": os.path.join(APP_DIR, "list-general.txt"),
            "custom": os.path.join(APP_DIR, "custom_hosts.txt")
        }

        self.combo_file = Gtk.ComboBoxText()
        self.combo_file.append("custom", "custom_hosts.txt (Свои домены, сохраняются при обновлении)")
        self.combo_file.append("hosts", "hosts.txt (База Smart Proxy для ИИ и сайтов)")
        self.combo_file.append("badsum", "badsum_hosts.txt (Хосты с badsum fooling)")
        self.combo_file.append("exclude", "exclude.txt (Исключения из обхода DPI)")
        self.combo_file.append("general", "list-general.txt (Базовый список, заменяется обновлением)")
        self.combo_file.set_active_id("custom")
        self.combo_file.connect("changed", self.on_hosts_file_changed)
        file_sel_card.pack_start(self.combo_file, True, True, 0)

        btn_reload = Gtk.Button(label="🔄 Загрузить")
        btn_reload.get_style_context().add_class("fluent-btn-secondary")
        btn_reload.connect("clicked", lambda _: self.load_hosts_file_content())
        file_sel_card.pack_end(btn_reload, False, False, 0)

        vbox.pack_start(file_sel_card, False, False, 0)

        # Editor Box
        ed_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        ed_card.get_style_context().add_class("fluent-card")

        scroller = Gtk.ScrolledWindow()
        scroller.set_size_request(-1, 260)
        self.hosts_buffer = Gtk.TextBuffer()
        self.hosts_view = Gtk.TextView(buffer=self.hosts_buffer)
        self.hosts_view.get_style_context().add_class("log-view")
        scroller.add(self.hosts_view)
        ed_card.pack_start(scroller, True, True, 0)

        # Actions
        btn_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        btn_save = Gtk.Button(label="💾 Сохранить файл")
        btn_save.get_style_context().add_class("fluent-btn-primary")
        btn_save.connect("clicked", lambda _: self.save_hosts_file_content())
        btn_box.pack_start(btn_save, False, False, 0)

        btn_apply_hosts = Gtk.Button(label="🚀 Применить базу в /etc/hosts")
        btn_apply_hosts.get_style_context().add_class("fluent-btn-secondary")
        btn_apply_hosts.connect("clicked", lambda _: self.apply_hosts_now())
        btn_box.pack_start(btn_apply_hosts, False, False, 0)

        btn_clean_hosts = Gtk.Button(label="🧹 Очистить записи Zapret")
        btn_clean_hosts.get_style_context().add_class("fluent-btn-secondary")
        btn_clean_hosts.connect("clicked", lambda _: self.clean_hosts_now())
        btn_box.pack_start(btn_clean_hosts, False, False, 0)

        self.btn_ip2net = Gtk.Button(label="🌐 Собрать IP-подсети (mdig + ip2net)")
        self.btn_ip2net.get_style_context().add_class("fluent-btn-secondary")
        self.btn_ip2net.connect("clicked", self.on_build_ipset_clicked)
        btn_box.pack_start(self.btn_ip2net, False, False, 0)

        ed_card.pack_start(btn_box, False, False, 0)
        vbox.pack_start(ed_card, False, False, 0)

        self.load_hosts_file_content()
        return page

    def on_hosts_file_changed(self, _):
        self.load_hosts_file_content()

    def load_hosts_file_content(self):
        k = self.combo_file.get_active_id() or "hosts"
        fpath = self.hosts_files.get(k)
        if fpath and os.path.exists(fpath):
            try:
                with open(fpath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                    self.hosts_buffer.set_text(content)
            except Exception as e:
                self.hosts_buffer.set_text(f"Ошибка чтения: {e}")
        else:
            self.hosts_buffer.set_text(f"Файл {fpath} не существует.")

    def save_hosts_file_content(self):
        k = self.combo_file.get_active_id() or "hosts"
        fpath = self.hosts_files.get(k)
        start_iter = self.hosts_buffer.get_start_iter()
        end_iter = self.hosts_buffer.get_end_iter()
        text = self.hosts_buffer.get_text(start_iter, end_iter, False)
        try:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write(text)
            self.show_dialog("Сохранение", f"Файл {os.path.basename(fpath)} успешно сохранен.")
        except Exception as e:
            self.show_dialog("Ошибка", f"Не удалось сохранить файл: {e}")

    def on_ai_hosts_toggled(self, switch, _):
        if self._syncing_ai_hosts:
            return
        active = switch.get_active()
        self.enable_ai_hosts = active
        self._syncing_ai_hosts = True
        try:
            if hasattr(self, "sw_ai_hosts") and self.sw_ai_hosts != switch:
                self.sw_ai_hosts.set_active(active)
            if hasattr(self, "sw_ai_master") and self.sw_ai_master != switch:
                self.sw_ai_master.set_active(active)
        finally:
            self._syncing_ai_hosts = False
        self.save_config()
        threading.Thread(target=lambda: run_engine("hosts", "1" if active else "0"), daemon=True).start()

    def on_build_ipset_clicked(self, _):
        self.btn_ip2net.set_sensitive(False)
        self.btn_ip2net.set_label("⏳ Обработка доменов...")

        def worker():
            res = run_engine("ip2net")
            out = res.stdout.strip() if res.stdout else res.stderr.strip()

            def finish():
                self.btn_ip2net.set_sensitive(True)
                self.btn_ip2net.set_label("🌐 Собрать IP-подсети (mdig + ip2net)")
                if res.returncode == 0:
                    self.show_dialog("Сбор подсетей завершен", f"Подсети успешно сгенерированы и сохранены в /etc/zapret/ipset-general.txt!\n\n{out}")
                else:
                    self.show_dialog("Ошибка", f"Не удалось собрать подсети:\n{out}")
            GLib.idle_add(finish)

        threading.Thread(target=worker, daemon=True).start()

    def apply_hosts_now(self):
        run_engine("hosts", "1")
        self.show_dialog("Успех", "База Smart Proxy успешно применена в /etc/hosts!")

    def clean_hosts_now(self):
        run_engine("clean_hosts")
        self.show_dialog("Очистка", "Записи Zapret успешно удалены из /etc/hosts.")

    # ================= PAGE 8: UPDATES & SYNC =================
    def create_updates_page(self):
        page, vbox = self.create_page_container(
            "Обновления баз Zapret 2",
            "Автоматическая загрузка актуальных списков доменов и бинарных fakes из релизов Forgejo"
        )

        meta = get_update_meta()

        # Status Card
        card_status = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        card_status.get_style_context().add_class("fluent-card")

        b_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        b_info.pack_start(Gtk.Label(label="<b>Статус базы данных Zapret 2</b>", use_markup=True, xalign=0), False, False, 0)
        self.lbl_upd_ver = Gtk.Label(label=f"Версия баз: v{meta.get('version', __version__)}", xalign=0)
        self.lbl_upd_time = Gtk.Label(label=f"Последняя синхронизация: {meta.get('last_sync', 'Не выполнялось')}", xalign=0)
        self.lbl_upd_counts = Gtk.Label(label=f"Fakes: {meta.get('fakes_count', 98)}  •  Списки: {meta.get('lists_count', 132)}  •  Пресеты: {meta.get('presets_count', 136)}  •  Lua: {meta.get('lua_count', 19)}", xalign=0)

        b_info.pack_start(self.lbl_upd_ver, False, False, 0)
        b_info.pack_start(self.lbl_upd_time, False, False, 0)
        b_info.pack_start(self.lbl_upd_counts, False, False, 0)
        card_status.pack_start(b_info, True, True, 0)

        b_acts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.btn_check_upd = Gtk.Button(label="🔍 Проверить релиз")
        self.btn_check_upd.get_style_context().add_class("fluent-btn-secondary")
        self.btn_check_upd.connect("clicked", lambda _: self.on_check_updates())
        b_acts.pack_start(self.btn_check_upd, False, False, 0)

        self.btn_sync_now = Gtk.Button(label="⚡ Синхронизировать базы")
        self.btn_sync_now.get_style_context().add_class("fluent-btn-primary")
        self.btn_sync_now.connect("clicked", lambda _: self.on_start_sync())
        b_acts.pack_start(self.btn_sync_now, False, False, 0)
        card_status.pack_end(b_acts, False, False, 0)

        vbox.pack_start(card_status, False, False, 0)

        # Mirrors Grid Card
        card_mirrors = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card_mirrors.get_style_context().add_class("fluent-card")
        card_mirrors.pack_start(Gtk.Label(label="<b>Зеркала обновлений Zapret 2 (Forgejo)</b>", use_markup=True, xalign=0), False, False, 0)

        self.grid_mirrors = Gtk.Grid()
        self.grid_mirrors.set_column_spacing(16)
        self.grid_mirrors.set_row_spacing(6)
        self.mirror_labels = {}

        mirrors = [
            ("git2", "git2.zapret.moe (Основное зеркало)", "https://git2.zapret.moe"),
            ("git3", "git3.zapret.moe (Резервное зеркало 1)", "https://git3.zapret.moe"),
            ("git", "git.zapret.moe (Резервное зеркало 2)", "https://git.zapret.moe")
        ]
        for idx, (m_id, name, url) in enumerate(mirrors):
            lbl_name = Gtk.Label(label=name, xalign=0)
            lbl_badge = Gtk.Label(label="Проверяется...")
            lbl_badge.get_style_context().add_class("badge-neutral")
            self.mirror_labels[m_id] = lbl_badge

            self.grid_mirrors.attach(lbl_name, 0, idx, 1, 1)
            self.grid_mirrors.attach(lbl_badge, 1, idx, 1, 1)

        card_mirrors.pack_start(self.grid_mirrors, False, False, 0)
        vbox.pack_start(card_mirrors, False, False, 0)

        # Progress Bar & Live Log
        card_log = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card_log.get_style_context().add_class("fluent-card")
        card_log.pack_start(Gtk.Label(label="<b>Журнал синхронизации баз</b>", use_markup=True, xalign=0), False, False, 0)

        self.progress_upd = Gtk.ProgressBar()
        self.progress_upd.set_fraction(0.0)
        self.progress_upd.set_text("Готов к синхронизации")
        self.progress_upd.set_show_text(True)
        card_log.pack_start(self.progress_upd, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_size_request(-1, 160)
        self.upd_buffer = Gtk.TextBuffer()
        self.upd_text = Gtk.TextView(buffer=self.upd_buffer)
        self.upd_text.get_style_context().add_class("log-view")
        self.upd_text.set_editable(False)
        scroller.add(self.upd_text)
        card_log.pack_start(scroller, True, True, 0)

        vbox.pack_start(card_log, False, False, 0)

        GLib.timeout_add(1000, self.probe_mirrors_async)
        return page

    def probe_mirrors_async(self):
        def worker():
            res = self.updater.probe_mirrors()
            for r in res:
                m_str = r["mirror"]
                key = "git2" if "git2" in m_str else ("git3" if "git3" in m_str else "git")
                if r["ok"]:
                    txt = f"Доступно ({r['latency_ms']} ms)"
                    cls = "badge-ok"
                else:
                    txt = "Недоступно (таймаут)"
                    cls = "badge-bad"
                GLib.idle_add(self.update_mirror_badge, key, txt, cls)
        threading.Thread(target=worker, daemon=True).start()
        return False

    def update_mirror_badge(self, m_id, text, css_cls):
        badge = self.mirror_labels.get(m_id)
        if badge:
            badge.set_text(text)
            for c in ["badge-neutral", "badge-ok", "badge-warn", "badge-bad"]:
                badge.get_style_context().remove_class(c)
            badge.get_style_context().add_class(css_cls)

    def on_check_updates(self):
        self.btn_check_upd.set_sensitive(False)
        def worker():
            try:
                info = self.updater.fetch_latest_release_info()
                tag = info.get("tag_name", __version__)
                mirror = info.get("mirror", "")
                m_txt = f"Найдена версия {tag} на {mirror}!\nДата релиза: {info.get('published_at', '')[:10]}"
                GLib.idle_add(self.show_dialog, "Проверка обновлений", m_txt)
            except Exception as e:
                GLib.idle_add(self.show_dialog, "Ошибка проверки", f"Не удалось связаться с зеркалами: {e}")
            finally:
                GLib.idle_add(lambda: self.btn_check_upd.set_sensitive(True))
        threading.Thread(target=worker, daemon=True).start()

    def on_start_sync(self):
        self.btn_sync_now.set_sensitive(False)
        self.btn_check_upd.set_sensitive(False)
        self.progress_upd.set_fraction(0.0)
        self.upd_buffer.set_text("Начало синхронизации баз Zapret 2...\n")

        def append_log(line, percent=None):
            end_iter = self.upd_buffer.get_end_iter()
            self.upd_buffer.insert(end_iter, line + "\n")
            if percent is not None:
                self.progress_upd.set_fraction(percent)
                self.progress_upd.set_text(f"{int(percent * 100)}%")

        def worker():
            try:
                meta = self.updater.sync_bases_and_fakes(
                    progress_callback=lambda msg, percent=None: GLib.idle_add(append_log, msg, percent)
                )
                GLib.idle_add(append_log, "Синхронизация /etc/zapret/ с правами root...")
                run_engine("sync")

                if self.is_running:
                    GLib.idle_add(append_log, "Перезапуск активного десинхронизатора...")
                    run_engine(*self.engine_command("restart"))

                GLib.idle_add(append_log, "✅ Базы и бинарные fakes успешно обновлены!")
                GLib.idle_add(self.progress_upd.set_fraction, 1.0)
                GLib.idle_add(self.progress_upd.set_text, "Готово 100%")
                GLib.idle_add(self.lbl_upd_ver.set_text, f"Версия баз: v{meta['version']}")
                GLib.idle_add(self.lbl_upd_time.set_text, f"Последняя синхронизация: {meta['last_sync']}")
                GLib.idle_add(self.lbl_upd_counts.set_text, f"Fakes: {meta['fakes_count']}  •  Списки: {meta['lists_count']}  •  Пресеты: {meta.get('presets_count', 136)}  •  Lua: {meta.get('lua_count', 19)}")
                if hasattr(self, "top_tile_ver"):
                    GLib.idle_add(self.top_tile_ver.set_text, f"v{meta['version']}")
            except Exception as e:
                GLib.idle_add(append_log, f"❌ Ошибка синхронизации: {e}")
            finally:
                GLib.idle_add(lambda: self.btn_sync_now.set_sensitive(True))
                GLib.idle_add(lambda: self.btn_check_upd.set_sensitive(True))

        threading.Thread(target=worker, daemon=True).start()

    # ================= PAGE 9: BLOCKCHECK & DIAGNOSTICS =================
    def create_blockcheck_page(self):
        page, vbox = self.create_page_container(
            "BlockCheck & Диагностика",
            "Тестирование доступности заблокированных ресурсов и обнаружение активных стратегий ТСПУ"
        )

        card_check = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        card_check.get_style_context().add_class("fluent-card")

        h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        h_box.pack_start(Gtk.Label(label="<b>Экспресс-проверка доступности ресурсов</b>", use_markup=True, xalign=0), True, True, 0)

        self.btn_auto_preset = Gtk.Button(label="⚡ Автоподбор лучшего пресета")
        self.btn_auto_preset.get_style_context().add_class("fluent-btn-secondary")
        self.btn_auto_preset.connect("clicked", self.on_auto_preset_clicked)
        h_box.pack_end(self.btn_auto_preset, False, False, 0)

        self.btn_run_check = Gtk.Button(label="🚀 Запустить диагностику")
        self.btn_run_check.get_style_context().add_class("fluent-btn-primary")
        self.btn_run_check.connect("clicked", self.on_run_blockcheck)
        h_box.pack_end(self.btn_run_check, False, False, 0)
        card_check.pack_start(h_box, False, False, 0)

        self.check_targets = [
            ("youtube", "YouTube Главная", "https://www.youtube.com", {}),
            ("googlevideo", "YouTube Video Stream (googlevideo)", "https://redirector.googlevideo.com", {}),
            ("discord", "Discord API Gateway", "https://discord.com/api/v9/experiments", {}),
            ("nnmclub", "NNM-Club (Торрент-трекер)", "https://nnmclub.to", {}),
            ("rutracker", "RuTracker Org", "https://rutracker.org", {}),
            ("cloudflare", "Cloudflare DNS over HTTPS", "https://1.1.1.1/dns-query?name=cloudflare.com&type=A", {"Accept": "application/dns-json"}),
            ("openai", "OpenAI ChatGPT API", "https://api.openai.com/v1/models", {}),
            ("telegram", "Telegram Web App", "https://web.telegram.org", {})
        ]

        self.check_badges = {}
        grid = Gtk.Grid()
        grid.set_column_spacing(16)
        grid.set_row_spacing(8)
        grid.set_column_homogeneous(True)

        col = 0
        row = 0
        for key, name, url, headers in self.check_targets:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
            box.get_style_context().add_class("fluent-tile")
            box.pack_start(Gtk.Label(label=name, xalign=0), False, False, 0)
            badge = Gtk.Label(label="Не проверялось")
            badge.get_style_context().add_class("badge-neutral")
            badge.set_xalign(0)
            self.check_badges[key] = badge
            box.pack_start(badge, False, False, 0)

            grid.attach(box, col, row, 1, 1)
            col += 1
            if col > 1:
                col = 0
                row += 1

        card_check.pack_start(grid, False, False, 0)
        vbox.pack_start(card_check, False, False, 0)

        native = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        native.get_style_context().add_class("fluent-card")
        native.pack_start(Gtk.Label(label="<b>Настоящий Blockcheck2 (nfqws2)</b>", use_markup=True, xalign=0), False, False, 0)
        native.pack_start(Gtk.Label(label="Перебор TLS-стратегий автора Zapret2. Лимит 15 минут. На время теста текущий обход останавливается, затем восстанавливается.", xalign=0), False, False, 0)
        native_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.blockcheck2_domain = Gtk.Entry()
        self.blockcheck2_domain.set_text("rutracker.org")
        native_row.pack_start(self.blockcheck2_domain, True, True, 0)
        self.btn_blockcheck2 = Gtk.Button(label="Запустить Blockcheck2")
        self.btn_blockcheck2.get_style_context().add_class("fluent-btn-secondary")
        self.btn_blockcheck2.connect("clicked", self.on_blockcheck2)
        native_row.pack_start(self.btn_blockcheck2, False, False, 0)
        native.pack_start(native_row, False, False, 0)
        scroll = Gtk.ScrolledWindow()
        scroll.set_size_request(-1, 170)
        self.blockcheck2_buffer = Gtk.TextBuffer()
        output = Gtk.TextView(buffer=self.blockcheck2_buffer)
        output.set_editable(False)
        output.set_monospace(True)
        scroll.add(output)
        native.pack_start(scroll, True, True, 0)
        vbox.pack_start(native, False, False, 0)

        return page

    def on_blockcheck2(self, _):
        domain = self.blockcheck2_domain.get_text().strip()
        self.btn_blockcheck2.set_sensitive(False)
        self.blockcheck2_buffer.set_text("Подготовка Blockcheck2. Текущий движок будет остановлен...\n")
        was_running = self.is_running
        restore = self.engine_command()

        def worker():
            restore_error = ""
            try:
                if was_running:
                    stopped = run_engine("stop", self.active_iface)
                    if stopped.returncode != 0:
                        raise RuntimeError("Не удалось остановить движок:\n" + (stopped.stderr or stopped.stdout))
                result = run_engine("blockcheck2", domain, self.active_iface, self.active_dns)
                output = (result.stdout + result.stderr).strip()
                if result.returncode == 124:
                    output = "ВНИМАНИЕ: лимит 15 минут исчерпан. Ниже частичный результат, перебор не завершён.\n\n" + output
                elif result.returncode != 0:
                    output = f"ОШИБКА: Blockcheck2 завершился с кодом {result.returncode}.\n\n" + output
            except Exception as exc:
                output = "ОШИБКА ЗАПУСКА BLOCKCHECK2:\n" + str(exc)
            finally:
                if was_running:
                    try:
                        restored = run_engine(*restore)
                        if restored.returncode != 0:
                            restore_error = "\n\nОШИБКА ВОССТАНОВЛЕНИЯ ДВИЖКА:\n" + (restored.stderr or restored.stdout)
                    except Exception as exc:
                        restore_error = "\n\nОШИБКА ВОССТАНОВЛЕНИЯ ДВИЖКА:\n" + str(exc)
                else:
                    # Движок не был запущен -> обязательно восстанавливаем системный DNS
                    try:
                        run_engine("dns", self.active_iface, "system")
                    except Exception:
                        pass

            def finish():
                self.blockcheck2_buffer.set_text(output[-14000:] + restore_error)
                self.btn_blockcheck2.set_sensitive(True)
                self.refresh_status()
            GLib.idle_add(finish)

        threading.Thread(target=worker, daemon=True).start()

    def on_auto_preset_clicked(self, _):
        self.btn_auto_preset.set_sensitive(False)
        self.btn_run_check.set_sensitive(False)
        self.btn_auto_preset.set_label("⏳ Подбор пресета...")

        is_zapret2 = getattr(self, "engine_mode", "nfqws2") == "nfqws2"
        if is_zapret2:
            candidate_presets = [
                "general ALT",
                "Default (circular)",
                "general FAKE TLS AUTO",
                "ALL TCP & UDP hostfakesplit"
            ]
        else:
            candidate_presets = ["general", "youtube_discord", "alt_fakedsplit", "alt_split", "multidisorder"]

        markers = [
            ("youtube", "https://www.youtube.com/generate_204"),
            ("googlevideo", "https://redirector.googlevideo.com/report_mapping"),
            ("discord", "https://discord.com/api/v10/gateway"),
            ("rutracker", "https://rutracker.org"),
        ]

        def test_marker(url, key):
            t0 = time.time()
            try:
                req = urllib.request.Request(
                    url,
                    headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}
                )
                with urllib.request.urlopen(req, timeout=3.5) as res:
                    st = res.status
                    dt = int((time.time() - t0) * 1000)
                    if 200 <= st < 400:
                        return True, dt
                    return False, dt
            except urllib.error.HTTPError as e:
                dt = int((time.time() - t0) * 1000)
                # Any HTTP response code < 500 confirms successful TLS handshake and origin reachability
                if e.code < 500:
                    return True, dt
                return False, dt
            except Exception:
                return False, 9999

        def worker():
            results = {}
            for preset in candidate_presets:
                if is_zapret2:
                    p_title = preset
                    GLib.idle_add(self.btn_auto_preset.set_label, f"⏳ Тест: {p_title}...")
                    run_engine(
                        "start",
                        self.active_preset,
                        self.active_iface,
                        self.active_dns,
                        "1" if self.enable_ai_hosts else "0",
                        "1" if self.enable_quic else "0",
                        "1" if self.enable_discord_voice else "0",
                        str(self.conntrack_limit),
                        self.hostlist_mode,
                        "nfqws2",
                        self.custom_params,
                        preset,
                        "1" if self.enable_youtube else "0",
                        "1" if self.enable_discord_tcp else "0",
                        "1" if self.enable_general_https else "0",
                    )
                else:
                    p_title = PRESETS.get(preset, {}).get("title", preset).split("(")[0].strip()
                    GLib.idle_add(self.btn_auto_preset.set_label, f"⏳ Тест: {p_title}...")
                    run_engine(
                        "start",
                        preset,
                        self.active_iface,
                        self.active_dns,
                        "1" if self.enable_ai_hosts else "0",
                        "1" if self.enable_quic else "0",
                        "1" if self.enable_discord_voice else "0",
                        str(self.conntrack_limit),
                        self.hostlist_mode,
                        "nfqws",
                        self.custom_params,
                        self.zapret2_preset,
                        "1" if self.enable_youtube else "0",
                        "1" if self.enable_discord_tcp else "0",
                        "1" if self.enable_general_https else "0",
                    )
                time.sleep(1.2)

                ok_count = 0
                latencies = []
                for key, url in markers:
                    ok, lat = test_marker(url, key)
                    if ok:
                        ok_count += 1
                        latencies.append(lat)

                avg_lat = int(sum(latencies) / len(latencies)) if latencies else 9999
                results[preset] = {
                    "ok_count": ok_count,
                    "avg_lat": avg_lat
                }

            best_preset = max(
                candidate_presets,
                key=lambda p: (results[p]["ok_count"], -results[p]["avg_lat"])
            )

            if is_zapret2:
                self.zapret2_preset = best_preset
                self.engine_mode = "nfqws2"
                best_title = best_preset
            else:
                self.active_preset = best_preset
                self.engine_mode = "nfqws"
                best_title = PRESETS.get(best_preset, {}).get("title", best_preset)

            self.save_config()
            run_engine(*self.engine_command())

            report_lines = [
                f"🏆 Выбран лучший пресет: {best_title}",
                f"Доступно сервисов: {results[best_preset]['ok_count']}/{len(markers)}, ср. задержка: {results[best_preset]['avg_lat']} ms\n",
                "Сводка по всем протестированным стратегиям:"
            ]
            for p in candidate_presets:
                res = results[p]
                icon = "⭐" if p == best_preset else "•"
                p_label = p if is_zapret2 else PRESETS.get(p, {}).get("title", p)
                report_lines.append(f"{icon} {p_label}: {res['ok_count']}/{len(markers)} доступно (ср. пинг {res['avg_lat']} ms)")

            def finish():
                self.btn_auto_preset.set_sensitive(True)
                self.btn_run_check.set_sensitive(True)
                self.btn_auto_preset.set_label("⚡ Автоподбор лучшего пресета")

                if is_zapret2:
                    if hasattr(self, "top_tile_preset"):
                        self.top_tile_preset.set_text(best_preset)
                    if hasattr(self, "pill_preset"):
                        self.pill_preset.set_text(f"⚡ {best_preset}")
                    if hasattr(self, "combo_engine_mode"):
                        self.combo_engine_mode.set_active_id("nfqws2")
                    if hasattr(self, "zapret2_page") and self.zapret2_page:
                        self.zapret2_page.preset_id = best_preset
                        self.zapret2_page.refresh_catalog()
                else:
                    if hasattr(self, "preset_radios") and best_preset in self.preset_radios:
                        self.preset_radios[best_preset].set_active(True)
                    if hasattr(self, "top_tile_preset"):
                        self.top_tile_preset.set_text(PRESETS.get(best_preset, {}).get("title", best_preset).split("(")[0].strip())
                    if hasattr(self, "pill_preset"):
                        self.pill_preset.set_text(f"⚡ {PRESETS.get(best_preset, {}).get('title', best_preset)}")
                    if hasattr(self, "combo_engine_mode"):
                        self.combo_engine_mode.set_active_id("nfqws")

                self.update_top_tile_mode()
                self.refresh_status()
                self.show_dialog("Автоподбор завершен", "\n".join(report_lines))

            GLib.idle_add(finish)

        threading.Thread(target=worker, daemon=True).start()

    def on_run_blockcheck(self, _):
        self.btn_run_check.set_sensitive(False)
        for b in self.check_badges.values():
            b.set_text("Проверка...")
            for c in ["badge-ok", "badge-warn", "badge-bad"]:
                b.get_style_context().remove_class(c)
            b.get_style_context().add_class("badge-neutral")

        def worker():
            for key, name, url, extra_headers in self.check_targets:
                t0 = time.time()
                try:
                    req_headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}
                    req_headers.update(extra_headers)
                    req = urllib.request.Request(url, headers=req_headers)
                    with urllib.request.urlopen(req, timeout=4.0) as res:
                        st = res.status
                        dt = int((time.time() - t0) * 1000)
                        if st in (200, 301, 302, 307):
                            txt = f"Доступен ({st}, {dt} ms)"
                            cls = "badge-ok"
                        else:
                            txt = f"Ответ {st} ({dt} ms)"
                            cls = "badge-warn"
                        GLib.idle_add(self.update_check_badge, self.check_badges[key], txt, cls)
                except urllib.error.HTTPError as e:
                    dt = int((time.time() - t0) * 1000)
                    if key == "googlevideo" and e.code in (400, 404):
                        txt = f"Доступен (CDN OK, {dt} ms)"
                        cls = "badge-ok"
                    elif key == "openai" and e.code in (401, 403):
                        txt = f"Доступен (API OK, {dt} ms)"
                        cls = "badge-ok"
                    elif e.code in (200, 301, 302, 307):
                        txt = f"Доступен ({e.code}, {dt} ms)"
                        cls = "badge-ok"
                    elif e.code in (400, 401, 403, 405):
                        txt = f"Ответ HTTP {e.code} ({dt} ms)"
                        cls = "badge-warn"
                    else:
                        txt = f"HTTP {e.code} ({dt} ms)"
                        cls = "badge-bad"
                    GLib.idle_add(self.update_check_badge, self.check_badges[key], txt, cls)
                except Exception as e:
                    GLib.idle_add(self.update_check_badge, self.check_badges[key], "Заблокирован / Таймаут", "badge-bad")

            GLib.idle_add(lambda: self.btn_run_check.set_sensitive(True))
        threading.Thread(target=worker, daemon=True).start()

    def update_check_badge(self, badge, text, css_cls):
        badge.set_text(text)
        for c in ["badge-neutral", "badge-ok", "badge-warn", "badge-bad"]:
            badge.get_style_context().remove_class(c)
        badge.get_style_context().add_class(css_cls)

    # ================= PAGE 10: LOGS =================
    def create_logs_page(self):
        page, vbox = self.create_page_container(
            "Журнал работы (Логи)",
            "Логи работы nfqws, сетевых интерфейсов и скрипта engine.sh в реальном времени"
        )

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("fluent-card")

        h_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        h_box.pack_start(Gtk.Label(label="<b>Лог /tmp/zapret-gui.log:</b>", use_markup=True, xalign=0), True, True, 0)
        btn_refresh = Gtk.Button(label="🔄 Обновить лог")
        btn_refresh.get_style_context().add_class("fluent-btn-secondary")
        btn_refresh.connect("clicked", lambda _: self.read_log_file())
        h_box.pack_end(btn_refresh, False, False, 0)
        card.pack_start(h_box, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_size_request(-1, 380)
        self.log_buffer = Gtk.TextBuffer()
        self.log_view = Gtk.TextView(buffer=self.log_buffer)
        self.log_view.get_style_context().add_class("log-view")
        self.log_view.set_editable(False)
        scroller.add(self.log_view)
        card.pack_start(scroller, True, True, 0)

        vbox.pack_start(card, False, False, 0)
        self.read_log_file()
        return page

    def read_log_file(self):
        if os.path.exists(LOG_FILE):
            try:
                with open(LOG_FILE, "r", encoding="utf-8", errors="ignore") as f:
                    lines = f.readlines()
                    tail = "".join(lines[-150:])
                    self.log_buffer.set_text(tail)
            except Exception as e:
                self.log_buffer.set_text(f"Ошибка чтения лога: {e}")
        else:
            self.log_buffer.set_text("Лог-файл пуст или служба еще не запускалась.")

    # ================= PAGE 11: SETTINGS =================
    def create_settings_page(self):
        page, vbox = self.create_page_container(
            "Настройки программы",
            "Параметры сетевого интерфейса, автозагрузки и системных служб"
        )

        card_iface = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card_iface.get_style_context().add_class("fluent-card")
        card_iface.pack_start(Gtk.Label(label="<b>Сетевой адаптер (Interface)</b>", use_markup=True, xalign=0), False, False, 0)

        self.combo_iface = Gtk.ComboBoxText()
        self.populate_iface_combo(self.combo_iface)
        self.combo_iface.connect("changed", self.on_iface_changed)
        card_iface.pack_start(self.combo_iface, False, False, 0)
        vbox.pack_start(card_iface, False, False, 0)

        # Autostart Card
        card_auto = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        card_auto.get_style_context().add_class("fluent-card")
        a_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        a_info.pack_start(Gtk.Label(label="<b>Автозапуск при входе в сессию Linux</b>", use_markup=True, xalign=0), False, False, 0)
        a_info.pack_start(Gtk.Label(label="Создает файл ~/.config/autostart/zapret-gui.desktop для фонового запуска", xalign=0), False, False, 0)
        card_auto.pack_start(a_info, True, True, 0)

        self.sw_settings_autostart = Gtk.Switch()
        self.sw_settings_autostart.set_active(os.path.exists(AUTOSTART_FILE))
        self.sw_settings_autostart.set_halign(Gtk.Align.END)
        self.sw_settings_autostart.set_valign(Gtk.Align.CENTER)
        self.sw_settings_autostart.connect("notify::active", self.on_autostart_toggled)
        card_auto.pack_end(self.sw_settings_autostart, False, False, 0)
        vbox.pack_start(card_auto, False, False, 0)

        # Polkit / Sudoers Card
        card_polkit = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        card_polkit.get_style_context().add_class("fluent-card")
        p_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        p_info.pack_start(Gtk.Label(label="<b>Беспарольный запуск (Polkit &amp; Sudoers)</b>", use_markup=True, xalign=0), False, False, 0)
        p_info.pack_start(Gtk.Label(label="Устанавливает правило в /etc/sudoers.d/ и policykit для мгновенного запуска без окон пароля", xalign=0), False, False, 0)
        card_polkit.pack_start(p_info, True, True, 0)

        btn_polkit = Gtk.Button(label="🛡️ Установить права")
        btn_polkit.get_style_context().add_class("fluent-btn-secondary")
        btn_polkit.connect("clicked", lambda _: self.install_polkit_action())
        btn_polkit.set_valign(Gtk.Align.CENTER)
        card_polkit.pack_end(btn_polkit, False, False, 0)
        vbox.pack_start(card_polkit, False, False, 0)

        # Auto-Healer Card
        card_healer = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        card_healer.get_style_context().add_class("fluent-card")
        h_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        h_info.pack_start(Gtk.Label(label="<b>🩹 Auto-Healing Daemon</b>", use_markup=True, xalign=0), False, False, 0)
        h_info.pack_start(Gtk.Label(label="Автоматически проверяет доступность сервисов и перезапускает обход при сбоях", xalign=0), False, False, 0)
        card_healer.pack_start(h_info, True, True, 0)

        self.sw_healer = Gtk.Switch()
        self.sw_healer.set_active(self.healer_enabled)
        self.sw_healer.set_halign(Gtk.Align.END)
        self.sw_healer.set_valign(Gtk.Align.CENTER)
        self.sw_healer.connect("notify::active", self.on_healer_toggled)
        card_healer.pack_end(self.sw_healer, False, False, 0)
        vbox.pack_start(card_healer, False, False, 0)

        # Healer Status
        h_status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        h_status_box.set_margin_start(16)
        h_status_box.set_margin_bottom(8)
        self.healer_status_label = Gtk.Label(label="🟢 Ожидание проверки...")
        self.healer_status_label.set_xalign(0)
        h_status_box.pack_start(self.healer_status_label, False, False, 0)
        vbox.pack_start(h_status_box, False, False, 0)

        # System Details Card
        about_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        about_card.get_style_context().add_class("fluent-card")
        about_card.pack_start(Gtk.Label(label="<b>О программе</b>", use_markup=True, xalign=0), False, False, 0)
        about_card.pack_start(Gtk.Label(label=APP_DESCRIPTION, xalign=0), False, False, 0)
        mode_text = "🛡️ Системный режим (/usr)" if getattr(self, "is_system_mode", False) else "📦 Портативный режим (запуск из каталога пользователя)"
        about_card.pack_start(Gtk.Label(label=f"Режим установки: {mode_text}", xalign=0), False, False, 0)
        about_card.pack_start(Gtk.Label(label="Ядра: nfqws2 + Lua, nfqws / tpws v72.13; брандмауэр: nftables", xalign=0), False, False, 0)
        about_card.pack_start(Gtk.Label(label="Синхронизация списков: Forgejo git2.zapret.moe (Zapret 2 Community)", xalign=0), False, False, 0)
        vbox.pack_start(about_card, False, False, 0)

        return page

    def install_polkit_action(self):
        def worker():
            res = run_engine("install_polkit")
            out = res.stdout.strip() if res.stdout else res.stderr.strip()
            def finish():
                if res.returncode == 0:
                    self.show_dialog("Успех", f"Polkit настроен, старое правило NOPASSWD удалено:\n{out}")
                else:
                    self.show_dialog("Ошибка", f"Не удалось настроить Polkit:\n{out}")
            GLib.idle_add(finish)
        threading.Thread(target=worker, daemon=True).start()

    # ================= ENGINE CONTROLLER =================
    def refresh_status(self):
        if getattr(self, "_refreshing_status", False):
            return False
        self._refreshing_status = True

        def worker():
            try:
                res = subprocess.run([ENGINE_SH, "status"], capture_output=True, text=True, timeout=2)
                out = res.stdout.strip()
                GLib.idle_add(self._apply_status, out)
            except Exception:
                pass
            finally:
                self._refreshing_status = False
        threading.Thread(target=worker, daemon=True).start()
        return False

    def _apply_status(self, out):
        if out == "ACTIVE":
            self.is_running = True
            mode_title = {"tpws": "TPWS", "nfqws2": "nfqws2 + Lua"}.get(self.engine_mode, "nfqws v1")
            self.status_title.set_markup(f"<span font='15' weight='bold' color='#34d399'>🟢 Движок запущен ({mode_title})</span>")
            self.status_desc.set_text("Процесс и правила перехвата активны. Доступность сервисов проверяется отдельно в диагностике.")
            self.btn_toggle.set_label("■ Остановить обход")
            self.btn_toggle.get_style_context().remove_class("fluent-btn-primary")
            self.btn_toggle.get_style_context().add_class("fluent-btn-danger")

            self.status_banner.get_style_context().remove_class("status-banner-inactive")
            self.status_banner.get_style_context().add_class("status-banner-active")

            self.pill_status.set_text("● Обход DPI активен")
            self.pill_status.get_style_context().remove_class("badge-bad")
            self.pill_status.get_style_context().remove_class("badge-warn")
            self.pill_status.get_style_context().add_class("badge-ok")
            self.update_tray(True)
        elif out == "NFQWS_ONLY":
            self.is_running = True
            mode_title = {"tpws": "TPWS", "nfqws2": "nfqws2 + Lua"}.get(self.engine_mode, "nfqws v1")
            self.status_title.set_markup(f"<span font='15' weight='bold' color='#f59e0b'>🟡 Движок запущен • Правила nftables отсутствуют ({mode_title})</span>")
            self.status_desc.set_text("Процесс десинхронизатора активен, но правила перехвата трафика не найдены.")
            self.btn_toggle.set_label("■ Остановить обход")
            self.btn_toggle.get_style_context().remove_class("fluent-btn-primary")
            self.btn_toggle.get_style_context().add_class("fluent-btn-danger")

            self.status_banner.get_style_context().remove_class("status-banner-inactive")
            self.status_banner.get_style_context().add_class("status-banner-active")

            self.pill_status.set_text("● NFQWS без nftables")
            self.pill_status.get_style_context().remove_class("badge-bad")
            self.pill_status.get_style_context().remove_class("badge-ok")
            self.pill_status.get_style_context().add_class("badge-warn")
            self.update_tray(True)
        else:
            self.is_running = False
            self.status_title.set_markup("<span font='15' weight='bold' color='#f87171'>○ Zapret остановлен • Обход выключен</span>")
            self.status_desc.set_text("Нажмите «Запустить обход», чтобы включить десинхронизацию для YouTube и Discord.")
            self.btn_toggle.set_label("▶ Запустить обход")
            self.btn_toggle.get_style_context().remove_class("fluent-btn-danger")
            self.btn_toggle.get_style_context().add_class("fluent-btn-primary")

            self.status_banner.get_style_context().remove_class("status-banner-active")
            self.status_banner.get_style_context().add_class("status-banner-inactive")

            self.pill_status.set_text("○ Обход DPI выключен")
            self.pill_status.get_style_context().remove_class("badge-ok")
            self.pill_status.get_style_context().remove_class("badge-warn")
            self.pill_status.get_style_context().add_class("badge-bad")
            self.update_tray(False)

    def on_iface_changed(self, combo):
        if self._syncing_iface:
            return
        val = combo.get_active_id() or (combo.get_active_text().split()[0] if combo.get_active_text() else "any")
        self.active_iface = val
        self._syncing_iface = True
        try:
            other = self.combo_iface if combo == self.combo_iface_quick else self.combo_iface_quick
            if other and other.get_active_id() != val:
                other.set_active_id(val)
        finally:
            self._syncing_iface = False
        self.save_config()
        if hasattr(self, "lbl_iface_quick_desc"):
            self.lbl_iface_quick_desc.set_text(f"Фильтрация исходящего сетевого трафика на адаптере (текущий: {self.active_iface})")
        if hasattr(self, "lbl_net_iface"):
            self.refresh_network_monitor()
        if self.is_running:
            self.restart_engine()

    def on_toggle_engine(self, _):
        if self.is_running:
            self.stop_engine()
        else:
            self.start_engine()

    def engine_command(self, command="start"):
        return (
            command, self.active_preset, self.active_iface, self.active_dns,
            "1" if self.enable_ai_hosts else "0",
            "1" if self.enable_quic else "0",
            "1" if self.enable_discord_voice else "0",
            str(self.conntrack_limit), self.hostlist_mode, self.engine_mode,
            self.custom_params, self.zapret2_preset,
            "1" if self.enable_youtube else "0",
            "1" if self.enable_discord_tcp else "0",
            "1" if self.enable_general_https else "0",
        )

    def start_engine(self):
        self.btn_toggle.set_sensitive(False)
        arguments = self.engine_command()

        def worker():
            result = run_engine(*arguments)
            def finish():
                self.btn_toggle.set_sensitive(True)
                self.refresh_status()
                if result.returncode != 0:
                    output = (result.stderr or result.stdout).strip()
                    self.show_dialog("Движок не запущен", output[-4000:])
            GLib.idle_add(finish)
        threading.Thread(target=worker, daemon=True).start()

    def stop_engine(self):
        self.btn_toggle.set_sensitive(False)
        def worker():
            run_engine("stop", self.active_iface)
            GLib.idle_add(lambda: self.btn_toggle.set_sensitive(True))
            GLib.idle_add(lambda: self.refresh_status())
        threading.Thread(target=worker, daemon=True).start()

    def restart_engine(self):
        self.start_engine()

    def switch_to_tab(self, name):
        if name in self.nav_buttons:
            self.nav_buttons[name].set_active(True)

    def on_autostart_toggled(self, switch, _):
        if self._syncing_autostart:
            return
        active = switch.get_active()
        self._syncing_autostart = True
        try:
            if hasattr(self, "sw_autostart") and self.sw_autostart != switch:
                self.sw_autostart.set_active(active)
            if hasattr(self, "sw_settings_autostart") and self.sw_settings_autostart != switch:
                self.sw_settings_autostart.set_active(active)
        finally:
            self._syncing_autostart = False

        os.makedirs(os.path.dirname(AUTOSTART_FILE), exist_ok=True)
        if active:
            main_py_path = os.path.join(APP_DIR, "main.py")
            content = f"""[Desktop Entry]
Type=Application
Name=Zapret 2 GUI
Comment=Zapret 2 DPI bypass for Arch Linux
Exec=/usr/bin/python3 {main_py_path} --minimized
Icon=network-vpn
Terminal=false
Categories=Network;Security;
X-GNOME-Autostart-enabled=true
"""
            with open(AUTOSTART_FILE, "w", encoding="utf-8") as f:
                f.write(content)
        else:
            if os.path.exists(AUTOSTART_FILE):
                os.remove(AUTOSTART_FILE)

    def setup_tray(self):
        icon_path = os.path.join(APP_DIR, "icon.svg")
        if not os.path.exists(icon_path):
            icon_path = "network-vpn"

        self.tray_menu = Gtk.Menu()

        self.tray_status_item = Gtk.MenuItem(label="Статус: Остановлен")
        self.tray_status_item.set_sensitive(False)
        self.tray_menu.append(self.tray_status_item)

        self.tray_toggle_item = Gtk.MenuItem(label="▶ Запустить обход")
        self.tray_toggle_item.connect("activate", lambda _: self.on_toggle_engine(None))
        self.tray_menu.append(self.tray_toggle_item)

        self.tray_menu.append(Gtk.SeparatorMenuItem())

        preset_item = Gtk.MenuItem(label="Быстрая смена пресета (Zapret 2)")
        preset_sub = Gtk.Menu()
        z2_top_presets = [
            ("general ALT", "general ALT (Рекомендуемый)"),
            ("Default (circular)", "Default (circular - авторотация)"),
            ("general FAKE TLS AUTO", "general FAKE TLS AUTO"),
            ("ALL TCP & UDP hostfakesplit", "ALL TCP & UDP hostfakesplit"),
        ]
        for z_id, z_title in z2_top_presets:
            it = Gtk.MenuItem(label=z_title)
            it.connect("activate", self.on_tray_z2_preset_selected, z_id)
            preset_sub.append(it)
        preset_item.set_submenu(preset_sub)
        self.tray_menu.append(preset_item)

        self.tray_menu.append(Gtk.SeparatorMenuItem())

        open_item = Gtk.MenuItem(label="Открыть окно")
        open_item.connect("activate", self.on_tray_open_clicked)
        self.tray_menu.append(open_item)

        quit_item = Gtk.MenuItem(label="Выход")
        quit_item.connect("activate", self.quit_app)
        self.tray_menu.append(quit_item)

        self.tray_menu.show_all()

        if AppIndicator is not None:
            try:
                self.indicator = AppIndicator.Indicator.new(
                    "zapret-gui",
                    icon_path,
                    AppIndicator.IndicatorCategory.APPLICATION_STATUS
                )
                if hasattr(self.indicator, "set_icon_theme_path"):
                    self.indicator.set_icon_theme_path(APP_DIR)
                self.indicator.set_status(AppIndicator.IndicatorStatus.ACTIVE)
                self.indicator.set_menu(self.tray_menu)
                return
            except Exception as e:
                print("AppIndicator error:", e)

        try:
            self.status_icon = Gtk.StatusIcon.new_from_file(icon_path) if os.path.exists(icon_path) else Gtk.StatusIcon.new_from_icon_name("network-vpn")
            self.status_icon.connect("popup-menu", self.on_status_icon_popup)
            self.status_icon.connect("activate", lambda _: self.on_tray_open_clicked(None))
            self.status_icon.set_visible(True)
        except Exception as e:
            print("StatusIcon error:", e)

    def on_status_icon_popup(self, icon, button, activate_time):
        self.tray_menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)

    def on_tray_open_clicked(self, _):
        self.show_all()
        self.present()

    def on_tray_z2_preset_selected(self, _, preset_id):
        self.zapret2_preset = preset_id
        self.engine_mode = "nfqws2"
        if hasattr(self, "combo_engine_mode"):
            self.combo_engine_mode.set_active_id("nfqws2")
        self.update_top_tile_mode()
        if hasattr(self, "top_tile_preset"):
            self.top_tile_preset.set_text(preset_id)
        if hasattr(self, "pill_preset"):
            self.pill_preset.set_text(f"⚡ {preset_id}")
        self.save_config()
        if self.is_running:
            self.restart_engine()

    def on_tray_preset_selected(self, _, preset_key):
        self.active_preset = preset_key
        self.engine_mode = "nfqws"
        if hasattr(self, "combo_engine_mode"):
            self.combo_engine_mode.set_active_id("nfqws")
        self.update_top_tile_mode()
        if preset_key in self.preset_radios:
            self.preset_radios[preset_key].set_active(True)
        p_info = PRESETS.get(preset_key, {"title": preset_key})
        if hasattr(self, "top_tile_preset"):
            self.top_tile_preset.set_text(p_info["title"].split("(")[0].strip())
        if hasattr(self, "pill_preset"):
            self.pill_preset.set_text(f"⚡ {p_info['title']}")
        self.save_config()
        if self.is_running:
            self.restart_engine()

    def update_tray(self, running):
        if hasattr(self, "tray_status_item"):
            mode = {"tpws": "TPWS", "nfqws2": "nfqws2"}.get(self.engine_mode, "nfqws")
            self.tray_status_item.set_label(f"Статус: {'Активен (' + mode + ')' if running else 'Выключен'}")
        if hasattr(self, "tray_toggle_item"):
            self.tray_toggle_item.set_label("■ Остановить обход" if running else "▶ Запустить обход")

    def on_delete_event(self, widget, event):
        desktop = (os.environ.get("XDG_CURRENT_DESKTOP") or "").lower()
        if "niri" in desktop or not getattr(self, "minimize_to_tray", True):
            self.quit_app(None)
            return True
        self.hide()
        return True

    def on_mirror_change(self, new_mirror, message):
        """Callback при смене зеркала."""
        def update():
            if hasattr(self, 'healer_status_label'):
                self.healer_status_label.set_text(f"🌐 {message}")
        GLib.idle_add(update)

    def on_healer_status(self, healthy, message):
        """Callback от AutoHealer при изменении статуса."""
        def update():
            if hasattr(self, 'healer_status_label'):
                icon = "🟢" if healthy else "🔴"
                self.healer_status_label.set_text(f"{icon} {message}")
            if not healthy and hasattr(self, 'btn_toggle'):
                # Можно добавить визуальную индикацию проблемы
                pass
        GLib.idle_add(update)

    def on_healer_toggled(self, switch, _):
        self.healer_enabled = switch.get_active()
        self.save_config()
        if self.healer_enabled:
            self.healer.start()
        else:
            self.healer.stop()

    def quit_app(self, _=None):
        self.healer.stop()
        self.mirror_monitor.stop()
        Gtk.main_quit()

    def on_dpi_auto_toggled(self, switch, _):
        self.dpi_auto = switch.get_active()
        self.save_config()

    def show_dialog(self, title, message):
        dialog = Gtk.MessageDialog(
            transient_for=self,
            flags=0,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text=title
        )
        dialog.format_secondary_text(message)
        dialog.run()
        dialog.destroy()


def main():
    if "--version" in sys.argv or "-v" in sys.argv:
        from version import APP_NAME, __version__
        print(f"{APP_NAME} v{__version__}")
        sys.exit(0)
    minimized = "--minimized" in sys.argv
    app = Zapret2App(minimized=minimized)
    app.connect("destroy", Gtk.main_quit)
    if minimized:
        app.show_all()
        app.hide()
    else:
        app.show_all()
    Gtk.main()


if __name__ == "__main__":
    main()

