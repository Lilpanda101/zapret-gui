#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from unittest.mock import MagicMock, patch
import pytest
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, Gdk

from persistent_bar import (
    PersistentStatusBar,
    create_persistent_bar,
    is_display_available,
    install_persistent_bar_css,
)
from status_presenter import StatusPresenter, compute_status_view, StatusViewData


@pytest.fixture(autouse=True)
def check_display():
    """Ensure display is available before instantiating GTK components directly."""
    if not is_display_available():
        pytest.skip("GTK display unavailable, skipping UI widget tests")


def test_init_defaults():
    bar = PersistentStatusBar()
    assert isinstance(bar, Gtk.Box)
    assert bar.get_orientation() == Gtk.Orientation.HORIZONTAL
    assert bar.current_state == "INACTIVE"
    assert bar.is_running is False
    assert bar.active_preset == "General"
    assert bar.engine_mode == "nfqws2"

    # Status badge
    assert bar.status_badge.get_text() == "○ Остановлен"
    ctx = bar.status_badge.get_style_context()
    assert ctx.has_class("badge-bad")

    # Info label
    assert "Пресет: General • nfqws2" in bar.lbl_info.get_text()

    # Quick toggle button
    assert bar.btn_toggle.get_label() == "▶ Запустить"
    assert bar.btn_toggle.get_can_focus() is True
    btn_ctx = bar.btn_toggle.get_style_context()
    assert btn_ctx.has_class("fluent-btn-primary")
    assert not btn_ctx.has_class("fluent-btn-danger")
    assert "Запустить" in bar.btn_toggle.get_tooltip_text()


def test_update_status_active():
    bar = PersistentStatusBar()
    data = compute_status_view("ACTIVE", "nfqws2")

    bar.update_status(data, active_preset="YouTube & Discord", engine_mode="nfqws2")

    assert bar.current_state == "ACTIVE"
    assert bar.is_running is True
    assert bar.status_badge.get_text() == "🟢 Активен"
    ctx = bar.status_badge.get_style_context()
    assert ctx.has_class("badge-ok")
    assert not ctx.has_class("badge-bad")
    assert not ctx.has_class("badge-warn")

    assert "Пресет: YouTube & Discord • nfqws2" in bar.lbl_info.get_text()

    assert bar.btn_toggle.get_label() == "■ Остановить"
    btn_ctx = bar.btn_toggle.get_style_context()
    assert btn_ctx.has_class("fluent-btn-danger")
    assert not btn_ctx.has_class("fluent-btn-primary")
    assert "Остановить" in bar.btn_toggle.get_tooltip_text()


def test_update_status_nfqws_only():
    bar = PersistentStatusBar()
    data = compute_status_view("NFQWS_ONLY", "tpws")

    bar.update_status(data, active_preset="General", engine_mode="tpws")

    assert bar.current_state == "NFQWS_ONLY"
    assert bar.is_running is True
    assert bar.status_badge.get_text() == "🟡 Внимание"
    ctx = bar.status_badge.get_style_context()
    assert ctx.has_class("badge-warn")
    assert not ctx.has_class("badge-ok")

    assert "Пресет: General • tpws" in bar.lbl_info.get_text()
    assert bar.btn_toggle.get_label() == "■ Остановить"
    btn_ctx = bar.btn_toggle.get_style_context()
    assert btn_ctx.has_class("fluent-btn-danger")


def test_update_status_inactive():
    bar = PersistentStatusBar(active_preset="Gaming", engine_mode="nfqws2")
    # First set to active
    bar.update_status(compute_status_view("ACTIVE", "nfqws2"))
    assert bar.is_running is True

    # Now transition to inactive
    data_inactive = compute_status_view("INACTIVE", "nfqws2")
    bar.update_status(data_inactive)

    assert bar.current_state == "INACTIVE"
    assert bar.is_running is False
    assert bar.status_badge.get_text() == "○ Остановлен"
    ctx = bar.status_badge.get_style_context()
    assert ctx.has_class("badge-bad")
    assert not ctx.has_class("badge-ok")

    assert bar.btn_toggle.get_label() == "▶ Запустить"
    btn_ctx = bar.btn_toggle.get_style_context()
    assert btn_ctx.has_class("fluent-btn-primary")
    assert not btn_ctx.has_class("fluent-btn-danger")


def test_update_status_string_and_kwargs():
    bar = PersistentStatusBar()

    # Pass string state directly
    bar.update_status("ACTIVE", active_preset="Preset A", engine_mode="nfqws2")
    assert bar.current_state == "ACTIVE"
    assert bar.is_running is True
    assert bar.status_badge.get_text() == "🟢 Активен"
    assert "Preset A" in bar.lbl_info.get_text()

    # Pass via state keyword
    bar.update_status(state="INACTIVE", active_preset="Preset B")
    assert bar.current_state == "INACTIVE"
    assert bar.is_running is False
    assert bar.status_badge.get_text() == "○ Остановлен"
    assert "Preset B" in bar.lbl_info.get_text()


def test_toggle_button_callback_constructor():
    cb = MagicMock()
    bar = PersistentStatusBar(on_toggle=cb)

    bar.btn_toggle.clicked()
    cb.assert_called_once()


