#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Persistent Status Bar component for Zapret GUI Linux.
Provides an always-visible bottom status bar displaying:
- Engine status indicator / badge (🟢 Активен / 🟡 Внимание / ○ Остановлен)
- Current preset & engine mode information (e.g. "Пресет: General • nfqws2")
- Quick toggle button (click-to-toggle: "▶ Запустить" / "■ Остановить")
with full keyboard accessibility (can_focus, Enter/Space activation, tooltips)
and seamless integration with StatusPresenter / StatusViewData.
"""

from __future__ import annotations
from typing import Any, Callable, Optional, Union
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from status_presenter import StatusViewData, compute_status_view


def is_display_available() -> bool:
    """Checks if a GTK display is available (useful for headless / CI environments)."""
    try:
        res = Gtk.init_check([])
        if isinstance(res, tuple):
            return bool(res[0])
        return bool(res)
    except Exception:
        return False


STATUS_BADGE_CONFIG = {
    "ACTIVE": {
        "text": "🟢 Активен",
        "css_class": "badge-ok",
        "tooltip": "Обход DPI активен и правила перехвата трафика работают.",
    },
    "NFQWS_ONLY": {
        "text": "🟡 Внимание",
        "css_class": "badge-warn",
        "tooltip": "Движок nfqws запущен, но правила перехвата nftables отсутствуют.",
    },
    "INACTIVE": {
        "text": "○ Остановлен",
        "css_class": "badge-bad",
        "tooltip": "Zapret остановлен. Десинхронизация DPI выключена.",
    },
}

PERSISTENT_BAR_CSS = """
.persistent-status-bar {
    background-color: #171722;
    border-top: 1px solid #2a2a3c;
    padding: 6px 16px;
}

.persistent-bar-info {
    color: #a0a0b8;
    font-size: 13px;
    font-weight: 500;
}

