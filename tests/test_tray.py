#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tests/test_tray.py - Комплексные тесты для TrayManager и цепочки детекции трея.
"""

from unittest.mock import MagicMock
import pytest
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

pytestmark = pytest.mark.filterwarnings(
    "ignore::gi.PyGIWarning",
    "ignore::UserWarning",
)

from tray_manager import (
    TrayManager,
    detect_tray_backend,
    BACKEND_AYATANA,
    BACKEND_APPINDICATOR,
    BACKEND_STATUS_ICON,
    BACKEND_NONE,
    FALLBACK_GUIDANCE_TIP,
)


class TestTrayDetectionChain:
    """Тестирование цепочки обнаружения возможностей (capability detection)."""

    def test_detect_backend_ayatana(self, monkeypatch):
        """Попытка 1: AyatanaAppIndicator3 доступен."""
        def fake_require_version(namespace, version):
            if namespace == "AyatanaAppIndicator3":
                return
            raise ValueError(f"Unknown {namespace}")

        monkeypatch.setattr(gi, "require_version", fake_require_version)

        backend, mod = detect_tray_backend()
        assert backend == BACKEND_AYATANA
        assert mod is not None
        assert hasattr(mod, "Indicator")

    def test_detect_backend_appindicator(self, monkeypatch):
        """Попытка 2: Ayatana недоступен, но AppIndicator3 доступен."""
        def fake_require_version(namespace, version):
            if namespace == "AyatanaAppIndicator3":
                raise ValueError("Namespace AyatanaAppIndicator3 not available")
            if namespace == "AppIndicator3":
                return
            raise ValueError(f"Unknown {namespace}")

        monkeypatch.setattr(gi, "require_version", fake_require_version)

        backend, mod = detect_tray_backend()
        assert backend == BACKEND_APPINDICATOR
        assert mod is not None
        assert hasattr(mod, "Indicator")

    def test_detect_backend_status_icon(self, monkeypatch):
        """Попытка 3: Оба AppIndicator недоступны, используется Gtk.StatusIcon."""
        def fake_require_version(namespace, version):
            raise ValueError(f"Namespace {namespace} not available")

        monkeypatch.setattr(gi, "require_version", fake_require_version)

        backend, mod = detect_tray_backend()
        assert backend == BACKEND_STATUS_ICON
        assert mod == Gtk.StatusIcon

    def test_detect_backend_none_when_all_fail(self, monkeypatch):
        """Попытка 4 (Fallback): Все бэкенды недоступны -> backend='none'."""
        def fake_require_version(namespace, version):
            raise ValueError(f"Namespace {namespace} not available")

        monkeypatch.setattr(gi, "require_version", fake_require_version)
        monkeypatch.setattr(Gtk, "StatusIcon", None)

        backend, mod = detect_tray_backend()
        assert backend == BACKEND_NONE
        assert mod is None


class TestTrayManagerFallback:
    """Тестирование безопасного перехода в режим backend='none' (graceful degradation)."""

    def test_fallback_none_mode_properties(self):
        tm = TrayManager(force_backend=BACKEND_NONE)

        assert tm.backend == BACKEND_NONE
        assert tm.is_available() is False
        assert tm.indicator is None
        assert tm.status_icon is None
        assert tm.guidance_tip == FALLBACK_GUIDANCE_TIP
        assert "Системный трей недоступен" in tm.fallback_reason

    def test_fallback_none_methods_are_safe(self):
        """Вызовы методов обновления статуса и меню не падают при backend='none'."""
        tm = TrayManager(force_backend=BACKEND_NONE)

        # Ничего не должно выбрасывать исключений
        tm.update_status(True, current_preset="preset-1")
        assert tm.is_running is True
        assert tm.current_preset == "preset-1"
        assert tm.status_item.get_label() == "Статус: Активен (preset-1)"

        tm.update_status(False)
        assert tm.is_running is False
        assert tm.status_item.get_label() == "Статус: Остановлен"

        tm.rebuild_presets_menu([("p1", "Title 1"), ("p2", "Title 2")], "p1")
        assert len(tm.presets_submenu.get_children()) == 2

    def test_indicator_init_failure_degrades_to_none(self, monkeypatch):
        """Если создание индикатора падает с ошибкой, TrayManager деградирует в 'none'."""
        fake_mod = MagicMock()
        fake_mod.Indicator.new.side_effect = RuntimeError("D-Bus initialization failed")
        fake_mod.IndicatorCategory.APPLICATION_STATUS = 1
        fake_mod.IndicatorStatus.ACTIVE = 1

        monkeypatch.setattr("tray_manager.detect_tray_backend", lambda: (BACKEND_AYATANA, fake_mod))

        tm = TrayManager()
        assert tm.backend == BACKEND_NONE
        assert tm.is_available() is False
        assert tm.indicator is None
        assert "Ошибка инициализации" in tm.fallback_reason

    def test_status_icon_init_failure_degrades_to_none(self, monkeypatch):
        """Если создание Gtk.StatusIcon падает с ошибкой, TrayManager деградирует в 'none'."""
        monkeypatch.setattr("tray_manager.detect_tray_backend", lambda: (BACKEND_STATUS_ICON, Gtk.StatusIcon))
        monkeypatch.setattr(Gtk.StatusIcon, "new_from_icon_name", MagicMock(side_effect=RuntimeError("X11 error")))
        monkeypatch.setattr(Gtk.StatusIcon, "new_from_file", MagicMock(side_effect=RuntimeError("X11 error")))

        tm = TrayManager()
        assert tm.backend == BACKEND_NONE
        assert tm.is_available() is False
        assert tm.status_icon is None
        assert "Ошибка инициализации" in tm.fallback_reason


class TestTrayMenuAndCallbacks:
    """Тестирование пунктов меню, подменю пресетов и срабатывания колбэков."""

    def test_menu_structure_exists(self):
        tm = TrayManager(force_backend=BACKEND_NONE)

        assert isinstance(tm.menu, Gtk.Menu)
        assert isinstance(tm.status_item, Gtk.MenuItem)
        assert isinstance(tm.toggle_item, Gtk.MenuItem)
        assert isinstance(tm.presets_root_item, Gtk.MenuItem)
        assert isinstance(tm.presets_submenu, Gtk.Menu)
        assert isinstance(tm.show_hide_item, Gtk.MenuItem)
        assert isinstance(tm.quit_item, Gtk.MenuItem)

        assert tm.status_item.get_sensitive() is False

    def test_toggle_bypass_callback_with_arg(self):
        received = []
        tm = TrayManager(
            force_backend=BACKEND_NONE,
            on_toggle_bypass=lambda state: received.append(state),
        )
        assert tm.is_running is False

        # Клик по кнопке переключения обхода (сейчас остановлен -> передает True)
        tm.toggle_item.activate()
        assert received == [True]

        # Теперь переключаем в статус running
        tm.update_status(True)
        tm.toggle_item.activate()
        assert received == [True, False]

    def test_toggle_bypass_callback_no_arg(self):
        called = []
        tm = TrayManager(
            force_backend=BACKEND_NONE,
            on_toggle_bypass=lambda: called.append(True),
        )
        tm.toggle_item.activate()
        assert called == [True]

    def test_show_hide_and_quit_callbacks(self):
        show_hide_called = []
        quit_called = []

        tm = TrayManager(
            force_backend=BACKEND_NONE,
            on_show_hide=lambda: show_hide_called.append(True),
            on_quit=lambda: quit_called.append(True),
        )

        tm.show_hide_item.activate()
        assert show_hide_called == [True]

        tm.quit_item.activate()
        assert quit_called == [True]

    def test_presets_submenu_rebuild_and_click(self):
        selected_presets = []
        tm = TrayManager(
            force_backend=BACKEND_NONE,
            on_preset_selected=lambda pid: selected_presets.append(pid),
        )

        presets = [
            ("preset_ultra", "Ultra Speed 1000"),
            ("preset_discord", "Discord Voice Fix"),
            ("preset_youtube", "YouTube 4K"),
        ]

        tm.rebuild_presets_menu(presets, active_preset_id="preset_discord")

        children = tm.presets_submenu.get_children()
        assert len(children) == 3

        assert children[0].get_label() == "Ultra Speed 1000"
        assert children[1].get_label() == "● Discord Voice Fix"
        assert children[2].get_label() == "YouTube 4K"

        # Кликаем на первый пресет
        children[0].activate()
        assert selected_presets == ["preset_ultra"]
        assert tm.active_preset_id == "preset_ultra"

        # Кликаем на третий пресет
        children[2].activate()
        assert selected_presets == ["preset_ultra", "preset_youtube"]
        assert tm.active_preset_id == "preset_youtube"

    def test_presets_empty_shows_disabled_item(self):
        tm = TrayManager(force_backend=BACKEND_NONE)
        tm.rebuild_presets_menu([])

        children = tm.presets_submenu.get_children()
        assert len(children) == 1
        assert children[0].get_sensitive() is False
        assert "Нет доступных" in children[0].get_label()

    def test_update_status_updates_labels(self):
        tm = TrayManager(force_backend=BACKEND_NONE)

        tm.update_status(True, current_preset="nfqws2-special")
        assert "Активен" in tm.status_item.get_label()
        assert "nfqws2-special" in tm.status_item.get_label()
        assert tm.toggle_item.get_label() == "■ Остановить обход"

        tm.update_status(False)
        assert "Остановлен" in tm.status_item.get_label()
        assert tm.toggle_item.get_label() == "▶ Запустить обход"

    def test_status_icon_popup_menu_handler(self, monkeypatch):
        """Проверяем обработчик popup-menu для Gtk.StatusIcon."""
        tm = TrayManager(force_backend=BACKEND_NONE)
        mock_popup = MagicMock()
        monkeypatch.setattr(tm.menu, "popup", mock_popup)

        tm._on_status_icon_popup(None, 3, 0)
        assert mock_popup.called
