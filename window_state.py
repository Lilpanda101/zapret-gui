#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Window State & Geometry Manager for Zapret GUI Linux.
Handles persisting and restoring window size, maximized state, last visited page,
and configures accessibility keyboard shortcuts (F1, Ctrl+Q, Ctrl+1..9) and tooltips.
"""

from __future__ import annotations
import logging
from typing import Optional, Callable, Dict, Any

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gtk, Gdk
    GTK_AVAILABLE = True
except (ImportError, ValueError):
    GTK_AVAILABLE = False

logger = logging.getLogger("zapret_gui.window_state")

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 720
MIN_WIDTH = 640
MIN_HEIGHT = 480
MAX_WIDTH = 7680
MAX_HEIGHT = 4320

DEFAULT_PAGE = "dashboard"

VALID_PAGES = (
    "dashboard",
    "presets",
    "profiles",
    "zapret2",
    "dpi_mode",
    "monitor",
    "dns",
    "hosts",
    "updates",
    "blockcheck",
    "logs",
    "settings",
)

# Ordered mapping for Ctrl+1..9 shortcuts
SHORTCUT_PAGES = [
    "dashboard",   # Ctrl+1
    "presets",     # Ctrl+2
    "profiles",    # Ctrl+3
    "zapret2",     # Ctrl+4
    "dpi_mode",    # Ctrl+5
    "monitor",     # Ctrl+6
    "dns",         # Ctrl+7
    "hosts",       # Ctrl+8
    "settings",    # Ctrl+9
]


def clamp_dimension(val: Any, default: int, min_val: int, max_val: int) -> int:
    """Safely clamp window width/height."""
    try:
        ival = int(val)
        if ival < min_val:
            return min_val
        if ival > max_val:
            return max_val
        return ival
    except (TypeError, ValueError):
        return default


def is_window_maximized(window: Any) -> bool:
    """Check if window is maximized safely."""
    # Check manual tracking flag first
    if hasattr(window, "_is_maximized"):
        return bool(window._is_maximized)
    # Check Gtk.Window method if available
    if hasattr(window, "is_maximized") and callable(window.is_maximized):
        try:
            return bool(window.is_maximized())
        except Exception:
            pass
    # Check GdkWindow state if realized
    if hasattr(window, "get_window") and callable(window.get_window):
        try:
            gdk_win = window.get_window()
            if gdk_win:
                state = gdk_win.get_state()
                return bool(state & Gdk.WindowState.MAXIMIZED)
        except Exception:
            pass
    return False


def save_window_state(window: Any, current_page: str, config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save current window dimensions, maximized state, and last visited page into config dict.
    Returns the updated config dictionary.
    """
    if config is None:
        config = {}

    maximized = is_window_maximized(window)
    config["window_maximized"] = maximized

    # Retrieve window dimensions
    width = None
    height = None

    raw_w = getattr(window, "window_width", None)
    raw_h = getattr(window, "window_height", None)
    if isinstance(raw_w, int) and isinstance(raw_h, int) and raw_w != DEFAULT_WIDTH:
        width = raw_w
        height = raw_h
    elif hasattr(window, "get_size") and callable(window.get_size):
        try:
            w, h = window.get_size()
            if isinstance(w, int) and isinstance(h, int):
                width, height = w, h
        except Exception as e:
            logger.debug("Failed to get_size from window: %s", e)
    elif isinstance(raw_w, int) and isinstance(raw_h, int):
        width = raw_w
        height = raw_h

    # If maximized, retain the previous unmaximized dimensions if tracked
    if maximized:
        saved_w = getattr(window, "_unmaximized_width", getattr(window, "window_width", config.get("window_width", DEFAULT_WIDTH)))
        saved_h = getattr(window, "_unmaximized_height", getattr(window, "window_height", config.get("window_height", DEFAULT_HEIGHT)))
        w_clamped = clamp_dimension(saved_w, DEFAULT_WIDTH, MIN_WIDTH, MAX_WIDTH)
        h_clamped = clamp_dimension(saved_h, DEFAULT_HEIGHT, MIN_HEIGHT, MAX_HEIGHT)
        config["window_width"] = w_clamped
        config["window_height"] = h_clamped
        window.window_width = w_clamped
        window.window_height = h_clamped
    else:
        if width is not None and height is not None:
            w_clamped = clamp_dimension(width, DEFAULT_WIDTH, MIN_WIDTH, MAX_WIDTH)
            h_clamped = clamp_dimension(height, DEFAULT_HEIGHT, MIN_HEIGHT, MAX_HEIGHT)
            config["window_width"] = w_clamped
            config["window_height"] = h_clamped
            window.window_width = w_clamped
            window.window_height = h_clamped
            window._unmaximized_width = w_clamped
            window._unmaximized_height = h_clamped

    # Save last visited page
    page = (current_page or "").strip()
    if page in VALID_PAGES:
        config["last_page"] = page
    elif "last_page" not in config:
        config["last_page"] = DEFAULT_PAGE

    return config


