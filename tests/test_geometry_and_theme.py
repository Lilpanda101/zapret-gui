#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Window State, Geometry, A11y, and Theme Management.
Covers serialization/deserialization of window geometry and last_page,
switching and CSS generation for dark/light/system themes,
and keyboard shortcuts and accessibility tooltips.
"""

import pytest
from unittest.mock import MagicMock, patch
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk

from window_state import (
    DEFAULT_WIDTH,
    DEFAULT_HEIGHT,
    MIN_WIDTH,
    MIN_HEIGHT,
    DEFAULT_PAGE,
    VALID_PAGES,
    SHORTCUT_PAGES,
    clamp_dimension,
    is_window_maximized,
    save_window_state,
    restore_window_state,
    bind_window_geometry_events,
    setup_window_shortcuts,
    apply_a11y_tooltips,
)
from theme_manager import (
    VALID_THEMES,
    DEFAULT_THEME,
    get_theme_css,
    resolve_theme,
    get_system_theme,
    load_theme,
    ThemeManager,
)


# ==============================================================================
# 1. GEOMETRY & WINDOW STATE TESTS
# ==============================================================================

class TestClampDimension:
    def test_normal_value(self):
        assert clamp_dimension(1024, default=800, min_val=640, max_val=1920) == 1024

    def test_underflow_clamped(self):
        assert clamp_dimension(200, default=800, min_val=640, max_val=1920) == 640

    def test_overflow_clamped(self):
        assert clamp_dimension(5000, default=800, min_val=640, max_val=1920) == 1920

    def test_none_and_invalid_string(self):
        assert clamp_dimension(None, default=800, min_val=640, max_val=1920) == 800
        assert clamp_dimension("not-a-number", default=800, min_val=640, max_val=1920) == 800

    def test_valid_numeric_string(self):
        assert clamp_dimension("1280", default=800, min_val=640, max_val=1920) == 1280


class TestRestoreWindowState:
    def test_restore_defaults_when_empty_config(self):
        win = MagicMock()
        last_page = restore_window_state(win, {})
        win.set_default_size.assert_called_once_with(DEFAULT_WIDTH, DEFAULT_HEIGHT)
        assert last_page == DEFAULT_PAGE
        assert win._is_maximized is False

    def test_restore_custom_dimensions(self):
        win = MagicMock()
        cfg = {
            "window_width": 1440,
            "window_height": 900,
            "window_maximized": False,
            "last_page": "dns",
        }
        last_page = restore_window_state(win, cfg)
        win.set_default_size.assert_called_once_with(1440, 900)
        assert last_page == "dns"
        assert win._is_maximized is False

    def test_restore_maximized_window(self):
        win = MagicMock()
        cfg = {
            "window_width": 1280,
            "window_height": 800,
            "window_maximized": True,
            "last_page": "hosts",
        }
        last_page = restore_window_state(win, cfg)
        win.set_default_size.assert_called_once_with(1280, 800)
        win.maximize.assert_called_once()
        assert win._is_maximized is True
        assert last_page == "hosts"

    def test_restore_invalid_page_fallback(self):
        win = MagicMock()
        cfg = {
            "window_width": 1080,
            "window_height": 720,
            "last_page": "non_existent_page_123",
        }
        last_page = restore_window_state(win, cfg)
        assert last_page == DEFAULT_PAGE


class TestSaveWindowState:
    def test_save_normal_window(self):
        win = MagicMock()
        win.get_size.return_value = (1366, 768)
        win._is_maximized = False
        config = {}

        updated = save_window_state(win, "zapret2", config)
        assert updated["window_width"] == 1366
        assert updated["window_height"] == 768
        assert updated["window_maximized"] is False
        assert updated["last_page"] == "zapret2"

    def test_save_maximized_window_preserves_unmaximized_size(self):
        win = MagicMock()
        win.get_size.return_value = (1920, 1080)
        win._is_maximized = True
        win._unmaximized_width = 1100
        win._unmaximized_height = 750
        config = {}

        updated = save_window_state(win, "monitor", config)
        assert updated["window_maximized"] is True
        assert updated["window_width"] == 1100
        assert updated["window_height"] == 750
        assert updated["last_page"] == "monitor"

    def test_save_with_invalid_page_preserves_existing_or_default(self):
        win = MagicMock()
        win.get_size.return_value = (1080, 720)
        win._is_maximized = False
        config = {"last_page": "profiles"}

        updated = save_window_state(win, "invalid_page", config)
        assert updated["last_page"] == "profiles"

    def test_is_window_maximized_checks(self):
        win = MagicMock()
        win._is_maximized = True
        assert is_window_maximized(win) is True

        win._is_maximized = False
        assert is_window_maximized(win) is False


class TestWindowGeometryEvents:
    def test_bind_window_geometry_events(self):
        win = MagicMock()
        callback = MagicMock()

        bind_window_geometry_events(win, on_change_callback=callback)

        assert win.connect.call_count == 2
        calls = [c[0][0] for c in win.connect.call_args_list]
        assert "window-state-event" in calls
        assert "configure-event" in calls


# ==============================================================================
# 2. THEME MANAGER TESTS
# ==============================================================================

class TestThemeManager:
    def test_valid_themes_constants(self):
        assert "dark" in VALID_THEMES
        assert "light" in VALID_THEMES
        assert "system" in VALID_THEMES
        assert DEFAULT_THEME == "dark"

    def test_resolve_concrete_themes(self):
        assert resolve_theme("dark") == "dark"
        assert resolve_theme("light") == "light"
        assert resolve_theme("DARK") == "dark"
        assert resolve_theme("LIGHT") == "light"
        assert resolve_theme("unknown") == DEFAULT_THEME

    def test_resolve_system_theme(self):
        with patch("theme_manager.get_system_theme", return_value="light"):
            assert resolve_theme("system") == "light"
        with patch("theme_manager.get_system_theme", return_value="dark"):
            assert resolve_theme("system") == "dark"

    def test_get_system_theme_env_override(self, monkeypatch):
        monkeypatch.setenv("GTK_THEME", "Adwaita:dark")
        assert get_system_theme() == "dark"

        monkeypatch.setenv("GTK_THEME", "Adwaita:light")
        assert get_system_theme() == "light"

    def test_dark_theme_css_content(self):
        css = get_theme_css("dark")
        # Check background palette
        assert "#0d1117" in css or "#202020" in css
        assert "#161b22" in css or "#242424" in css
        # Check high contrast text
        assert "#e6edf3" in css or "#f2f2f2" in css
        # Check accents
        assert "#60cdff" in css or "#00c8d0" in css or "#00adb5" in css
        # Check fluent classes
        assert ".fluent-sidebar" in css
        assert ".fluent-card" in css
        assert ".fluent-btn-primary" in css
        assert ".badge-ok" in css
        assert "switch" in css

    def test_light_theme_css_content(self):
        css = get_theme_css("light")
        # Check clean light background #f8fafc / #ffffff
        assert "#f8fafc" in css
        assert "#ffffff" in css
        # Check high contrast text #0f172a
        assert "#0f172a" in css
        # Check borders #e2e8f0
        assert "#e2e8f0" in css
        # Check fluent classes
        assert ".fluent-sidebar" in css
        assert ".fluent-card" in css
        assert ".fluent-btn-primary" in css
        assert ".badge-ok" in css
        assert "switch" in css

    def test_theme_manager_toggle(self):
        tm = ThemeManager(current_theme="dark")
        assert tm.current_theme == "dark"

        new_t = tm.toggle()
        assert new_t == "light"
        assert tm.current_theme == "light"

        new_t = tm.toggle()
        assert new_t == "dark"
        assert tm.current_theme == "dark"

    def test_load_theme_creates_provider(self):
        provider = load_theme("dark")
        assert isinstance(provider, Gtk.CssProvider)

        # Reload with light theme into existing provider
        updated = load_theme("light", gtk_css_provider=provider)
        assert updated is provider


# ==============================================================================
# 3. A11Y & SHORTCUTS TESTS
# ==============================================================================

class TestShortcutsAndA11y:
    def test_shortcut_pages_count_and_mapping(self):
        assert len(SHORTCUT_PAGES) == 9
        assert SHORTCUT_PAGES[0] == "dashboard"
        assert SHORTCUT_PAGES[1] == "presets"
        assert SHORTCUT_PAGES[8] == "settings"

    def test_setup_window_shortcuts_attaches_key_press(self):
        win = MagicMock()
        setup_window_shortcuts(win)
        win.connect.assert_called_once()
        assert win.connect.call_args[0][0] == "key-press-event"

    def test_f1_triggers_help_callback(self):
        win = MagicMock()
        on_help = MagicMock()
        setup_window_shortcuts(win, on_help=on_help)

        # Retrieve the handler connected to key-press-event
        handler = win.connect.call_args[0][1]

        event = MagicMock()
        event.keyval = 0xFFBE  # Gdk.KEY_F1
        event.state = 0

        res = handler(win, event)
        assert res is True
        on_help.assert_called_once()

    def test_ctrl_q_triggers_quit_callback(self):
        win = MagicMock()
        on_quit = MagicMock()
        setup_window_shortcuts(win, on_quit=on_quit)

        handler = win.connect.call_args[0][1]

        event = MagicMock()
        event.keyval = ord("q")
        event.state = Gdk.ModifierType.CONTROL_MASK

        res = handler(win, event)
        assert res is True
        on_quit.assert_called_once()

    def test_ctrl_numbers_trigger_page_switch(self):
        win = MagicMock()
        on_switch = MagicMock()
        setup_window_shortcuts(win, on_switch_page=on_switch)

        handler = win.connect.call_args[0][1]

        # Test Ctrl+1 through Ctrl+9
        for idx in range(1, 10):
            event = MagicMock()
            event.keyval = ord(str(idx))
            event.state = Gdk.ModifierType.CONTROL_MASK

            res = handler(win, event)
            assert res is True
            expected_page = SHORTCUT_PAGES[idx - 1]
            on_switch.assert_called_with(expected_page)

    def test_apply_a11y_tooltips(self):
        win = MagicMock()
        btn_dash = MagicMock()
        btn_presets = MagicMock()
        btn_settings = MagicMock()

        win.nav_buttons = {
            "dashboard": btn_dash,
            "presets": btn_presets,
            "settings": btn_settings,
        }

        apply_a11y_tooltips(win)

        btn_dash.set_tooltip_text.assert_called_once()
        tooltip_dash = btn_dash.set_tooltip_text.call_args[0][0]
        assert "Ctrl+1" in tooltip_dash

        btn_presets.set_tooltip_text.assert_called_once()
        tooltip_presets = btn_presets.set_tooltip_text.call_args[0][0]
        assert "Ctrl+2" in tooltip_presets

        btn_settings.set_tooltip_text.assert_called_once()
        tooltip_settings = btn_settings.set_tooltip_text.call_args[0][0]
        assert "Ctrl+9" in tooltip_settings


# ==============================================================================
# 4. INTEGRATION TEST WITH ZAPRET2APP
# ==============================================================================

@patch("main.MirrorHealthMonitor")
@patch("main.get_healer")
@patch("main.subprocess.run")
def test_zapret2app_geometry_and_theme_integration(mock_subp, mock_get_healer, mock_mirror, tmp_path):
    mock_subp.return_value = MagicMock(returncode=0, stdout="INACTIVE\n", stderr="")
    fake_healer = MagicMock()
    fake_healer.status = "OK"
    mock_get_healer.return_value = fake_healer

    from main import Zapret2App

    app = Zapret2App(minimized=True)

    # Verify geometry attributes exist
    assert hasattr(app, "window_width")
    assert hasattr(app, "window_height")
    assert hasattr(app, "window_maximized")
    assert hasattr(app, "last_page")
    assert hasattr(app, "theme")

    # Verify theme switching works
    app.set_theme("light")
    assert app.theme == "light"

    app.set_theme("dark")
    assert app.theme == "dark"

    # Verify tooltips are present on nav buttons
    for key, btn in app.nav_buttons.items():
        assert btn.get_tooltip_text() is not None

    if hasattr(app, "mirror_monitor"):
        try:
            app.mirror_monitor.stop()
        except Exception:
            pass
    app.destroy()
