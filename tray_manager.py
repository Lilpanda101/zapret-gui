#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tray_manager.py - Менеджер системного трея для Zapret GUI Linux.

Реализует отказоустойчивую цепочку обнаружения возможностей (capability detection):
1. Попытка 1: AyatanaAppIndicator3 ('AyatanaAppIndicator3', '0.1')
2. Попытка 2: AppIndicator3 ('AppIndicator3', '0.1')
3. Попытка 3: Gtk.StatusIcon (legacy X11/XFCE/MATE/KDE)
4. Fallback: graceful degradation в backend="none" без крашей и без фантомных пустых квадратов.
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Callable, List, Optional, Tuple

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

logger = logging.getLogger(__name__)

# Константы бэкендов
BACKEND_AYATANA = "ayatana"
BACKEND_APPINDICATOR = "appindicator"
BACKEND_STATUS_ICON = "status_icon"
BACKEND_NONE = "none"

FALLBACK_GUIDANCE_TIP = (
    "Системный трей недоступен в вашей графической среде. "
    "Установите расширение AppIndicator / libayatana-appindicator "
    "или используйте приложение через панель задач."
)


def detect_tray_backend(gi_module=None, gtk_module=None) -> Tuple[str, object]:
    """
    Выполняет строгую цепочку проверки доступности бэкендов трея:
    1. AyatanaAppIndicator3
    2. AppIndicator3
    3. Gtk.StatusIcon
    4. Fallback -> BACKEND_NONE, None
    """
    target_gi = gi_module if gi_module is not None else gi
    target_gtk = gtk_module if gtk_module is not None else Gtk

    # 1. Попытка: AyatanaAppIndicator3
    try:
        target_gi.require_version("AyatanaAppIndicator3", "0.1")
        mod = sys.modules.get("gi.repository.AyatanaAppIndicator3")
        if mod is None:
            import importlib
            mod = importlib.import_module("gi.repository.AyatanaAppIndicator3")
        if hasattr(mod, "Indicator"):
            return BACKEND_AYATANA, mod
    except (ValueError, ImportError, AttributeError, Exception) as e:
        logger.debug("AyatanaAppIndicator3 недоступен: %s", e)

    # 2. Попытка: AppIndicator3
    try:
        target_gi.require_version("AppIndicator3", "0.1")
        mod = sys.modules.get("gi.repository.AppIndicator3")
        if mod is None:
            import importlib
            mod = importlib.import_module("gi.repository.AppIndicator3")
        if hasattr(mod, "Indicator"):
            return BACKEND_APPINDICATOR, mod
    except (ValueError, ImportError, AttributeError, Exception) as e:
        logger.debug("AppIndicator3 недоступен: %s", e)

    # 3. Попытка: Gtk.StatusIcon
    try:
        if target_gtk is not None and getattr(target_gtk, "StatusIcon", None) is not None:
            return BACKEND_STATUS_ICON, target_gtk.StatusIcon
    except (ImportError, AttributeError, Exception) as e:
        logger.debug("Gtk.StatusIcon недоступен: %s", e)

    # 4. Fallback
    return BACKEND_NONE, None