def restore_window_state(window: Any, config: Dict[str, Any]) -> str:
    """
    Restore window dimensions and maximized state from config dict.
    Returns the last visited page name for switching the UI stack.
    """
    if not isinstance(config, dict):
        config = {}

    width = clamp_dimension(config.get("window_width"), DEFAULT_WIDTH, MIN_WIDTH, MAX_WIDTH)
    height = clamp_dimension(config.get("window_height"), DEFAULT_HEIGHT, MIN_HEIGHT, MAX_HEIGHT)
    is_maximized = bool(config.get("window_maximized", False))

    if hasattr(window, "set_default_size") and callable(window.set_default_size):
        try:
            window.set_default_size(width, height)
        except Exception as e:
            logger.debug("Failed to set_default_size: %s", e)

    if hasattr(window, "resize") and callable(window.resize):
        try:
            window.resize(width, height)
        except Exception:
            pass

    # Cache unmaximized dimensions on window instance
    window.window_width = width
    window.window_height = height
    window._unmaximized_width = width
    window._unmaximized_height = height
    window._is_maximized = is_maximized

    if is_maximized:
        if hasattr(window, "maximize") and callable(window.maximize):
            try:
                window.maximize()
            except Exception as e:
                logger.debug("Failed to maximize window: %s", e)
    else:
        if hasattr(window, "unmaximize") and callable(window.unmaximize):
            try:
                window.unmaximize()
            except Exception:
                pass

    last_page = config.get("last_page", DEFAULT_PAGE)
    if last_page not in VALID_PAGES:
        last_page = DEFAULT_PAGE
    window.last_page = last_page

    return last_page


def bind_window_geometry_events(window: Any, on_change_callback: Optional[Callable[[], None]] = None):
    """
    Attach 'configure-event' and 'window-state-event' handlers to track resizing and maximizing.
    """
    if not hasattr(window, "connect") or not callable(window.connect):
        return

    def on_window_state(widget, event):
        try:
            if hasattr(event, "new_window_state"):
                is_max = bool(event.new_window_state & Gdk.WindowState.MAXIMIZED)
                widget._is_maximized = is_max
                if on_change_callback:
                    on_change_callback()
        except Exception:
            pass
        return False

    def on_configure(widget, event):
        try:
            if not getattr(widget, "_is_maximized", False):
                if hasattr(event, "width") and hasattr(event, "height"):
                    if event.width >= MIN_WIDTH and event.height >= MIN_HEIGHT:
                        widget._unmaximized_width = event.width
                        widget._unmaximized_height = event.height
        except Exception:
            pass
        return False

    try:
        window.connect("window-state-event", on_window_state)
        window.connect("configure-event", on_configure)
    except Exception as e:
        logger.debug("Could not bind window geometry events: %s", e)


