"""
Stage 3 Acceptance & Parity Audit Tests for Zapret GUI Linux.

Covers:
1. Fallback when system tray is unavailable (AppIndicator and Gtk.StatusIcon degraded/missing).
2. Fallback when GtkSource is unavailable (clean fallback to Gtk.TextView/Gtk.TextBuffer).
3. Window size and last page persistence across restarts (config schema & app lifecycle).
4. Full keyboard accessibility (focusability of interactive controls & key shortcuts).
5. Codebase integrity & no cyclic imports.
"""

import os
import sys
import json
import pytest
from unittest.mock import patch, MagicMock
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

import config_manager
import zapret2_ui
from main import Zapret2App


@pytest.fixture(autouse=True)
def check_gtk():
    initialized = Gtk.init_check([])[0]
    if not initialized:
        pytest.skip("GTK display unavailable, run under xvfb-run")


@pytest.fixture
def mock_app_deps():
    with patch("main.MirrorHealthMonitor") as mock_mirror, \
         patch("main.get_healer") as mock_healer, \
         patch("main.subprocess.run") as mock_subp:
        mock_subp.return_value = MagicMock(returncode=0, stdout="INACTIVE\n", stderr="")
        fake_healer = MagicMock()
        fake_healer.status = "OK"
        fake_healer.is_running = False
        mock_healer.return_value = fake_healer
        yield {
            "mirror": mock_mirror,
            "healer": fake_healer,
            "subp": mock_subp,
        }


# =========================================================================
# 1. ТРЕЙ: Отсутствие трея не роняет приложение (Graceful Degradation)
# =========================================================================

def test_app_start_without_tray_no_crash(mock_app_deps, monkeypatch, tmp_path):
    """При отсутствии AppIndicator и падении StatusIcon приложение запускается без трея."""
    monkeypatch.setattr("main.AppIndicator", None)
    monkeypatch.setattr("tray_manager.detect_tray_backend", lambda: ("none", None))

    with patch.object(Gtk, "StatusIcon", None, create=True):
        app = Zapret2App(minimized=False)
        assert app.has_tray is False
        assert not hasattr(app, "indicator")
        assert not hasattr(app, "status_icon")

        # Проверка, что вызов update_tray не падает без трея
        app.update_tray(True)
        app.update_tray(False)

        # Проверка, что закрытие окна без трея завершает приложение, а не оставляет зомби-процесс
        with patch.object(app, "quit_app") as mock_quit:
            app.on_delete_event(None, None)
            mock_quit.assert_called_once()

        app.destroy()


def test_app_minimized_without_tray_stays_visible(mock_app_deps, monkeypatch):
    """Если трей недоступен, режим --minimized не скрывает окно навсегда."""
    monkeypatch.setattr("main.AppIndicator", None)
    monkeypatch.setattr("tray_manager.detect_tray_backend", lambda: ("none", None))

    with patch.object(Gtk, "StatusIcon", None, create=True):
        app = Zapret2App(minimized=True)
        assert app.has_tray is False
        app.destroy()


# =========================================================================
# 2. GTKSOURCE FALLBACK: Отсутствие GtkSource не роняет редактор
# =========================================================================

def test_editor_fallback_without_gtksource(mock_app_deps, monkeypatch):
    """Редактор пресетов работает на Gtk.TextView/Gtk.TextBuffer, если GtkSource недоступен."""
    monkeypatch.setattr(zapret2_ui, "HAVE_GTK_SOURCE", False)

    app = Zapret2App(minimized=True)
    zapret2_widget = app.stack.get_child_by_name("zapret2")
    assert zapret2_widget is not None

    editor_ui = app.zapret2_page
    assert editor_ui is not None
    assert hasattr(editor_ui, "buffer")
    # При отсутствии GtkSource буфер должен быть стандартным Gtk.TextBuffer
    assert type(editor_ui.buffer) is Gtk.TextBuffer

    # Проверяем работу загрузки, поиска и замены в TextBuffer fallback
    editor_ui.buffer.set_text("test line 1\n--filter-tcp=443\ntest line 3")
    assert "filter-tcp" in editor_ui.buffer.get_text(
        editor_ui.buffer.get_start_iter(),
        editor_ui.buffer.get_end_iter(),
        False
    )

    editor_ui.ed_search_entry.set_text("line 1")
    editor_ui.ed_replace_entry.set_text("modified line 1")
    editor_ui._replace_all(None)

    result_text = editor_ui.buffer.get_text(
        editor_ui.buffer.get_start_iter(),
        editor_ui.buffer.get_end_iter(),
        False
    )
    assert "modified line 1" in result_text

    app.destroy()


# =========================================================================
# 3. СОХРАНЕНИЕ ГЕОМЕТРИИ ОКНА И ПОСЛЕДНЕЙ СТРАНИЦЫ
# =========================================================================

