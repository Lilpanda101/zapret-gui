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
        return _build_light_css()
    return _build_dark_css()


def _build_dark_css() -> str:
    """Dark theme: GitHub/Fluent Dark palette (#0d1117 / #161b22, text #e6edf3, accents #60cdff)."""
    return """
* {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Inter", "Ubuntu", "Cantarell", "Noto Sans", sans-serif;
    outline: none;
    -gtk-dpi: 96;
}

window {
    background-color: #0d1117;
    color: #e6edf3;
}

/* Universal button styling */
button {
    background-image: none;
    background-color: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 7px 16px;
    font-weight: 500;
    font-size: 13px;
    transition: all 120ms ease;
    box-shadow: none;
    text-shadow: none;
}

button:hover {
    background-color: #30363d;
    border-color: #484f58;
    color: #ffffff;
}

button:active {
    background-color: #161b22;
    border-color: #60cdff;
}

button:disabled {
    opacity: 0.55;
}

/* Switch styling - prevents stretching deformities */
switch {
    min-width: 44px;
    min-height: 22px;
    border-radius: 12px;
    background-color: #21262d;
    border: 1px solid #30363d;
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
    background-color: #161b22;
    border-right: 1px solid #21262d;
    padding: 12px 6px;
}

.nav-section-title {
    font-size: 11px;
    font-weight: 700;
    color: #8b949e;
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
    color: #8b949e;
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
    background-color: #1f242c;
    color: #ffffff;
    font-weight: 600;
    border-left: 3px solid #60cdff;
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
    color: #8b949e;
    margin-bottom: 16px;
}

/* Fluent Cards */
.fluent-card {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 16px 18px;
    margin-bottom: 12px;
}

.fluent-card:hover {
    border-color: #484f58;
}

.fluent-tile {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px 14px;
    transition: all 120ms ease;
}

.fluent-tile:hover {
    background-color: #1f242c;
    border-color: #484f58;
}

.tile-title {
    font-size: 11px;
    color: #8b949e;
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
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 10px 14px;
    transition: all 120ms ease;
}

.metric-tile:hover {
    border-color: #484f58;
}

.metric-tile-label {
    font-size: 11px;
    font-weight: 600;
    color: #8b949e;
    letter-spacing: 0.4px;
}

.metric-tile-val {
    font-size: 14px;
    font-weight: 600;
    color: #e6edf3;
    margin-top: 2px;
}

/* Fluent Setting Row Card */
.fluent-setting-row {
    background-color: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 12px 16px;
    margin-bottom: 6px;
    transition: all 120ms ease;
}

.fluent-setting-row:hover {
    border-color: #484f58;
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
    background-color: #21262d;
    color: #e6edf3;
    border: 1px solid #30363d;
    border-radius: 6px;
    padding: 7px 16px;
}

.fluent-btn-secondary:hover {
    background-color: #30363d;
    border-color: #484f58;
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
    color: #60cdff;
    border-radius: 12px;
    padding: 2px 9px;
    font-size: 11px;
    font-weight: 600;
}

.badge-neutral {
    background-color: rgba(139, 148, 158, 0.16);
    border: 1px solid rgba(139, 148, 158, 0.35);
    color: #8b949e;
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
    border: 1px solid #30363d;
    border-radius: 6px;
}

/* Progress bar */
progressbar trough {
    background-color: #21262d;
    border: 1px solid #30363d;
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
    background-color: #21262d;
    border: 1px solid #30363d;
    color: #e6edf3;
    border-radius: 6px;
    padding: 4px 10px;
}

combobox menu {
    background-color: #161b22;
    border: 1px solid #30363d;
    color: #e6edf3;
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
