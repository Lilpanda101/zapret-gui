import os
from pathlib import Path
import pytest

import zapret2_core as core
from zapret2_core import PresetDocument, PresetError, adapt_preset, check_preset_unsupported_options


def test_profile_skip_toggle_preserves_structure():
    """Проверяет отключение профиля через --skip без вырезания строк и с сохранением структуры --new."""
    text = (
        "--lua-init=@lua/init.lua\n"
        "--new\n"
        "--name=Main\n"
        "--filter-tcp=80,443\n"
        "--lua-desync=fake\n"
        "--new\n"
        "--name=Discord\n"
        "--filter-udp=50000-50100\n"
        "--lua-desync=fake\n"
    )
    doc = PresetDocument.parse(text)
    assert len(doc.profiles) == 2
    assert doc.profiles[0].enabled is True
    assert doc.profiles[1].enabled is True

    # Отключаем профиль 1 (Discord)
    doc.set_profile_enabled(1, False)
    assert doc.profiles[1].enabled is False
    profile1_text = doc.profile_text(1)
    assert "--skip" in profile1_text
    assert "--new" in profile1_text
    assert "--name=Discord" in profile1_text

    # Включаем профиль 1 обратно
    doc.set_profile_enabled(1, True)
    assert doc.profiles[1].enabled is True
    assert "--skip" not in doc.profile_text(1)


def test_skip_with_comment_recognized_and_cleaned():
    """Проверяет, что --skip с комментарием распознается как отключенный и корректно удаляется."""
    text = (
        "--new\n"
        "--name=Main\n"
        "--skip # временно отключен\n"
        "--filter-tcp=443\n"
        "--lua-desync=fake\n"
    )
    doc = PresetDocument.parse(text)
    assert doc.profiles[0].enabled is False

    # Включаем профиль
    doc.set_profile_enabled(0, True)
    assert doc.profiles[0].enabled is True
    assert "--skip" not in doc.text()


def test_replace_profile_preserves_new_directive():
    """Проверяет, что замена тела второго профиля текстом без --new автоматически сохраняет --new."""
    text = (
        "--new\n"
        "--name=First\n"
        "--filter-tcp=80\n"
        "--new\n"
        "--name=Second\n"
        "--filter-tcp=443\n"
    )
    doc = PresetDocument.parse(text)
    assert len(doc.profiles) == 2

    # Пользователь редактирует профиль 1 и стирает --new
    user_edited_text = "--name=SecondEdited\n--filter-tcp=8443\n--lua-desync=fake\n"
    doc.replace_profile(1, user_edited_text)

    # Профили не должны слиться, их по-прежнему должно быть ровно 2!
    assert len(doc.profiles) == 2
    assert doc.profiles[1].name == "SecondEdited"
    # Первая строка тела профиля 1 обязана быть --new
    body1 = doc.lines[doc.profiles[1].start:doc.profiles[1].end]
    assert body1[0].strip() == "--new"


def test_windivert_options_warning_and_filtering(tmp_path):
    """Проверяет регистрацию предупреждений для Windows WinDivert-специфичных параметров."""
    text = (
        "--wf-raw\n"
        "--wf-l3\n"
        "--wf-tcp-out=80,443\n"
        "--filter-tcp=443\n"
        "--lua-desync=fake\n"
    )
    unsupported = check_preset_unsupported_options(text)
    assert any("--wf-raw" in u or "--wf-l3" in u for u in unsupported)

    adapted = adapt_preset(text, app_dir=tmp_path, data_dir=tmp_path, writable_dir=tmp_path)
    # WinDivert параметры не должны передаваться в аргументы nfqws2
    for arg in adapted.arguments:
        assert not arg.startswith("--wf-")


def test_editor_save_as_user_preset(monkeypatch, tmp_path):
    """Проверяет создание пользовательского пресета через save_as_user_preset."""
    monkeypatch.setattr(core, "USER_PRESETS", tmp_path)
    text = "--new\n--name=Custom\n--filter-tcp=443\n--lua-desync=fake\n"
    saved_path = core.save_user_preset("my_cool_preset", text)
    assert saved_path.is_file()
    assert saved_path.name == "my_cool_preset.txt"
    assert saved_path.read_text(encoding="utf-8") == text


def test_ui_editor_dirty_state_tracking(monkeypatch, tmp_path):
    """Проверяет отслеживание dirty-state флага в UI редакторе."""
    from zapret2_ui import Zapret2Page
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    class DummyApp:
        zapret2_preset = "Default (circular).txt"
        active_iface = "eth0"
        engine_mode = "nfqws2"
        def create_page_container(self, title, subtitle):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            return box, box
        def save_config(self):
            pass

    monkeypatch.setattr(core, "USER_PRESETS", tmp_path)
    app = DummyApp()
    page = Zapret2Page(app)
    page.create()

    assert hasattr(page, "_is_dirty")
    assert page._is_dirty is False

    # Симулируем ручной ввод в текстовый буфер
    page.buffer.set_text(page.buffer.get_text(page.buffer.get_start_iter(), page.buffer.get_end_iter(), False) + "\n# user edit")
    assert page._is_dirty is True

    # Сохраняем профиль
    page.save_profile(None)
    assert page._is_dirty is False