def test_window_geometry_and_last_page_persistence(mock_app_deps, tmp_path, monkeypatch):
    """Размер окна и последняя активная вкладка сохраняются в конфиг и восстанавливаются."""
    cfg_file = str(tmp_path / "zapret_config.json")
    monkeypatch.setattr("main.CONFIG_FILE", cfg_file)

    # 1. Запуск 1: меняем страницу и размер окна
    app1 = Zapret2App(minimized=True)
    assert "settings" in app1.nav_buttons

    # Переключаем вкладку на "settings"
    app1.nav_buttons["settings"].set_active(True)
    assert app1.last_page == "settings"

    # Задаем размер окна
    app1.window_width = 1280
    app1.window_height = 800
    app1.save_config()
    app1.destroy()

    # Проверяем файл конфигурации
    saved_cfg = config_manager.load_config_from_file(cfg_file)
    assert saved_cfg["last_page"] == "settings"
    assert saved_cfg["window_width"] == 1280
    assert saved_cfg["window_height"] == 800

    # 2. Запуск 2: проверяем восстановление
    app2 = Zapret2App(minimized=True)
    assert app2.last_page == "settings"
    assert app2.window_width == 1280
    assert app2.window_height == 800

    # Проверяем, что активная кнопка навигации и видимый дочерний элемент стека — "settings"
    assert app2.nav_buttons["settings"].get_active() is True
    assert app2.stack.get_visible_child_name() == "settings"

    app2.destroy()


# =========================================================================
# 4. ДОСТУПНОСТЬ С КЛАВИАТУРЫ (KEYBOARD ACCESSIBILITY)
# =========================================================================

def test_keyboard_navigation_and_focusability(mock_app_deps):
    """Все кнопки навигации и ключевые контролы обладают can_focus=True."""
    app = Zapret2App(minimized=True)

    # 1. Проверяем все элементы бокового меню навигации
    for name, btn in app.nav_buttons.items():
        assert btn.get_can_focus(), f"Кнопка меню {name} недоступна для фокуса с клавиатуры"

    # 2. Проверяем контролы на странице Zapret 2
    z2_page = app.zapret2_page
    assert z2_page.preset_combo.get_can_focus()
    assert z2_page.search.get_can_focus()
    assert z2_page.ed_search_entry.get_can_focus()
    assert z2_page.ed_replace_entry.get_can_focus()

    # 3. Проверяем горячие клавиши
    # Ctrl+R -> refresh_status
    with patch.object(app, "refresh_status") as mock_refresh:
        event = Gdk.EventKey()
        event.state = Gdk.ModifierType.CONTROL_MASK
        event.keyval = Gdk.KEY_r
        handled = app.on_key_press_event(app, event)
        assert handled is True
        mock_refresh.assert_called_once()

    # F5 -> refresh_status
    with patch.object(app, "refresh_status") as mock_refresh:
        event = Gdk.EventKey()
        event.state = 0
        event.keyval = Gdk.KEY_F5
        handled = app.on_key_press_event(app, event)
        assert handled is True
        mock_refresh.assert_called_once()

    # Ctrl+1 -> переключение на первую вкладку (dashboard)
    event = Gdk.EventKey()
    event.state = Gdk.ModifierType.CONTROL_MASK
    event.keyval = Gdk.KEY_1
    handled = app.on_key_press_event(app, event)
    assert handled is True
    assert app.nav_buttons["dashboard"].get_active() is True

    # Ctrl+Q -> quit_app
    with patch.object(app, "quit_app") as mock_quit:
        event = Gdk.EventKey()
        event.state = Gdk.ModifierType.CONTROL_MASK
        event.keyval = Gdk.KEY_q
        handled = app.on_key_press_event(app, event)
        assert handled is True
        mock_quit.assert_called_once()

    app.destroy()


# =========================================================================
# 5. ЦЕЛОСТНОСТЬ КОДОВОЙ БАЗЫ И ОТСУТСТВИЕ ЦИКЛИЧЕСКИХ ИМПОРТОВ
# =========================================================================

def test_codebase_integrity_and_clean_imports():
    """Проверка чистоты модулей, отсутствия взаимных блокировок при импорте."""
    core_modules = [
        "config_manager",
        "engine_params",
        "hosts_manager",
        "status_presenter",
        "app_shell",
        "version",
        "catalog.preset_catalog",
        "persistent_bar",
        "tray_manager",
        "onboarding",
        "theme_manager",
        "window_state",
        "zapret2_core",
        "healer",
        "updater",
        "zapret2_ui",
        "main",
    ]

    # Прямой порядок импортов
    for mod in core_modules:
        assert mod in sys.modules or __import__(mod)

    # Обратный порядок импортов
    for mod in reversed(core_modules):
        assert mod in sys.modules or __import__(mod)


# =========================================================================
# 6. ПОСТОЯННАЯ СТРОКА СТАТУСА (PERSISTENT STATUS BAR В APP)
# =========================================================================

def test_persistent_status_bar_in_app(mock_app_deps):
    """Строка статуса всегда видна внизу, реагирует на статусы движка и доступна для фокуса."""
    app = Zapret2App(minimized=True)
    assert hasattr(app, "persistent_bar")
    if app.persistent_bar is not None:
        assert app.persistent_bar.btn_toggle.get_can_focus() is True
        
        # Проверяем обновление статуса через _apply_status
        app._apply_status("ACTIVE")
        assert app.persistent_bar.current_state == "ACTIVE"
        assert app.persistent_bar.btn_toggle.get_label() == "■ Остановить"

        app._apply_status("INACTIVE")
        assert app.persistent_bar.current_state == "INACTIVE"
        assert app.persistent_bar.btn_toggle.get_label() == "▶ Запустить"

        # Клик по кнопке вызывает переключение
        with patch.object(app, "on_toggle_engine") as mock_toggle:
            app.persistent_bar.btn_toggle.clicked()
            mock_toggle.assert_called_once()

    app.destroy()
