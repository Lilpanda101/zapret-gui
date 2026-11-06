import ast
import re
from pathlib import Path
import pytest
from catalog.preset_catalog import PresetCatalog, parse_preset_id

PRESETS_DIR = Path("zapret2/presets/winws2_builtin")


def test_version_sorting_semver_numeric():
    """Проверяет, что 1.10.3 считается новее 1.9.9, а v3_1 новее v2."""
    catalog = PresetCatalog.load_from_directory(PRESETS_DIR)
    
    # Семейство general ALT9 имеет версии 1.9.4, 1.9.5, 1.9.9, 1.10.3
    alt9_presets = catalog.get_family("general ALT9")
    assert len(alt9_presets) > 0
    # Последним элементом должна быть именно версия 1.10.3
    latest_alt9 = alt9_presets[-1]
    assert latest_alt9.version == "1.10.3", f"Expected latest version 1.10.3, but got {latest_alt9.version}"

    # При фильтрации only_latest_per_family=True для general ALT9 должен вернуться 1.10.3
    filtered = catalog.filter(family="general ALT9", only_latest_per_family=True)
    assert len(filtered) == 1
    assert filtered[0].version == "1.10.3"


def test_only_latest_per_family_returns_exact_family_count():
    """При флаге only_latest_per_family=True количество пресетов равно числу семейств (63)."""
    catalog = PresetCatalog.load_from_directory(PRESETS_DIR)
    latest_presets = catalog.filter(only_latest_per_family=True)
    assert len(latest_presets) == catalog.family_count == 63
    # Каждое семейство представлено ровно один раз
    families = [p.family for p in latest_presets]
    assert len(set(families)) == 63


def test_sidebar_label_dynamic_counter():
    """Проверяет, что в main.py навигационный пункт пресетов формируется динамически или содержит актуальные счетчики семейств и версий."""
    main_py = Path("main.py").read_text(encoding="utf-8")
    assert "family_count" in main_py and "total_count" in main_py, "Sidebar should dynamically use family_count and total_count"
    assert "сем. ·" in main_py, "Sidebar label should format family and total count"


def test_zapret2_ui_has_all_versions_toggle():
    """Проверяет наличие переключателя версий в Zapret2Page и интеграцию с PresetCatalog."""
    from zapret2_ui import Zapret2Page
    import gi
    gi.require_version("Gtk", "3.0")
    from gi.repository import Gtk

    class FakeApp:
        zapret2_preset = "Default (circular).txt"
        active_iface = "eth0"
        engine_mode = "nfqws2"
        def create_page_container(self, title, subtitle):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
            return box, box
        def save_config(self):
            pass

    app = FakeApp()
    page = Zapret2Page(app)
    widget = page.create()

    # Должен быть атрибут chk_all_versions или аналогичный переключатель
    assert hasattr(page, "chk_all_versions"), "Zapret2Page must have chk_all_versions toggle"
    assert isinstance(page.chk_all_versions, Gtk.CheckButton)
    # По умолчанию переключатель выключен (показываем актуальные версии семейств)
    assert page.chk_all_versions.get_active() is False

    # В комбобоксе при дефолтном режиме должно быть число пресетов, равное семействам
    model = page.preset_combo.get_model()
    assert len(model) == 63, f"Default combo should contain 63 canonical family presets, got {len(model)}"

    # Включаем показ всех версий
    page.chk_all_versions.set_active(True)
    assert len(page.preset_combo.get_model()) == 136, "With all versions enabled, combo should have 136 items"

    # Проверяем, что активный id всегда оканчивается на .txt
    active_id = page.preset_combo.get_active_id()
    assert active_id is not None
    assert active_id.endswith(".txt")