def test_toggle_button_callback_methods_and_attributes():
    bar = PersistentStatusBar()

    # 1. set_toggle_callback
    cb1 = MagicMock()
    bar.set_toggle_callback(cb1)
    bar.btn_toggle.clicked()
    cb1.assert_called_once()

    # 2. toggle_engine attribute
    bar.on_toggle = None
    cb2 = MagicMock()
    bar.toggle_engine = cb2
    bar.btn_toggle.clicked()
    cb2.assert_called_once()

    # 3. on_toggle_clicked attribute
    bar.toggle_engine = None
    cb3 = MagicMock()
    bar.on_toggle_clicked = cb3
    bar.btn_toggle.clicked()
    cb3.assert_called_once()


def test_preset_and_engine_mode_changes():
    bar = PersistentStatusBar(active_preset="InitPreset", engine_mode="nfqws2")
    assert "Пресет: InitPreset • nfqws2" in bar.lbl_info.get_text()

    # Method setters
    bar.set_preset("Discord Voice")
    assert bar.active_preset == "Discord Voice"
    assert "Пресет: Discord Voice • nfqws2" in bar.lbl_info.get_text()

    bar.set_engine_mode("tpws")
    assert bar.engine_mode == "tpws"
    assert "Пресет: Discord Voice • tpws" in bar.lbl_info.get_text()

    # Property setters
    bar.active_preset = "Custom Profile"
    bar.engine_mode = "nfqws v1"
    assert bar.active_preset == "Custom Profile"
    assert bar.engine_mode == "nfqws v1"
    assert "Пресет: Custom Profile • nfqws v1" in bar.lbl_info.get_text()


def test_keyboard_accessibility():
    cb = MagicMock()
    bar = PersistentStatusBar(on_toggle=cb)

    # Must be focusable via Tab
    assert bar.btn_toggle.get_can_focus() is True

    # Tooltip must be descriptive
    assert len(bar.btn_toggle.get_tooltip_text()) > 0
    assert "обход" in bar.btn_toggle.get_tooltip_text().lower()

    # Key press event simulation for Enter/Return key
    class FakeEvent:
        def __init__(self, keyval):
            self.keyval = keyval

    # Enter key triggers clicked
    res = bar._on_btn_key_press(bar.btn_toggle, FakeEvent(Gdk.KEY_Return))
    assert res is True
    cb.assert_called_once()

    # KP_Enter triggers clicked
    cb.reset_mock()
    res = bar._on_btn_key_press(bar.btn_toggle, FakeEvent(Gdk.KEY_KP_Enter))
    assert res is True
    cb.assert_called_once()

    # Non-enter key returns False and does not trigger extra clicked
    cb.reset_mock()
    res = bar._on_btn_key_press(bar.btn_toggle, FakeEvent(Gdk.KEY_Tab))
    assert res is False
    cb.assert_not_called()


def test_status_presenter_integration():
    class FakeApp:
        def __init__(self):
            self.active_preset = "General"
            self.engine_mode = "nfqws2"
            self.is_running = False
            self.status_title = MagicMock()
            self.status_desc = MagicMock()
            self.btn_toggle = MagicMock()
            self.btn_toggle.get_style_context.return_value = MagicMock()
            self.status_banner = MagicMock()
            self.status_banner.get_style_context.return_value = MagicMock()
            self.pill_status = MagicMock()
            self.pill_status.get_style_context.return_value = MagicMock()
            self.persistent_bar = PersistentStatusBar(
                active_preset=self.active_preset,
                engine_mode=self.engine_mode,
            )

        def update_persistent_bar(self, data: StatusViewData):
            self.persistent_bar.update_status(data, self.active_preset, self.engine_mode)

    app = FakeApp()
    presenter = StatusPresenter(app)

    # 1. Apply ACTIVE
    presenter.apply("ACTIVE")
    assert app.persistent_bar.current_state == "ACTIVE"
    assert app.persistent_bar.is_running is True
    assert app.persistent_bar.status_badge.get_text() == "🟢 Активен"
    assert app.persistent_bar.btn_toggle.get_label() == "■ Остановить"

    # 2. Change preset in app and apply NFQWS_ONLY
    app.active_preset = "YouTube Fix"
    presenter.apply("NFQWS_ONLY")
    assert app.persistent_bar.current_state == "NFQWS_ONLY"
    assert app.persistent_bar.is_running is True
    assert app.persistent_bar.status_badge.get_text() == "🟡 Внимание"
    assert "YouTube Fix" in app.persistent_bar.lbl_info.get_text()

    # 3. Apply INACTIVE
    presenter.apply("INACTIVE")
    assert app.persistent_bar.current_state == "INACTIVE"
    assert app.persistent_bar.is_running is False
    assert app.persistent_bar.status_badge.get_text() == "○ Остановлен"
    assert app.persistent_bar.btn_toggle.get_label() == "▶ Запустить"


def test_headless_display_check():
    # True case (under display)
    assert is_display_available() is True
    bar = create_persistent_bar()
    assert isinstance(bar, PersistentStatusBar)

    # Mocked unavailable display
    with patch("gi.repository.Gtk.init_check", return_value=(False, [])):
        assert is_display_available() is False
        bar_headless = create_persistent_bar()
        assert bar_headless is None


def test_css_install():
    # Should not raise any exceptions
    install_persistent_bar_css()
