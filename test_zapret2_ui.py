from pathlib import Path
from unittest.mock import patch, MagicMock

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

import zapret2_core as core
import zapret2_ui as zui
from zapret2_ui import Zapret2Page, GAME_WARNING_TEXT, HEALTH_TARGETS


class DummyApp:
    zapret2_preset = "Default (circular)"
    engine_mode = "nfqws2"
    active_iface = "enp5s0"
    enable_auto_hostlist = False

    def __init__(self):
        self.errors = []
        self.saved_config_called = False

    def create_page_container(self, title, subtitle):
        scrolled = Gtk.ScrolledWindow()
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        scrolled.add(box)
        return scrolled, box

    def show_dialog(self, title, message):
        self.errors.append((title, message))

    def save_config(self):
        self.saved_config_called = True

    def update_top_tile_mode(self):
        pass

    def start_engine(self):
        pass


@pytest.fixture(autouse=True)
def check_gtk():
    initialized = Gtk.init_check([])[0]
    if not initialized:
        pytest.skip("GTK display is unavailable")


def test_gtk_catalog_and_profile_editor(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "USER_PRESETS", tmp_path)
    app = DummyApp()
    page = Zapret2Page(app)
    widget = page.create()
    assert widget is not None
    assert len(page.preset_combo.get_model()) == 136
    assert page.preset_id == "Default (circular).txt"
    assert page.document.profiles
    assert "--" in page.buffer.get_text(page.buffer.get_start_iter(), page.buffer.get_end_iter(), False)

    page.save_profile(None)
    saved = tmp_path / Path(page.preset_id).name
    assert saved.is_file()
    assert core.PresetDocument.parse(saved.read_text()).profiles
    assert not app.errors


def test_preset_categories_and_filtering(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "USER_PRESETS", tmp_path)
    app = DummyApp()
    page = Zapret2Page(app)
    widget = page.create()

    # Проверка наличия 4 кнопок-фильтров
    assert "recommended" in page.category_buttons
    assert "circular" in page.category_buttons
    assert "game" in page.category_buttons
    assert "all" in page.category_buttons

    # 1. Переключение на «Игровые (Game filter)»
    page.category_buttons["game"].set_active(True)
    game_count = len(page.preset_combo.get_model())
    assert 70 < game_count < 100
    # Проверяем, что в комбо только игровые пресеты
    model = page.preset_combo.get_model()
    for row in model:
        title = row[1].casefold()
        assert "game filter" in title or "gaming" in title

    # 2. Переключение на «Circular (Адаптивные)»
    page.category_buttons["circular"].set_active(True)
    circ_count = len(page.preset_combo.get_model())
    assert 25 < circ_count < 50

    # 3. Переключение на «🌟 Топ / Рекомендуемые»
    page.category_buttons["recommended"].set_active(True)
    rec_count = len(page.preset_combo.get_model())
    assert 10 < rec_count < 80

    # 4. Переключение обратно на «Все пресеты»
    page.category_buttons["all"].set_active(True)
    assert len(page.preset_combo.get_model()) == 136


def test_game_filter_warning_banner(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "USER_PRESETS", tmp_path)
    app = DummyApp()
    page = Zapret2Page(app)
    widget = page.create()

    # По умолчанию выбран 'Default (circular).txt' — баннер должен быть скрыт
    assert page.game_banner.get_visible() is False

    # Загружаем игровой пресет
    page.load_preset("Dead by Daylight (game filter).txt")
    assert page.game_banner.get_visible() is True

    # Загружаем обратно обычный пресет
    page.load_preset("Default (circular).txt")
    assert page.game_banner.get_visible() is False


