#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Theme Manager for Zapret GUI Linux.
Provides Dark, Light, and System theme support with modern Fluent / GNOME design,
high-contrast accessible palettes, and full HiDPI support.
"""

from __future__ import annotations
import os
import subprocess
from typing import Optional

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gtk, Gdk
    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False

VALID_THEMES = ("dark", "light", "system")
DEFAULT_THEME = "dark"


def get_system_theme() -> str:
    """
    Detect whether the system prefers a dark or light theme.
    Checks environment override (GTK_THEME), GTK settings, and GNOME color-scheme.
    """
    # 1. Check environment override first (e.g. GTK_THEME=Adwaita:dark or GTK_THEME=Adwaita:light)
    env_theme = os.environ.get("GTK_THEME", "").lower()
    if "dark" in env_theme:
        return "dark"
    if "light" in env_theme:
        return "light"

    # 2. Try GTK Settings if GTK is available and initialized
    if GTK_AVAILABLE:
        try:
            settings = Gtk.Settings.get_default()
            if settings:
                prefer_dark = settings.get_property("gtk-application-prefer-dark-theme")
                if prefer_dark:
                    return "dark"
                theme_name = settings.get_property("gtk-theme-name") or ""
                if "dark" in theme_name.lower():
                    return "dark"
        except Exception:
            pass

    # 3. Try gsettings for GNOME 42+ dark style preference
    try:
        res = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=1,
        )
        if res.returncode == 0:
            val = res.stdout.strip().strip("'\"")
            if "prefer-dark" in val:
                return "dark"
            if "prefer-light" in val or "default" in val:
                return "light"
    except Exception:
        pass

    return "dark"


def resolve_theme(theme_mode: str) -> str:
    """Resolve 'system' into concrete 'dark' or 'light'."""
    mode = (theme_mode or "").strip().lower()
    if mode == "system":
        return get_system_theme()
    if mode in ("dark", "light"):
        return mode
    return DEFAULT_THEME


def get_theme_css(theme_name: str) -> str:
    """
    Generate modern HiDPI CSS for the requested theme mode ('dark', 'light', or 'system').
    Uses vector spacing, scalable fonts, and high-contrast accessible color palettes.
    """
    mode = resolve_theme(theme_name)

    if mode == "light":
        return _build_light_css() + _build_light_overrides()
    return _build_dark_css() + _build_dark_overrides()


def _build_dark_css() -> str:
    """Dark theme: Zapret2 dark palette (#202020 / #242424, text #f2f2f2, accents #00c8d0)."""
    return """
* {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", "Ubuntu", "Cantarell", "Noto Sans", sans-serif;
    outline: none;
    -gtk-dpi: 96;
}

window {
    background-color: #202020;
    color: #f2f2f2;
}

/* Universal button styling */
button {
    background-image: none;
    background-color: #2e2e2e;
    color: #f2f2f2;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 500;
    font-size: 13px;
    transition: all 120ms ease;
    box-shadow: none;
    text-shadow: none;
}

button:hover {
    background-color: #3a3a3a;
    border-color: #4a4a4a;
    color: #ffffff;
}

button:active {
    background-color: #242424;
    border-color: #00c8d0;
}

button:disabled {
    opacity: 0.55;
}

/* Switch styling - prevents stretching deformities */
switch {
    min-width: 44px;
    min-height: 22px;
    border-radius: 12px;
    background-color: #2e2e2e;
    border: 1px solid #3a3a3a;
}

switch:checked {
    background-color: #00adb5;
    border-color: #00c8d0;
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
    background-color: #242424;
    border-right: 1px solid #2e2e2e;
    padding: 12px 6px;
}

.nav-section-title {
    font-size: 11px;
    font-weight: 700;
    color: #9a9a9a;
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
    color: #9a9a9a;
    background: transparent;
    border: none;
    box-shadow: none;
    background-image: none;
    transition: all 120ms ease;
}

.fluent-nav-item:hover {
    background-color: rgba(255, 255, 255, 0.08);
    color: #ffffff;
}

.fluent-nav-item:checked, .fluent-nav-item:active {
    background-color: #2e2e2e;
    color: #ffffff;
    font-weight: 600;
    border-left: 3px solid #00c8d0;
}

/* Header & Titles */
.page-title {
    font-size: 22px;
    font-weight: 700;
    color: #ffffff;
    margin-bottom: 2px;
}

.page-subtitle {
    font-size: 13px;
    color: #9a9a9a;
    margin-bottom: 16px;
}

/* Fluent Cards */
.fluent-card {
    background-color: #242424;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 16px 18px;
    margin-bottom: 12px;
}

.fluent-card:hover {
    border-color: #4a4a4a;
}

.fluent-tile {
    background-color: #242424;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 12px 14px;
    transition: all 120ms ease;
}

.fluent-tile:hover {
    background-color: #2e2e2e;
    border-color: #4a4a4a;
}

.tile-title {
    font-size: 11px;
    color: #9a9a9a;
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
    background-color: #242424;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 10px 14px;
    transition: all 120ms ease;
}

.metric-tile:hover {
    border-color: #4a4a4a;
}

.metric-tile-label {
    font-size: 11px;
    font-weight: 600;
    color: #9a9a9a;
    letter-spacing: 0.4px;
}

.metric-tile-val {
    font-size: 14px;
    font-weight: 600;
    color: #f2f2f2;
    margin-top: 2px;
}

/* Fluent Setting Row Card */
.fluent-setting-row {
    background-color: #242424;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 6px;
    transition: all 120ms ease;
}

.fluent-setting-row:hover {
    border-color: #4a4a4a;
    background-color: #1c2128;
}

.setting-icon-box {
    background-color: rgba(96, 205, 255, 0.12);
    border-radius: 6px;
    padding: 6px 9px;
    margin-right: 12px;
}

/* Status Banner */
.status-banner-active {
    background: linear-gradient(135deg, rgba(46, 160, 67, 0.15) 0%, rgba(22, 27, 34, 0.95) 100%);
    border: 1px solid rgba(46, 160, 67, 0.55);
    border-radius: 8px;
    padding: 18px;
    box-shadow: 0 4px 20px rgba(46, 160, 67, 0.08);
}

.status-banner-inactive {
    background: linear-gradient(135deg, rgba(248, 81, 73, 0.12) 0%, rgba(22, 27, 34, 0.95) 100%);
    border: 1px solid rgba(248, 81, 73, 0.45);
    border-radius: 8px;
    padding: 18px;
    box-shadow: 0 4px 20px rgba(248, 81, 73, 0.05);
}

/* Button Variants */
.fluent-btn-primary {
    background-image: none;
    background-color: #00adb5;
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
    background-color: #da3633;
    color: #ffffff;
    border: 1px solid #f85149;
    font-weight: 600;
    padding: 8px 20px;
    box-shadow: 0 2px 8px rgba(218, 54, 51, 0.35);
}

.fluent-btn-danger:hover {
    background-color: #f85149;
    border-color: #ff7b72;
}

.fluent-btn-secondary {
    background-image: none;
    background-color: #2e2e2e;
    color: #f2f2f2;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
    padding: 7px 16px;
}

.fluent-btn-secondary:hover {
    background-color: #3a3a3a;
    border-color: #4a4a4a;
    color: #ffffff;
}

/* Badges / Pills */
.badge-ok {
    background-color: rgba(46, 160, 67, 0.18);
    border: 1px solid rgba(46, 160, 67, 0.45);
    color: #3fb950;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-warn {
    background-color: rgba(210, 153, 34, 0.18);
    border: 1px solid rgba(210, 153, 34, 0.45);
    color: #e3b341;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-bad {
    background-color: rgba(248, 81, 73, 0.18);
    border: 1px solid rgba(248, 81, 73, 0.45);
    color: #f85149;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-accent {
    background-color: rgba(96, 205, 255, 0.16);
    border: 1px solid rgba(96, 205, 255, 0.45);
    color: #00c8d0;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-neutral {
    background-color: rgba(139, 148, 158, 0.16);
    border: 1px solid rgba(139, 148, 158, 0.35);
    color: #9a9a9a;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

/* Logs and Text Area */
textview, textview text, .log-view, .log-view text {
    background-color: #0a0c10;
    color: #79c0ff;
    font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", monospace;
    font-size: 12px;
}

.log-view {
    padding: 10px;
    border: 1px solid #3a3a3a;
    border-radius: 6px;
}

/* Progress bar */
progressbar trough {
    background-color: #2e2e2e;
    border: 1px solid #3a3a3a;
    border-radius: 4px;
    min-height: 8px;
}

progressbar progress {
    background-color: #00adb5;
    border-radius: 4px;
}

/* Scrolled window */
scrolledwindow viewport {
    background-color: transparent;
}

/* Windows Fluent 2 Enhancements */
.hero-card-accent {
    background: linear-gradient(135deg, rgba(0, 162, 237, 0.14) 0%, #252525 100%) !important;
    border: 1px solid rgba(0, 162, 237, 0.55) !important;
}

.quick-action-card {
    background-color: #252525;
    border: 1px solid #363636;
    border-radius: 8px;
    padding: 12px 14px;
    transition: all 120ms ease;
}
.quick-action-card:hover {
    background-color: #2f2f2f;
    border-color: #484848;
}

.quick-action-purple {
    background: linear-gradient(135deg, rgba(147, 51, 234, 0.18) 0%, #252525 100%);
    border: 1px solid rgba(147, 51, 234, 0.45);
}
.quick-action-purple:hover {
    background: linear-gradient(135deg, rgba(147, 51, 234, 0.28) 0%, #2d2d2d 100%);
    border-color: rgba(147, 51, 234, 0.65);
}

.badge-free {
    background-color: #333333;
    color: #b5b5b5;
    font-size: 10px;
    font-weight: 700;
    border-radius: 4px;
    padding: 2px 6px;
    letter-spacing: 0.5px;
}

.preset-chip {
    background-color: #262626;
    border: 1px solid #363636;
    border-radius: 6px;
    padding: 6px 12px;
    color: #d0d0d0;
    font-size: 12px;
    transition: all 120ms ease;
}
.preset-chip:hover {
    background-color: #323232;
    border-color: #4a4a4a;
    color: #ffffff;
}
.preset-chip-active {
    background-color: rgba(0, 162, 237, 0.18) !important;
    border: 1px solid #00a2ed !important;
    color: #ffffff !important;
    font-weight: 600;
}

.service-tile {
    background-color: #252525;
    border: 1px solid #343434;
    border-radius: 8px;
    padding: 10px 12px;
    transition: all 120ms ease;
}
.service-tile:hover {
    background-color: #2c2c2c;
    border-color: #444444;
}

.last-msg-card {
    background-color: #222222;
    border: 1px solid #2d2d2d;
    border-radius: 8px;
    padding: 10px 14px;
}

/* ComboBox */
combobox button.combo {
    background-color: #2e2e2e;
    border: 1px solid #3a3a3a;
    color: #f2f2f2;
    border-radius: 6px;
    padding: 4px 10px;
}

combobox menu {
    background-color: #242424;
    border: 1px solid #3a3a3a;
    color: #f2f2f2;
}

/* Content width limiter for ultrawide screens */
.content-wrapper {
    margin: 22px 32px;
}
"""


def _build_light_css() -> str:
    """Light theme: Clean modern light palette (#f8fafc / #ffffff, text #0f172a, borders #e2e8f0, accents #0284c7)."""
    return """
* {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", "Ubuntu", "Cantarell", "Noto Sans", sans-serif;
    outline: none;
    -gtk-dpi: 96;
}

window {
    background-color: #f8fafc;
    color: #0f172a;
}

/* Universal button styling */
button {
    background-image: none;
    background-color: #ffffff;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 500;
    font-size: 13px;
    transition: all 120ms ease;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.04);
    text-shadow: none;
}

button:hover {
    background-color: #f1f5f9;
    border-color: #94a3b8;
    color: #0f172a;
}

button:active {
    background-color: #e2e8f0;
    border-color: #0284c7;
}

button:disabled {
    opacity: 0.55;
}

/* Switch styling */
switch {
    min-width: 44px;
    min-height: 22px;
    border-radius: 12px;
    background-color: #e2e8f0;
    border: 1px solid #cbd5e1;
}

switch:checked {
    background-color: #0284c7;
    border-color: #0369a1;
}

switch slider {
    min-width: 16px;
    min-height: 16px;
    border-radius: 50%;
    background-color: #ffffff;
    margin: 3px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}

/* Sidebar styling */
.fluent-sidebar {
    background-color: #ffffff;
    border-right: 1px solid #e2e8f0;
    padding: 12px 6px;
}

.nav-section-title {
    font-size: 11px;
    font-weight: 700;
    color: #64748b;
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
    color: #475569;
    background: transparent;
    border: none;
    box-shadow: none;
    background-image: none;
    transition: all 120ms ease;
}

.fluent-nav-item:hover {
    background-color: #f1f5f9;
    color: #0f172a;
}

.fluent-nav-item:checked, .fluent-nav-item:active {
    background-color: #e0f2fe;
    color: #0369a1;
    font-weight: 600;
    border-left: 3px solid #0284c7;
}

/* Header & Titles */
.page-title {
    font-size: 22px;
    font-weight: 700;
    color: #0f172a;
    margin-bottom: 2px;
}

.page-subtitle {
    font-size: 13px;
    color: #64748b;
    margin-bottom: 16px;
}

/* Fluent Cards */
.fluent-card {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 16px 18px;
    margin-bottom: 12px;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.03);
}

.fluent-card:hover {
    border-color: #cbd5e1;
}

.fluent-tile {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px 14px;
    transition: all 120ms ease;
}

.fluent-tile:hover {
    background-color: #f8fafc;
    border-color: #cbd5e1;
}

.tile-title {
    font-size: 11px;
    color: #64748b;
    font-weight: 600;
    margin-bottom: 4px;
}

.tile-value {
    font-size: 13px;
    font-weight: 600;
    color: #0f172a;
}

/* Metric Tiles Row (Top of Dashboard) */
.metric-tile {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 10px 14px;
    transition: all 120ms ease;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.metric-tile:hover {
    border-color: #cbd5e1;
}

.metric-tile-label {
    font-size: 11px;
    font-weight: 600;
    color: #64748b;
    letter-spacing: 0.4px;
}

.metric-tile-val {
    font-size: 14px;
    font-weight: 600;
    color: #0f172a;
    margin-top: 2px;
}

/* Fluent Setting Row Card */
.fluent-setting-row {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 6px;
    transition: all 120ms ease;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.02);
}

.fluent-setting-row:hover {
    border-color: #cbd5e1;
    background-color: #f8fafc;
}

.setting-icon-box {
    background-color: rgba(2, 132, 199, 0.1);
    border-radius: 6px;
    padding: 6px 9px;
    margin-right: 12px;
}

/* Status Banner */
.status-banner-active {
    background: linear-gradient(135deg, rgba(16, 185, 129, 0.12) 0%, rgba(255, 255, 255, 0.98) 100%);
    border: 1px solid rgba(16, 185, 129, 0.6);
    border-radius: 8px;
    padding: 18px;
    box-shadow: 0 4px 16px rgba(16, 185, 129, 0.08);
}

.status-banner-inactive {
    background: linear-gradient(135deg, rgba(239, 68, 68, 0.1) 0%, rgba(255, 255, 255, 0.98) 100%);
    border: 1px solid rgba(239, 68, 68, 0.5);
    border-radius: 8px;
    padding: 18px;
    box-shadow: 0 4px 16px rgba(239, 68, 68, 0.06);
}

/* Button Variants */
.fluent-btn-primary {
    background-image: none;
    background-color: #0284c7;
    color: #ffffff;
    border: 1px solid #0369a1;
    font-weight: 600;
    padding: 8px 20px;
    box-shadow: 0 2px 6px rgba(2, 132, 199, 0.3);
}

.fluent-btn-primary:hover {
    background-color: #0369a1;
    border-color: #075985;
}

.fluent-btn-danger {
    background-image: none;
    background-color: #ef4444;
    color: #ffffff;
    border: 1px solid #dc2626;
    font-weight: 600;
    padding: 8px 20px;
    box-shadow: 0 2px 6px rgba(239, 68, 68, 0.25);
}

.fluent-btn-danger:hover {
    background-color: #dc2626;
    border-color: #b91c1c;
}

.fluent-btn-secondary {
    background-image: none;
    background-color: #f1f5f9;
    color: #0f172a;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
    padding: 7px 16px;
}

.fluent-btn-secondary:hover {
    background-color: #e2e8f0;
    border-color: #94a3b8;
    color: #0f172a;
}

/* Badges / Pills */
.badge-ok {
    background-color: rgba(16, 185, 129, 0.14);
    border: 1px solid rgba(16, 185, 129, 0.45);
    color: #047857;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-warn {
    background-color: rgba(245, 158, 11, 0.14);
    border: 1px solid rgba(245, 158, 11, 0.45);
    color: #b45309;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-bad {
    background-color: rgba(239, 68, 68, 0.14);
    border: 1px solid rgba(239, 68, 68, 0.45);
    color: #b91c1c;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-accent {
    background-color: rgba(2, 132, 199, 0.14);
    border: 1px solid rgba(2, 132, 199, 0.45);
    color: #0369a1;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-neutral {
    background-color: rgba(100, 116, 139, 0.14);
    border: 1px solid rgba(100, 116, 139, 0.35);
    color: #475569;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

/* Logs and Text Area */
textview, textview text, .log-view, .log-view text {
    background-color: #f8fafc;
    color: #1e293b;
    font-family: "JetBrains Mono", "Cascadia Code", "Fira Code", monospace;
    font-size: 12px;
}

.log-view {
    padding: 10px;
    border: 1px solid #cbd5e1;
    border-radius: 6px;
}

/* Progress bar */
progressbar trough {
    background-color: #e2e8f0;
    border: 1px solid #cbd5e1;
    border-radius: 4px;
    min-height: 8px;
}

progressbar progress {
    background-color: #0284c7;
    border-radius: 4px;
}

/* Scrolled window */
scrolledwindow viewport {
    background-color: transparent;
}

/* Windows Fluent 2 Enhancements */
.hero-card-accent {
    background: linear-gradient(135deg, rgba(0, 162, 237, 0.14) 0%, #252525 100%) !important;
    border: 1px solid rgba(0, 162, 237, 0.55) !important;
}

.quick-action-card {
    background-color: #252525;
    border: 1px solid #363636;
    border-radius: 8px;
    padding: 12px 14px;
    transition: all 120ms ease;
}
.quick-action-card:hover {
    background-color: #2f2f2f;
    border-color: #484848;
}

.quick-action-purple {
    background: linear-gradient(135deg, rgba(147, 51, 234, 0.18) 0%, #252525 100%);
    border: 1px solid rgba(147, 51, 234, 0.45);
}
.quick-action-purple:hover {
    background: linear-gradient(135deg, rgba(147, 51, 234, 0.28) 0%, #2d2d2d 100%);
    border-color: rgba(147, 51, 234, 0.65);
}

.badge-free {
    background-color: #333333;
    color: #b5b5b5;
    font-size: 10px;
    font-weight: 700;
    border-radius: 4px;
    padding: 2px 6px;
    letter-spacing: 0.5px;
}

.preset-chip {
    background-color: #262626;
    border: 1px solid #363636;
    border-radius: 6px;
    padding: 6px 12px;
    color: #d0d0d0;
    font-size: 12px;
    transition: all 120ms ease;
}
.preset-chip:hover {
    background-color: #323232;
    border-color: #4a4a4a;
    color: #ffffff;
}
.preset-chip-active {
    background-color: rgba(0, 162, 237, 0.18) !important;
    border: 1px solid #00a2ed !important;
    color: #ffffff !important;
    font-weight: 600;
}

.service-tile {
    background-color: #252525;
    border: 1px solid #343434;
    border-radius: 8px;
    padding: 10px 12px;
    transition: all 120ms ease;
}
.service-tile:hover {
    background-color: #2c2c2c;
    border-color: #444444;
}

.last-msg-card {
    background-color: #222222;
    border: 1px solid #2d2d2d;
    border-radius: 8px;
    padding: 10px 14px;
}

/* ComboBox */
combobox button.combo {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    color: #0f172a;
    border-radius: 6px;
    padding: 4px 10px;
}

combobox menu {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    color: #0f172a;
}

/* Content width limiter for ultrawide screens */
.content-wrapper {
    margin: 22px 32px;
}
"""


def _build_dark_overrides() -> str:
    """Modern 2026 refresh layered on top of the legacy palette.

    Kept as a separate block so every historical selector stays valid while the
    visible surface, inputs, tables, scrollbars and status banner are updated.
    """
    return """
/* ===== Modern refresh: dark ===== */
window, .background {
    background-color: #202020;
    color: #f2f2f2;
}

/* Sidebar */
.fluent-sidebar {
    background-color: #1a1a1a;
    border-right: 1px solid #2a2a2a;
    padding: 14px 8px;
}
.brand-box {
    padding: 0 2px;
}
.brand-icon {
    background-color: rgba(0, 200, 208, 0.12);
    border: 1px solid rgba(0, 200, 208, 0.22);
    border-radius: 10px;
    padding: 6px 8px;
}
.brand-title {
    font-size: 15px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.2px;
}
.brand-version {
    font-size: 11px;
    color: #9a9a9a;
}
.brand-icon image {
    color: #33d6de;
}
.nav-section-title {
    color: #8a8a8a;
    font-size: 10px;
    letter-spacing: 0.8px;
    margin-top: 18px;
    margin-bottom: 4px;
    margin-left: 14px;
    font-weight: 700;
}
.fluent-nav-item {
    color: #a6a6a6;
    border-radius: 8px;
    padding: 9px 12px;
    margin: 2px 6px;
    border: none;
    box-shadow: none;
}
.fluent-nav-item:hover {
    background-color: #262626;
    color: #ffffff;
}
.fluent-nav-item:checked {
    background-color: #2e2e2e;
    color: #ffffff;
    font-weight: 600;
    border-left: none;
    box-shadow: none;
}
.fluent-nav-item image {
    color: #a6a6a6;
}
.fluent-nav-item:checked image {
    color: #33d6de;
}
.section-title {
    font-size: 13px;
    font-weight: 600;
    color: #d6d6d6;
    letter-spacing: 0.2px;
    margin-top: 14px;
    margin-bottom: 8px;
}

/* Buttons */
button {
    background-color: #2e2e2e;
    color: #f2f2f2;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 8px 15px;
    font-weight: 500;
    font-size: 13px;
    box-shadow: none;
}
button:hover {
    background-color: #3a3a3a;
    border-color: #4a4a4a;
    color: #ffffff;
}
button:active {
    background-color: #262626;
    border-color: #00c8d0;
}
button:focus {
    box-shadow: 0 0 0 3px rgba(0, 200, 208, 0.20);
}
.fluent-btn-primary {
    background-color: #00adb5;
    border-color: #00adb5;
    color: #ffffff;
    font-weight: 600;
    box-shadow: none;
}
.fluent-btn-primary:hover {
    background-color: #00bcc5;
    border-color: #00bcc5;
    box-shadow: none;
}
.fluent-btn-secondary {
    background-color: #2e2e2e;
    border-color: #3a3a3a;
    color: #f2f2f2;
    box-shadow: none;
}
.fluent-btn-secondary:hover {
    background-color: #3a3a3a;
    border-color: #4a4a4a;
}
.fluent-btn-danger {
    background-color: #c9484a;
    border-color: #c9484a;
    color: #ffffff;
    box-shadow: none;
}
.fluent-btn-danger:hover {
    background-color: #db585a;
    border-color: #db585a;
}

/* Inputs */
entry, spinbutton, searchentry, combobox button, combobox button.combo {
    background-color: #2a2a2a;
    color: #f2f2f2;
    border: 1px solid #3a3a3a;
    border-radius: 8px;
    padding: 8px 12px;
    box-shadow: none;
    caret-color: #00c8d0;
}
entry:focus, spinbutton:focus, combobox button:focus {
    border-color: #00c8d0;
    box-shadow: 0 0 0 3px rgba(0, 200, 208, 0.16);
}
entry:disabled {
    color: #8a8a8a;
}
entry selection, textview selection {
    background-color: #00adb5;
    color: #ffffff;
}
combobox arrow {
    color: #a6a6a6;
}

/* Text views and logs */
textview, textview text, .log-view, .log-view text {
    background-color: #171717;
    color: #e8e8e8;
}
textview {
    border: 1px solid #2f2f2f;
    border-radius: 9px;
}
textview text {
    padding: 6px;
}

/* Tree view (orchestra results, catalogs) */
treeview.view {
    background-color: #1e1e1e;
    color: #f2f2f2;
    border: none;
}
treeview.view:selected {
    background-color: rgba(0, 200, 208, 0.20);
    color: #ffffff;
}
treeview.view header button {
    background-color: #242424;
    color: #9a9a9a;
    border: none;
    border-bottom: 1px solid #2f2f2f;
    border-radius: 0;
    padding: 8px 10px;
    font-weight: 600;
    font-size: 12px;
    box-shadow: none;
}
treeview.view header button:hover {
    background-color: #2a2a2a;
    color: #ffffff;
}

/* Scrollbars: the old white trough was the most visible artifact */
scrollbar {
    background-color: transparent;
    border: none;
}
scrollbar trough {
    background-color: transparent;
}
scrollbar slider {
    background-color: #3d3d3d;
    border-radius: 8px;
    min-width: 8px;
    min-height: 8px;
    margin: 2px;
}
scrollbar slider:hover {
    background-color: #4f4f4f;
}
scrolledwindow undershoot, scrolledwindow overshoot {
    background: none;
    box-shadow: none;
    border: none;
}

/* Cards */
.fluent-card {
    background-color: #282828;
    border: 1px solid #2f2f2f;
    border-radius: 10px;
    padding: 18px 20px;
    margin-bottom: 12px;
    box-shadow: none;
}
.fluent-card:hover {
    border-color: #3a3a3a;
}
.fluent-tile {
    background-color: #242424;
    border: 1px solid #2f2f2f;
    border-radius: 10px;
    padding: 12px 14px;
}
.fluent-tile:hover {
    background-color: #2c2c2c;
    border-color: #3a3a3a;
}
.fluent-setting-row {
    background-color: #282828;
    border: 1px solid #2f2f2f;
    border-radius: 10px;
    padding: 16px 18px;
    margin-bottom: 8px;
}
.fluent-setting-row:hover {
    background-color: #2e2e2e;
    border-color: #3a3a3a;
}
.setting-icon-box {
    background-color: rgba(0, 200, 208, 0.10);
    border-radius: 9px;
    padding: 7px 9px;
}
.setting-icon-image {
    color: #33d6de;
}

/* Typography */
.page-title {
    font-size: 26px;
    font-weight: 700;
    color: #ffffff;
    letter-spacing: -0.3px;
    margin-top: 4px;
    margin-bottom: 4px;
    padding-top: 4px;
}
.page-subtitle {
    font-size: 13px;
    color: #9a9a9a;
    margin-bottom: 20px;
}
.tile-title, .metric-tile-label {
    font-size: 10px;
    letter-spacing: 0.7px;
    color: #8a8a8a;
    font-weight: 700;
}
.tile-value, .metric-tile-val {
    color: #ffffff;
    font-weight: 600;
    font-size: 14px;
}

/* Status banner: flat surface with a quiet accent, no glow */
.status-banner-active {
    background-color: #282828;
    background-image: none;
    border: 1px solid #2f2f2f;
    border-radius: 10px;
    padding: 18px 20px;
    box-shadow: none;
}
.status-banner-inactive {
    background-color: #282828;
    background-image: none;
    border: 1px solid #2f2f2f;
    border-radius: 10px;
    padding: 18px 20px;
    box-shadow: none;
}

/* Badges */
.badge-ok, .badge-warn, .badge-bad, .badge-accent, .badge-neutral,
.badge-tag-v2, .badge-tag-legacy {
    border-radius: 999px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
}
.badge-ok {
    background-color: rgba(70, 185, 127, 0.12);
    border: 1px solid rgba(70, 185, 127, 0.32);
    color: #5ed39a;
}
.badge-warn {
    background-color: rgba(227, 179, 65, 0.12);
    border: 1px solid rgba(227, 179, 65, 0.32);
    color: #e7c266;
}
.badge-bad {
    background-color: rgba(224, 106, 99, 0.12);
    border: 1px solid rgba(224, 106, 99, 0.32);
    color: #ef8a84;
}
.badge-accent {
    background-color: rgba(0, 200, 208, 0.12);
    border: 1px solid rgba(0, 200, 208, 0.32);
    color: #33d6de;
}
.badge-neutral {
    background-color: rgba(143, 160, 181, 0.10);
    border: 1px solid rgba(143, 160, 181, 0.25);
    color: #a6a6a6;
}
.badge-tag-v2 {
    background-color: rgba(0, 200, 208, 0.12);
    color: #33d6de;
}
.badge-tag-legacy {
    background-color: rgba(143, 160, 181, 0.10);
    color: #a6a6a6;
}

/* Switches & checks */
switch {
    min-width: 46px;
    min-height: 26px;
    border-radius: 999px;
    background-color: #4a4a4a;
    border: 1px solid #4a4a4a;
}
switch:checked {
    background-color: #00c8d0;
    border-color: #00c8d0;
}
switch slider {
    min-width: 18px;
    min-height: 18px;
    border-radius: 50%;
    background-color: #8a8a8a;
    margin: 2px;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.35);
}
switch:checked slider {
    background-color: #111111;
}
check, radio {
    background-color: #1e1e1e;
    border: 1px solid #4a4a4a;
    border-radius: 5px;
}
check:checked, radio:checked {
    background-color: #00adb5;
    border-color: #00adb5;
    color: #ffffff;
}

/* Progress */
progressbar trough {
    background-color: #2e2e2e;
    border: none;
    border-radius: 999px;
    min-height: 8px;
}
progressbar progress {
    background-color: #00c8d0;
    border-radius: 999px;
    min-height: 8px;
}

/* Menus, popovers, tooltips */
menu, .menu, popover, popover.background {
    background-color: #242424;
    color: #f2f2f2;
    border: 1px solid #2f2f2f;
    border-radius: 10px;
}
menuitem {
    padding: 7px 12px;
    border-radius: 6px;
}
menuitem:hover {
    background-color: #2e2e2e;
    color: #ffffff;
}
tooltip, tooltip.background {
    background-color: #242424;
    color: #ffffff;
    border: 1px solid #2f2f2f;
    border-radius: 8px;
    padding: 6px 10px;
}

/* Classes used by newer pages */
.feature-bullet { color: #a6a6a6; }
.filter-pill {
    background-color: #2a2a2a;
    border: 1px solid #2f2f2f;
    border-radius: 999px;
    padding: 4px 10px;
    color: #a6a6a6;
    font-size: 12px;
}
.game-warning-banner {
    background-color: rgba(227, 179, 65, 0.10);
    border: 1px solid rgba(227, 179, 65, 0.28);
    border-radius: 11px;
    padding: 12px 14px;
}
.health-grid-tile {
    background-color: #1e1e1e;
    border: 1px solid #2f2f2f;
    border-radius: 11px;
    padding: 12px 14px;
}
.persistent-status-bar {
    background-color: #1a1a1a;
    border-top: 1px solid #2a2a2a;
    padding: 6px 12px;
}
.persistent-bar-info { color: #9a9a9a; font-size: 12px; }
.persistent-toggle-btn {
    border-radius: 8px;
    padding: 4px 12px;
}
.onboarding-window { background-color: #1a1a1a; }
.onboarding-card {
    background-color: #242424;
    border: 1px solid #2f2f2f;
    border-radius: 14px;
    padding: 20px;
}
.onboarding-card-accent { border-color: rgba(0, 200, 208, 0.40); }
.onboarding-step-pill {
    background-color: #2a2a2a;
    color: #9a9a9a;
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 12px;
}
.onboarding-step-pill-active {
    background-color: rgba(0, 200, 208, 0.16);
    color: #e6feff;
}
expander title { color: #9a9a9a; }
expander title:hover { color: #ffffff; }
separator { background-color: #2a2a2a; min-height: 1px; }
"""


def _build_light_overrides() -> str:
    """Modern 2026 refresh for the light palette."""
    return """
/* ===== Modern refresh: light ===== */
window, .background {
    background-color: #f4f6fa;
    color: #16202b;
}

/* Sidebar */
.fluent-sidebar {
    background-color: #ffffff;
    border-right: 1px solid #e2e8f2;
    padding: 14px 8px;
}
.brand-box {
    padding: 0 2px;
}
.brand-icon {
    background-color: rgba(47, 111, 237, 0.08);
    border: 1px solid rgba(47, 111, 237, 0.18);
    border-radius: 10px;
    padding: 6px 8px;
}
.brand-title {
    font-size: 15px;
    font-weight: 700;
    color: #101a26;
    letter-spacing: -0.2px;
}
.brand-version {
    font-size: 11px;
    color: #6b7a92;
}
.brand-icon image {
    color: #2f6fed;
}
.nav-section-title {
    color: #7b8aa1;
    font-size: 10px;
    letter-spacing: 0.8px;
    margin-top: 18px;
    margin-bottom: 4px;
    margin-left: 14px;
    font-weight: 700;
}
.fluent-nav-item {
    color: #5c6b82;
    border-radius: 9px;
    padding: 9px 12px;
    margin: 2px 6px;
    border: none;
    box-shadow: none;
}
.fluent-nav-item:hover {
    background-color: #f1f5fb;
    color: #16202b;
}
.fluent-nav-item:checked {
    background-color: rgba(47, 111, 237, 0.10);
    color: #16202b;
    font-weight: 600;
    border-left: none;
    box-shadow: inset 3px 0 0 #2f6fed;
}
.fluent-nav-item image {
    color: #5c6b82;
}
.fluent-nav-item:checked image {
    color: #2f6fed;
}
.section-title {
    font-size: 13px;
    font-weight: 600;
    color: #314056;
    letter-spacing: 0.2px;
    margin-top: 14px;
    margin-bottom: 8px;
}

/* Buttons */
button {
    background-color: #ffffff;
    color: #314056;
    border: 1px solid #d8e0ec;
    border-radius: 9px;
    padding: 8px 15px;
    font-weight: 500;
    font-size: 13px;
    box-shadow: none;
}
button:hover {
    background-color: #f4f7fc;
    border-color: #b9c5d8;
    color: #16202b;
}
button:focus {
    box-shadow: 0 0 0 3px rgba(47, 111, 237, 0.16);
}
.fluent-btn-primary {
    background-color: #2f6fed;
    border-color: #2f6fed;
    color: #ffffff;
    font-weight: 600;
    box-shadow: none;
}
.fluent-btn-primary:hover {
    background-color: #255fd4;
    border-color: #255fd4;
}
.fluent-btn-secondary {
    background-color: #ffffff;
    border-color: #d8e0ec;
    color: #314056;
}
.fluent-btn-secondary:hover {
    background-color: #f4f7fc;
    border-color: #b9c5d8;
}
.fluent-btn-danger {
    background-color: #c93c37;
    border-color: #c93c37;
    color: #ffffff;
    box-shadow: none;
}

/* Inputs */
entry, spinbutton, searchentry, combobox button, combobox button.combo {
    background-color: #ffffff;
    color: #16202b;
    border: 1px solid #d8e0ec;
    border-radius: 9px;
    padding: 8px 12px;
    box-shadow: none;
    caret-color: #2f6fed;
}
entry:focus, spinbutton:focus, combobox button:focus {
    border-color: #2f6fed;
    box-shadow: 0 0 0 3px rgba(47, 111, 237, 0.14);
}
entry selection, textview selection {
    background-color: #2f6fed;
    color: #ffffff;
}
combobox arrow { color: #5c6b82; }

/* Text views and logs */
textview, textview text, .log-view, .log-view text {
    background-color: #fbfcfe;
    color: #1d2a3a;
}
textview {
    border: 1px solid #e2e8f2;
    border-radius: 9px;
}
textview text { padding: 6px; }

/* Tree view */
treeview.view {
    background-color: #ffffff;
    color: #1d2a3a;
    border: none;
}
treeview.view:selected {
    background-color: rgba(47, 111, 237, 0.12);
    color: #16202b;
}
treeview.view header button {
    background-color: #f6f8fc;
    color: #5c6b82;
    border: none;
    border-bottom: 1px solid #e2e8f2;
    border-radius: 0;
    padding: 8px 10px;
    font-weight: 600;
    font-size: 12px;
    box-shadow: none;
}

/* Scrollbars */
scrollbar { background-color: transparent; border: none; }
scrollbar trough { background-color: transparent; }
scrollbar slider {
    background-color: #c3ccdb;
    border-radius: 8px;
    min-width: 8px;
    min-height: 8px;
    margin: 2px;
}
scrollbar slider:hover { background-color: #a8b4c8; }
scrolledwindow undershoot, scrolledwindow overshoot {
    background: none;
    box-shadow: none;
    border: none;
}

/* Cards */
.fluent-card {
    background-color: #ffffff;
    border: 1px solid #e2e8f2;
    border-radius: 13px;
    padding: 18px 20px;
    margin-bottom: 12px;
    box-shadow: none;
}
.fluent-tile {
    background-color: #fbfcfe;
    border: 1px solid #e2e8f2;
    border-radius: 11px;
    padding: 12px 14px;
}
.fluent-setting-row {
    background-color: #ffffff;
    border: 1px solid #e2e8f2;
    border-radius: 12px;
    padding: 13px 16px;
    margin-bottom: 8px;
}
.fluent-setting-row:hover {
    background-color: #f8fafd;
    border-color: #cbd5e4;
}
.setting-icon-box {
    background-color: rgba(47, 111, 237, 0.08);
    border-radius: 9px;
    padding: 7px 9px;
}
.setting-icon-image {
    color: #2f6fed;
}

/* Typography */
.page-title {
    font-size: 26px;
    font-weight: 700;
    color: #101a26;
    letter-spacing: -0.3px;
    margin-top: 4px;
    margin-bottom: 4px;
    padding-top: 4px;
}
.page-subtitle {
    font-size: 13px;
    color: #61708a;
    margin-bottom: 20px;
}
.tile-title, .metric-tile-label {
    font-size: 10px;
    letter-spacing: 0.7px;
    color: #6b7a92;
    font-weight: 700;
}
.tile-value, .metric-tile-val {
    color: #101a26;
    font-weight: 600;
    font-size: 14px;
}

/* Status banner: flat, no gradient or glow */
.status-banner-active {
    background-color: #ffffff;
    background-image: none;
    border: 1px solid #e2e8f2;
    border-left: 4px solid #14875a;
    border-radius: 13px;
    padding: 18px 20px;
    box-shadow: none;
}
.status-banner-inactive {
    background-color: #ffffff;
    background-image: none;
    border: 1px solid #e2e8f2;
    border-left: 4px solid #c93c37;
    border-radius: 13px;
    padding: 18px 20px;
    box-shadow: none;
}

/* Badges */
.badge-ok, .badge-warn, .badge-bad, .badge-accent, .badge-neutral,
.badge-tag-v2, .badge-tag-legacy {
    border-radius: 999px;
    padding: 3px 10px;
    font-size: 11px;
    font-weight: 600;
}
.badge-ok {
    background-color: rgba(20, 135, 90, 0.10);
    border: 1px solid rgba(20, 135, 90, 0.28);
    color: #0f7a50;
}
.badge-warn {
    background-color: rgba(180, 83, 9, 0.10);
    border: 1px solid rgba(180, 83, 9, 0.28);
    color: #a1520b;
}
.badge-bad {
    background-color: rgba(201, 60, 55, 0.10);
    border: 1px solid rgba(201, 60, 55, 0.28);
    color: #b33631;
}
.badge-accent {
    background-color: rgba(47, 111, 237, 0.10);
    border: 1px solid rgba(47, 111, 237, 0.28);
    color: #245fd0;
}
.badge-neutral {
    background-color: rgba(92, 107, 130, 0.08);
    border: 1px solid rgba(92, 107, 130, 0.22);
    color: #5c6b82;
}
.badge-tag-v2 { background-color: rgba(47, 111, 237, 0.10); color: #245fd0; }
.badge-tag-legacy { background-color: rgba(92, 107, 130, 0.08); color: #5c6b82; }

/* Switches & checks */
switch {
    min-width: 42px;
    min-height: 24px;
    border-radius: 999px;
    background-color: #dbe2ed;
    border: 1px solid #dbe2ed;
}
switch:checked {
    background-color: #2f6fed;
    border-color: #2f6fed;
}
switch slider {
    min-width: 18px;
    min-height: 18px;
    border-radius: 50%;
    background-color: #ffffff;
    margin: 2px;
    box-shadow: 0 1px 2px rgba(20, 30, 50, 0.20);
}
check, radio {
    background-color: #ffffff;
    border: 1px solid #c3ccdb;
    border-radius: 5px;
}
check:checked, radio:checked {
    background-color: #2f6fed;
    border-color: #2f6fed;
    color: #ffffff;
}

/* Progress */
progressbar trough {
    background-color: #e6ebf3;
    border: none;
    border-radius: 999px;
    min-height: 8px;
}
progressbar progress {
    background-color: #2f6fed;
    border-radius: 999px;
    min-height: 8px;
}

/* Menus, popovers, tooltips */
menu, .menu, popover, popover.background {
    background-color: #ffffff;
    color: #1d2a3a;
    border: 1px solid #e2e8f2;
    border-radius: 10px;
}
menuitem { padding: 7px 12px; border-radius: 6px; }
menuitem:hover { background-color: #f4f7fc; color: #16202b; }
tooltip, tooltip.background {
    background-color: #1d2a3a;
    color: #ffffff;
    border: none;
    border-radius: 8px;
    padding: 6px 10px;
}

/* Classes used by newer pages */
.feature-bullet { color: #5c6b82; }
.filter-pill {
    background-color: #f1f5fb;
    border: 1px solid #e2e8f2;
    border-radius: 999px;
    padding: 4px 10px;
    color: #5c6b82;
    font-size: 12px;
}
.game-warning-banner {
    background-color: rgba(180, 83, 9, 0.08);
    border: 1px solid rgba(180, 83, 9, 0.22);
    border-radius: 11px;
    padding: 12px 14px;
}
.health-grid-tile {
    background-color: #fbfcfe;
    border: 1px solid #e2e8f2;
    border-radius: 11px;
    padding: 12px 14px;
}
.persistent-status-bar {
    background-color: #ffffff;
    border-top: 1px solid #e2e8f2;
    padding: 6px 12px;
}
.persistent-bar-info { color: #61708a; font-size: 12px; }
.persistent-toggle-btn {
    border-radius: 8px;
    padding: 4px 12px;
}
.onboarding-window { background-color: #f4f6fa; }
.onboarding-card {
    background-color: #ffffff;
    border: 1px solid #e2e8f2;
    border-radius: 14px;
    padding: 20px;
}
.onboarding-card-accent { border-color: rgba(47, 111, 237, 0.36); }
.onboarding-step-pill {
    background-color: #f1f5fb;
    color: #5c6b82;
    border-radius: 999px;
    padding: 4px 10px;
    font-size: 12px;
}
.onboarding-step-pill-active {
    background-color: rgba(47, 111, 237, 0.12);
    color: #16202b;
}
expander title { color: #5c6b82; }
expander title:hover { color: #16202b; }
separator { background-color: #e2e8f2; min-height: 1px; }
"""


def load_theme(theme_name: str, gtk_css_provider=None):
    """
    Apply the given theme ('dark', 'light', or 'system') to the GTK screen / application.
    If gtk_css_provider is supplied, reloads the CSS into it.
    Otherwise creates a new provider and registers it.
    Returns the CssProvider instance.
    """
    if not GTK_AVAILABLE:
        return None

    css_text = get_theme_css(theme_name)
    provider = gtk_css_provider if gtk_css_provider is not None else Gtk.CssProvider()

    try:
        provider.load_from_data(css_text.encode("utf-8"))
    except Exception as e:
        # Fallback in case of parse error
        print(f"Warning: Failed to load theme CSS: {e}")

    # Register provider if it wasn't already attached
    if gtk_css_provider is None:
        try:
            screen = Gdk.Screen.get_default()
            if screen is not None:
                Gtk.StyleContext.add_provider_for_screen(
                    screen,
                    provider,
                    Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
                )
        except Exception:
            pass

    return provider


class ThemeManager:
    """Manages active theme state and runtime switching."""

    def __init__(self, current_theme: str = "dark"):
        self.current_theme = current_theme if current_theme in VALID_THEMES else DEFAULT_THEME
        self.provider = None

    def apply(self, theme_name: Optional[str] = None):
        """Applies theme to GTK session."""
        if theme_name and theme_name in VALID_THEMES:
            self.current_theme = theme_name
        self.provider = load_theme(self.current_theme, self.provider)
        return self.provider

    def toggle(self) -> str:
        """Toggles between dark and light themes, returns new theme."""
        resolved = resolve_theme(self.current_theme)
        new_theme = "light" if resolved == "dark" else "dark"
        self.current_theme = new_theme
        self.apply()
        return new_theme
