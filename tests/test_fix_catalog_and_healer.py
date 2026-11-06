from pathlib import Path
import json
import pytest

from catalog.preset_catalog import PresetCatalog, parse_preset_id
import healer
import zapret2_core as core

PRESETS_DIR = Path("zapret2/presets/winws2_builtin")
SNAPSHOT_FILE = Path("tests/snapshots/preset_ids.txt")


def test_compact_view_prefers_plain_and_has_exact_15_game_presets():
    """В компактном виде (only_latest_per_family) выбираются plain-версии.

    Игровой фильтр (game_filter=True) допускается только для тех 15 семейств, где нет неигровых версий.
    """
    catalog = PresetCatalog.load_from_directory(PRESETS_DIR)
    compact_entries = catalog.filter(only_latest_per_family=True)

    assert len(compact_entries) == 63

    # Определяем 15 семейств, у которых в принципе нет версий без game_filter
    game_only_families = set()
    for fam, items in catalog.families.items():
        if not any(not e.game_filter for e in items):
            game_only_families.add(fam)

    assert len(game_only_families) == 15

    # Проверяем каждое выбранное в компактном виде семейство
    game_entries = [e for e in compact_entries if e.game_filter]
    assert len(game_entries) == 15
    for e in game_entries:
        assert e.family in game_only_families, f"Family '{e.family}' has plain variants but compact view selected game filter: {e.id}"

    # Проверяем ключевые семейства: general ALT и general FAKE TLS AUTO
    alt_entry = next(e for e in compact_entries if e.family == "general ALT")
    assert alt_entry.id == "general ALT.txt"
    assert alt_entry.game_filter is False

    fake_tls_entry = next(e for e in compact_entries if e.family == "general FAKE TLS AUTO")
    assert fake_tls_entry.game_filter is False


def test_healer_persists_canonical_id_in_golden_snapshot(tmp_path, monkeypatch):
    """healer.switch_to_next_preset обязан сохранять в config канонический ID из golden snapshot."""
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(healer, "CONFIG_FILE", str(config_file))

    golden_ids = set(SNAPSHOT_FILE.read_text(encoding="utf-8").strip().splitlines())

    config = {"engine_mode": "nfqws2", "zapret2_preset": "general ALT"}
    next_id = healer.switch_to_next_preset(config)

    # Должен сохраниться канонический ID с расширением .txt
    assert next_id.endswith(".txt")
    assert next_id in golden_ids, f"Saved preset '{next_id}' is not in golden snapshot"

    saved_config = json.loads(config_file.read_text(encoding="utf-8"))
    assert saved_config["zapret2_preset"] == next_id
    assert saved_config["zapret2_preset"] in golden_ids

    # Следующий шаг ротации
    next_next_id = healer.switch_to_next_preset(saved_config)
    assert next_next_id.endswith(".txt")
    assert next_next_id in golden_ids