def setup_window_shortcuts(
    window: Any,
    on_switch_page: Optional[Callable[[str], None]] = None,
    on_help: Optional[Callable[[], None]] = None,
    on_quit: Optional[Callable[[], None]] = None,
    on_refresh: Optional[Callable[[], None]] = None,
):
    """
    Setup accessible keyboard shortcuts:
    - F1: Help / tour
    - F5 / Ctrl+R: Refresh status
    - Ctrl+Q: Exit application
    - Ctrl+1..9: Switch to pages (1: dashboard, 2: presets, ..., 9: settings)
    """
    if not hasattr(window, "connect") or not callable(window.connect):
        return

    # Key constants
    KEY_F1 = 0xFFBE
    KEY_F5 = 0xFFC2
    KEY_Q_LOWER = 0x0071
    KEY_Q_UPPER = 0x0051
    KEY_R_LOWER = 0x0072
    KEY_R_UPPER = 0x0052

    # Numbers 1..9
    NUMBER_KEYS = {
        0x0031: 0, 0xFFB1: 0,  # 1, KP_1
        0x0032: 1, 0xFFB2: 1,  # 2, KP_2
        0x0033: 2, 0xFFB3: 2,  # 3, KP_3
        0x0034: 3, 0xFFB4: 3,  # 4, KP_4
        0x0035: 4, 0xFFB5: 4,  # 5, KP_5
        0x0036: 5, 0xFFB6: 5,  # 6, KP_6
        0x0037: 6, 0xFFB7: 6,  # 7, KP_7
        0x0038: 7, 0xFFB8: 7,  # 8, KP_8
        0x0039: 8, 0xFFB9: 8,  # 9, KP_9
    }

    def on_key_press(widget, event):
        keyval = getattr(event, "keyval", None)
        state = getattr(event, "state", 0)

        if keyval is None:
            return False

        ctrl_pressed = bool(state & Gdk.ModifierType.CONTROL_MASK) if GTK_AVAILABLE else False

        # F1: Help
        if keyval == KEY_F1:
            if on_help and callable(on_help):
                on_help()
                return True

        # F5 / Ctrl+R: Refresh
        if keyval == KEY_F5 or (ctrl_pressed and keyval in (KEY_R_LOWER, KEY_R_UPPER)):
            if hasattr(widget, "refresh_status") and callable(widget.refresh_status):
                widget.refresh_status()
                return True
            elif on_refresh and callable(on_refresh):
                on_refresh()
                return True

        # Ctrl+Q: Quit
        if ctrl_pressed and (keyval in (KEY_Q_LOWER, KEY_Q_UPPER)):
            if on_quit and callable(on_quit):
                on_quit()
            elif hasattr(widget, "quit_app") and callable(widget.quit_app):
                widget.quit_app(None)
            elif hasattr(widget, "close") and callable(widget.close):
                widget.close()
            return True

        # Ctrl+1..9: Switch Page
        if ctrl_pressed and keyval in NUMBER_KEYS:
            page_idx = NUMBER_KEYS[keyval]
            if 0 <= page_idx < len(SHORTCUT_PAGES):
                target_page = SHORTCUT_PAGES[page_idx]
                if on_switch_page and callable(on_switch_page):
                    on_switch_page(target_page)
                    return True
                elif hasattr(widget, "switch_to_tab") and callable(widget.switch_to_tab):
                    widget.switch_to_tab(target_page)
                    return True

        return False

    window._shortcut_handler = on_key_press
    try:
        window.connect("key-press-event", on_key_press)
    except Exception as e:
        logger.debug("Failed to connect key-press-event: %s", e)


def apply_a11y_tooltips(window: Any):
    """
    Ensure all primary navigation buttons, toggles, and controls have helpful accessible tooltips.
    """
    tooltips = {
        "dashboard": "Панель управления: состояние обхода, быстрый пуск и метрики (Ctrl+1)",
        "presets": "Пресеты обхода: выбор готовых стратегий для сайтов и сервисов (Ctrl+2)",
        "profiles": "Профили: переключение готовых наборов настроек (Ctrl+3)",
        "zapret2": "Zapret 2: тонкая настройка параметров nfqws2 и стратегий (Ctrl+4)",
        "dpi_mode": "Режимы DPI: выбор ядер tpws, nfqws или nfqws2 (Ctrl+5)",
        "monitor": "Мониторинг сети: пинг зеркал и доступность серверов (Ctrl+6)",
        "dns": "Настройка DNS: выбор безопасных и быстрых резолверов (Ctrl+7)",
        "hosts": "Редактор хостов: списки доменов и IP адресов (Ctrl+8)",
        "updates": "Обновления: проверка версий и загрузка баз Zapret",
        "blockcheck": "BlockCheck: диагностика блокировок и тест стратегий",
        "logs": "Журнал: просмотр логов демона и сетевых событий",
        "settings": "Настройки: выбор сетевого адаптера, автозапуск, тема оформления (Ctrl+9)",
    }

    nav_buttons = getattr(window, "nav_buttons", {})
    if isinstance(nav_buttons, dict):
        for name, btn in nav_buttons.items():
            if name in tooltips and hasattr(btn, "set_tooltip_text"):
                btn.set_tooltip_text(tooltips[name])