class TrayManager:
    """
    Управляет системным треем, значком статуса и контекстным меню Zapret GUI.
    """

    def __init__(
        self,
        app_id: str = "zapret-gui",
        icon_path: Optional[str] = None,
        icon_theme_path: Optional[str] = None,
        on_toggle_bypass: Optional[Callable] = None,
        on_preset_selected: Optional[Callable[[str], None]] = None,
        on_show_hide: Optional[Callable] = None,
        on_open_clicked: Optional[Callable] = None,
        on_quit: Optional[Callable] = None,
        force_backend: Optional[str] = None,
        auto_init: bool = True,
    ):
        self.app_id = app_id
        self.icon_theme_path = icon_theme_path or os.path.dirname(os.path.abspath(__file__))

        if icon_path:
            self.icon_path = icon_path
        else:
            default_svg = os.path.join(self.icon_theme_path, "icon.svg")
            self.icon_path = default_svg if os.path.exists(default_svg) else "network-vpn"

        self.on_toggle_bypass = on_toggle_bypass
        self.on_preset_selected = on_preset_selected
        self.on_show_hide = on_show_hide or on_open_clicked
        self.on_quit = on_quit

        self.is_running: bool = False
        self.current_preset: Optional[str] = None
        self.active_preset_id: str = ""
        self.presets: List[Tuple[str, str]] = []

        self._fallback_reason: Optional[str] = None
        self.backend: str = BACKEND_NONE
        self._backend_mod: object = None

        self.indicator: object = None
        self.status_icon: object = None

        # Виджеты меню Gtk
        self.menu: Optional[Gtk.Menu] = None
        self.status_item: Optional[Gtk.MenuItem] = None
        self.toggle_item: Optional[Gtk.MenuItem] = None
        self.presets_root_item: Optional[Gtk.MenuItem] = None
        self.presets_submenu: Optional[Gtk.Menu] = None
        self.show_hide_item: Optional[Gtk.MenuItem] = None
        self.quit_item: Optional[Gtk.MenuItem] = None

        # Создаем структуру контекстного меню
        self._build_menu()

        # Алиасы для обратной совместимости с кодовой базой
        self.tray_menu = self.menu
        self.tray_status_item = self.status_item
        self.tray_toggle_item = self.toggle_item

        if auto_init:
            self._init_backend(force_backend)

    def is_available(self) -> bool:
        """Возвращает True, если трей успешно поднят в окружении."""
        return self.backend != BACKEND_NONE

    @property
    def guidance_tip(self) -> str:
        """Человекочитаемое руководство в случае отсутствия трея."""
        return FALLBACK_GUIDANCE_TIP

    @property
    def fallback_reason(self) -> str:
        """Диагностическая причина отсутствия трея."""
        if not self.is_available():
            return self._fallback_reason or FALLBACK_GUIDANCE_TIP
        return ""

    @fallback_reason.setter
    def fallback_reason(self, val: str) -> None:
        self._fallback_reason = val

    def _build_menu(self) -> None:
        """Формирует меню трея со всеми обязательными пунктами."""
        self.menu = Gtk.Menu()

        # 1. Текущий статус
        self.status_item = Gtk.MenuItem(label="Статус: Остановлен")
        self.status_item.set_sensitive(False)
        self.menu.append(self.status_item)

        # 2. Переключатель обхода
        self.toggle_item = Gtk.MenuItem(label="▶ Запустить обход")
        self.toggle_item.connect("activate", self._handle_toggle_bypass)
        self.menu.append(self.toggle_item)

        # Разделитель
        self.menu.append(Gtk.SeparatorMenuItem())

        # 3. Меню выбора пресетов
        self.presets_root_item = Gtk.MenuItem(label="Пресеты")
        self.presets_submenu = Gtk.Menu()
        self.presets_root_item.set_submenu(self.presets_submenu)
        self.menu.append(self.presets_root_item)

        # Разделитель
        self.menu.append(Gtk.SeparatorMenuItem())

        # 4. Показать / Скрыть окно
        self.show_hide_item = Gtk.MenuItem(label="Показать/Скрыть окно")
        self.show_hide_item.connect("activate", self._handle_show_hide)
        self.menu.append(self.show_hide_item)

        # 5. Выход
        self.quit_item = Gtk.MenuItem(label="Выход")
        self.quit_item.connect("activate", self._handle_quit)
        self.menu.append(self.quit_item)

        self.menu.show_all()

    def _init_backend(self, force_backend: Optional[str] = None) -> None:
        """Инициализирует выбранный бэкенд или деградирует в BACKEND_NONE."""
        if force_backend:
            if force_backend == BACKEND_NONE:
                self.backend = BACKEND_NONE
                self._fallback_reason = FALLBACK_GUIDANCE_TIP
                return
            elif force_backend == BACKEND_STATUS_ICON:
                self.backend = BACKEND_STATUS_ICON
                self._backend_mod = Gtk.StatusIcon
            elif force_backend in (BACKEND_AYATANA, BACKEND_APPINDICATOR):
                pkg = "AyatanaAppIndicator3" if force_backend == BACKEND_AYATANA else "AppIndicator3"
                try:
                    gi.require_version(pkg, "0.1")
                    from gi.repository import AyatanaAppIndicator3, AppIndicator3
                    self._backend_mod = AyatanaAppIndicator3 if force_backend == BACKEND_AYATANA else AppIndicator3
                    self.backend = force_backend
                except Exception as e:
                    self.backend = BACKEND_NONE
                    self._fallback_reason = f"Ошибка инициализации {force_backend}: {e}"
                    return
        else:
            self.backend, self._backend_mod = detect_tray_backend()

        if self.backend == BACKEND_NONE:
            self._fallback_reason = FALLBACK_GUIDANCE_TIP
            return

        # Настройка AppIndicator / Ayatana
        if self.backend in (BACKEND_AYATANA, BACKEND_APPINDICATOR):
            try:
                indicator_cls = getattr(self._backend_mod, "Indicator", None)
                if indicator_cls is None:
                    raise AttributeError(f"{self.backend} не предоставляет класс Indicator")

                category = getattr(self._backend_mod, "IndicatorCategory", None)
                cat_val = category.APPLICATION_STATUS if category else 0

                self.indicator = indicator_cls.new(
                    self.app_id,
                    self.icon_path,
                    cat_val,
                )

                if hasattr(self.indicator, "set_icon_theme_path") and self.icon_theme_path:
                    self.indicator.set_icon_theme_path(self.icon_theme_path)

                status_enum = getattr(self._backend_mod, "IndicatorStatus", None)
                if status_enum and hasattr(self.indicator, "set_status"):
                    self.indicator.set_status(status_enum.ACTIVE)

                if hasattr(self.indicator, "set_menu"):
                    self.indicator.set_menu(self.menu)
            except Exception as e:
                logger.warning("Сбой создания индикатора %s: %s", self.backend, e)
                self.backend = BACKEND_NONE
                self._fallback_reason = f"Ошибка инициализации {self.backend}: {e}"
                self.indicator = None

        # Настройка Gtk.StatusIcon
        elif self.backend == BACKEND_STATUS_ICON:
            try:
                if os.path.exists(self.icon_path):
                    self.status_icon = Gtk.StatusIcon.new_from_file(self.icon_path)
                else:
                    self.status_icon = Gtk.StatusIcon.new_from_icon_name(self.icon_path)

                self.status_icon.connect("popup-menu", self._on_status_icon_popup)
                self.status_icon.connect("activate", self._handle_show_hide)
                self.status_icon.set_visible(True)
            except Exception as e:
                logger.warning("Сбой создания Gtk.StatusIcon: %s", e)
                self.backend = BACKEND_NONE
                self._fallback_reason = f"Ошибка инициализации Gtk.StatusIcon: {e}"
                self.status_icon = None

    def _on_status_icon_popup(self, icon, button, activate_time):
        if self.menu:
            self.menu.popup(None, None, Gtk.StatusIcon.position_menu, icon, button, activate_time)

    def _handle_toggle_bypass(self, _widget=None):
        if self.on_toggle_bypass:
            try:
                self.on_toggle_bypass(not self.is_running)
            except TypeError:
                self.on_toggle_bypass()

    def _handle_show_hide(self, _widget=None):
        if self.on_show_hide:
            self.on_show_hide()

    def _handle_quit(self, _widget=None):
        if self.on_quit:
            self.on_quit()

    def _handle_preset_selected(self, _widget, preset_id: str):
        self.active_preset_id = preset_id
        if self.on_preset_selected:
            self.on_preset_selected(preset_id)

    def rebuild_presets_menu(self, presets: List[Tuple[str, str]], active_preset_id: str = "") -> None:
        """
        Динамически обновляет подменю «Пресеты».
        presets: список кортежей (preset_id, preset_title).
        active_preset_id: идентификатор текущего выбранного пресета.
        """
        self.presets = list(presets)
        if active_preset_id:
            self.active_preset_id = active_preset_id

        if self.presets_submenu is None:
            return

        for child in self.presets_submenu.get_children():
            self.presets_submenu.remove(child)

        if not presets:
            empty_item = Gtk.MenuItem(label="Нет доступных пресетов")
            empty_item.set_sensitive(False)
            self.presets_submenu.append(empty_item)
        else:
            for pid, title in presets:
                is_active = (pid == self.active_preset_id)
                label = f"● {title}" if is_active else title
                item = Gtk.MenuItem(label=label)
                item.connect("activate", self._handle_preset_selected, pid)
                self.presets_submenu.append(item)

        self.presets_submenu.show_all()

    def update_status(self, is_running: bool, current_preset: Optional[str] = None) -> None:
        """
        Обновляет статус работы обхода, подписи пунктов меню и состояние иконки.
        """
        self.is_running = is_running
        if current_preset is not None:
            self.current_preset = current_preset

        if self.status_item:
            if is_running:
                p_text = f" ({self.current_preset})" if self.current_preset else ""
                self.status_item.set_label(f"Статус: Активен{p_text}")
            else:
                self.status_item.set_label("Статус: Остановлен")

        if self.toggle_item:
            self.toggle_item.set_label("■ Остановить обход" if is_running else "▶ Запустить обход")

        # Индикатор (Ayatana / AppIndicator)
        if self.indicator is not None and self._backend_mod is not None:
            try:
                status_enum = getattr(self._backend_mod, "IndicatorStatus", None)
                if status_enum and hasattr(self.indicator, "set_status"):
                    self.indicator.set_status(status_enum.ACTIVE)
            except Exception as e:
                logger.debug("Ошибка обновления индикатора: %s", e)

        # StatusIcon
        if self.status_icon is not None:
            try:
                tip = f"Zapret: {'Активен' if is_running else 'Остановлен'}"
                if is_running and self.current_preset:
                    tip += f" ({self.current_preset})"
                self.status_icon.set_tooltip_text(tip)
            except Exception as e:
                logger.debug("Ошибка обновления подсказки StatusIcon: %s", e)