def test_health_check_ui_and_verdicts(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "USER_PRESETS", tmp_path)
    app = DummyApp()
    page = Zapret2Page(app)
    widget = page.create()

    # Проверка наличия виджетов Health Check
    assert page.btn_health_test is not None
    assert len(page.health_badges) == 4
    for name, _ in HEALTH_TARGETS:
        assert name in page.health_badges

    # Тест обновления бейджа при успехе и ошибке
    page._update_health_badge("YouTube", True, 120, "OK")
    assert "🟢 OK (120 ms)" in page.health_badges["YouTube"].get_text()
    assert page.health_badges["YouTube"].get_style_context().has_class("badge-ok")

    page._update_health_badge("Rutracker", False, 9999, "Таймаут/RST")
    assert "🔴 Ошибка (Таймаут/RST)" in page.health_badges["Rutracker"].get_text()
    assert page.health_badges["Rutracker"].get_style_context().has_class("badge-bad")

    # Тест вердиктов:
    # 1. Все 4 успешны
    page._finish_health_test([
        ("YouTube", True, 100, "OK"),
        ("GoogleVideo Stream", True, 110, "OK"),
        ("Discord Gateway", True, 90, "OK"),
        ("Rutracker", True, 150, "OK"),
    ])
    assert "Пресет работает отлично" in page.health_verdict.get_text()
    assert page.health_verdict_badge.get_style_context().has_class("badge-ok")

    # 2. Частичный доступ (2 из 4)
    page._finish_health_test([
        ("YouTube", True, 100, "OK"),
        ("GoogleVideo Stream", True, 110, "OK"),
        ("Discord Gateway", False, 9999, "RST"),
        ("Rutracker", False, 9999, "Таймаут"),
    ])
    assert "Частичный доступ" in page.health_verdict.get_text()
    assert page.health_verdict_badge.get_style_context().has_class("badge-warn")

    # 3. Полная блокировка ТСПУ (0 из 4)
    page._finish_health_test([
        ("YouTube", False, 9999, "RST"),
        ("GoogleVideo Stream", False, 9999, "Таймаут"),
        ("Discord Gateway", False, 9999, "RST"),
        ("Rutracker", False, 9999, "Таймаут"),
    ])
    assert "Блокируется ТСПУ" in page.health_verdict.get_text()
    assert page.health_verdict_badge.get_style_context().has_class("badge-bad")


def test_check_url_health_logic():
    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_resp = MagicMock()
        mock_resp.status = 204
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        is_ok, dt, status = zui.check_url_health("https://www.youtube.com/generate_204")
        assert is_ok is True
        assert "OK" in status

    with patch("urllib.request.urlopen") as mock_urlopen:
        import socket
        mock_urlopen.side_effect = socket.timeout("timed out")
        is_ok, dt, status = zui.check_url_health("https://example.com")
        assert is_ok is False
        assert status == "Таймаут"

    with patch("urllib.request.urlopen") as mock_urlopen:
        mock_urlopen.side_effect = ConnectionResetError("connection reset by peer")
        is_ok, dt, status = zui.check_url_health("https://example.com")
        assert is_ok is False
        assert status == "RST"


def test_auto_hostlist_card(monkeypatch, tmp_path):
    monkeypatch.setattr(core, "USER_PRESETS", tmp_path / "presets")
    autohost_file = tmp_path / "autohostlist.txt"
    monkeypatch.setattr(core, "get_auto_hostlist_path", lambda: autohost_file)

    app = DummyApp()
    page = Zapret2Page(app)
    widget = page.create()

    assert page.sw_auto_hostlist is not None
    assert page.lbl_autohost_count is not None
    assert page.btn_clear_autohost is not None

    # Проверка переключателя
    page.sw_auto_hostlist.set_active(True)
    assert app.enable_auto_hostlist is True
    assert app.saved_config_called is True

    # Записываем тестовые домены в файл автохостлиста
    autohost_file.write_text("domain1.com\ndomain2.org\ndomain3.net\n", encoding="utf-8")
    page.update_autohost_count()
    assert "Захвачено доменов: 3" in page.lbl_autohost_count.get_text()

    # Очистка списка автохостов
    page.clear_autohostlist()
    assert autohost_file.read_text(encoding="utf-8") == ""
    assert "Захвачено доменов: 0" in page.lbl_autohost_count.get_text()