.persistent-toggle-btn {
    min-width: 130px;
    font-size: 13px;
    padding: 6px 16px;
    border-radius: 6px;
}
"""


def install_persistent_bar_css() -> None:
    """Installs CSS styling for persistent status bar into the default Gtk screen."""
    try:
        screen = Gdk.Screen.get_default()
        if screen is None:
            return
        provider = Gtk.CssProvider()
        provider.load_from_data(PERSISTENT_BAR_CSS.encode("utf-8"))
        Gtk.StyleContext.add_provider_for_screen(
            screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION
        )
    except Exception:
        pass


class PersistentStatusBar(Gtk.Box):
    """
    Bottom persistent status bar for Zapret GUI.
    Always visible in UI (bottom of window or content area).
    """

    def __init__(
        self,
        on_toggle: Optional[Callable[[], Any]] = None,
        active_preset: str = "General",
        engine_mode: str = "nfqws2",
        **kwargs: Any,
    ):
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)

        # Support both on_toggle and toggle_engine kwargs
        self.on_toggle = on_toggle or kwargs.get("toggle_engine") or kwargs.get("on_toggle_clicked")
        self._active_preset = str(active_preset)
        self._engine_mode = str(engine_mode)
        self._current_state = "INACTIVE"
        self._is_running = False

        # Visual container configuration
        self.get_style_context().add_class("persistent-status-bar")
        self.set_margin_start(16)
        self.set_margin_end(16)
        self.set_margin_top(6)
        self.set_margin_bottom(6)

        # Left section: Status Badge + Preset/Engine Info
        self.info_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.info_box.set_valign(Gtk.Align.CENTER)

        # 1. Status badge
        self.status_badge = Gtk.Label(label="○ Остановлен")
        self.status_badge.get_style_context().add_class("badge-bad")
        self.status_badge.set_valign(Gtk.Align.CENTER)
        self.status_badge.set_tooltip_text(STATUS_BADGE_CONFIG["INACTIVE"]["tooltip"])
        # Aliases
        self.lbl_status = self.status_badge
        self.badge = self.status_badge

        # 2. Preset & Engine info
        self.lbl_info = Gtk.Label(label=self._format_info_text(self._active_preset, self._engine_mode))
        self.lbl_info.get_style_context().add_class("persistent-bar-info")
        self.lbl_info.set_valign(Gtk.Align.CENTER)
        self.lbl_info.set_xalign(0)
        self.lbl_info.set_tooltip_text(f"Пресет: {self._active_preset} • Движок: {self._engine_mode}")
        # Aliases
        self.lbl_preset_engine = self.lbl_info

        self.info_box.pack_start(self.status_badge, False, False, 0)
        self.info_box.pack_start(self.lbl_info, False, False, 0)
        self.pack_start(self.info_box, False, False, 0)

        # 3. Spacer to expand and push toggle button to the far right
        self.spacer = Gtk.Box()
        self.spacer.set_hexpand(True)
        self.pack_start(self.spacer, True, True, 0)

        # 4. Action button: Click-to-toggle
        self.btn_toggle = Gtk.Button(label="▶ Запустить")
        self.btn_toggle.set_valign(Gtk.Align.CENTER)
        self.btn_toggle.set_can_focus(True)
        self.btn_toggle.set_focus_on_click(True)
        self.btn_toggle.set_tooltip_text("Запустить обход DPI (Пробел / Enter)")
        self.btn_toggle.get_style_context().add_class("fluent-btn-primary")
        self.btn_toggle.get_style_context().add_class("persistent-toggle-btn")

        # Accessibility role name if ATK available
        try:
            accessible = self.btn_toggle.get_accessible()
            if accessible:
                accessible.set_name("Переключатель работы Zapret")
        except Exception:
            pass

        self.btn_toggle.connect("clicked", self._on_btn_clicked)
        self.btn_toggle.connect("key-press-event", self._on_btn_key_press)

        # Aliases
        self.toggle_button = self.btn_toggle
        self.pack_end(self.btn_toggle, False, False, 0)

    # ----------------------------------------------------------------------
    # Formatting & Helpers
    # ----------------------------------------------------------------------
    @staticmethod
    def _format_info_text(active_preset: str, engine_mode: str) -> str:
        preset_clean = active_preset.strip() if active_preset else "General"
        mode_clean = engine_mode.strip() if engine_mode else "nfqws2"
        return f"Пресет: {preset_clean} • {mode_clean}"

    # ----------------------------------------------------------------------
    # Properties & Setters
    # ----------------------------------------------------------------------
    @property
    def active_preset(self) -> str:
        return self._active_preset

    @active_preset.setter
    def active_preset(self, val: str) -> None:
        self.set_preset(val)

    @property
    def engine_mode(self) -> str:
        return self._engine_mode

    @engine_mode.setter
    def engine_mode(self, val: str) -> None:
        self.set_engine_mode(val)

    @property
    def current_state(self) -> str:
        return self._current_state

    @property
    def is_running(self) -> bool:
        return self._is_running

    def set_preset(self, preset: str) -> None:
        """Update displayed active preset."""
        self._active_preset = str(preset) if preset else "General"
        self._refresh_info_label()

    def set_engine_mode(self, mode: str) -> None:
        """Update displayed engine mode."""
        self._engine_mode = str(mode) if mode else "nfqws2"
        self._refresh_info_label()

    def set_toggle_callback(self, callback: Callable[[], Any]) -> None:
        """Sets the callback invoked when the toggle button is clicked or activated."""
        self.on_toggle = callback

    def _refresh_info_label(self) -> None:
        text = self._format_info_text(self._active_preset, self._engine_mode)
        self.lbl_info.set_text(text)
        self.lbl_info.set_tooltip_text(f"Пресет: {self._active_preset} • Движок: {self._engine_mode}")

    # ----------------------------------------------------------------------
    # Event Handlers & Accessibility
    # ----------------------------------------------------------------------
    def _on_btn_clicked(self, widget: Gtk.Button) -> None:
        """Dispatches toggle callback."""
        if callable(self.on_toggle):
            self.on_toggle()
        elif callable(getattr(self, "toggle_engine", None)):
            self.toggle_engine()
        elif callable(getattr(self, "on_toggle_clicked", None)):
            self.on_toggle_clicked()

    def _on_btn_key_press(self, widget: Gtk.Widget, event: Any) -> bool:
        """Keyboard accessibility: triggers activation on Enter/Return keys."""
        keyval = getattr(event, "keyval", None)
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter, Gdk.KEY_ISO_Enter):
            # Space is handled natively by Gtk.Button; Return is explicitly mapped
            if isinstance(widget, Gtk.Button):
                widget.clicked()
                return True
        return False

    # ----------------------------------------------------------------------
    # Integration with StatusPresenter
    # ----------------------------------------------------------------------
    def update_status(
        self,
        data: Optional[Union[StatusViewData, str]] = None,
        active_preset: Optional[str] = None,
        engine_mode: Optional[str] = None,
        state: Optional[str] = None,
    ) -> None:
        """
        Updates the persistent status bar state.
        Compatible with StatusPresenter:
        update_status(data: StatusViewData, active_preset: str, engine_mode: str)
        or can be called with keyword arguments or state string.
        """
        if active_preset is not None:
            self._active_preset = str(active_preset)
        if engine_mode is not None:
            self._engine_mode = str(engine_mode)

        # Resolve StatusViewData
        view_data: StatusViewData
        if isinstance(data, StatusViewData):
            view_data = data
        elif isinstance(data, str):
            view_data = compute_status_view(data, self._engine_mode)
        elif state is not None:
            view_data = compute_status_view(state, self._engine_mode)
        else:
            view_data = compute_status_view(self._current_state, self._engine_mode)

        self._current_state = view_data.state
        self._is_running = view_data.is_running

        # 1. Update status badge
        badge_cfg = STATUS_BADGE_CONFIG.get(self._current_state, STATUS_BADGE_CONFIG["INACTIVE"])
        badge_text = badge_cfg["text"]
        badge_cls = badge_cfg["css_class"]

        badge_ctx = self.status_badge.get_style_context()
        badge_ctx.remove_class("badge-ok")
        badge_ctx.remove_class("badge-warn")
        badge_ctx.remove_class("badge-bad")
        badge_ctx.add_class(badge_cls)
        self.status_badge.set_text(badge_text)
        self.status_badge.set_tooltip_text(view_data.desc_text or badge_cfg["tooltip"])

        # 2. Update info label
        self._refresh_info_label()

        # 3. Update quick toggle button
        btn_ctx = self.btn_toggle.get_style_context()
        if self._is_running:
            self.btn_toggle.set_label("■ Остановить")
            btn_ctx.remove_class("fluent-btn-primary")
            btn_ctx.add_class("fluent-btn-danger")
            self.btn_toggle.set_tooltip_text("Остановить обход DPI (Пробел / Enter)")
        else:
            self.btn_toggle.set_label("▶ Запустить")
            btn_ctx.remove_class("fluent-btn-danger")
            btn_ctx.add_class("fluent-btn-primary")
            self.btn_toggle.set_tooltip_text("Запустить обход DPI (Пробел / Enter)")


def create_persistent_bar(
    on_toggle: Optional[Callable[[], Any]] = None,
    active_preset: str = "General",
    engine_mode: str = "nfqws2",
) -> Optional[PersistentStatusBar]:
    """
    Safely creates a PersistentStatusBar if a GTK display is available,
    otherwise returns None (useful for headless / CI environments).
    """
    if not is_display_available():
        return None
    return PersistentStatusBar(
        on_toggle=on_toggle,
        active_preset=active_preset,
        engine_mode=engine_mode,
    )
