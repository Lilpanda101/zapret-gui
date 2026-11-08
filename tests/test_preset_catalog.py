import pytest
from pathlib import Path

from catalog.preset_catalog import PresetCatalog, parse_preset_id, PresetEntry

SNAPSHOT_FILE = Path("tests/snapshots/preset_ids.txt")
PRESETS_DIR = Path("zapret2/presets/winws2_builtin")


def test_parse_alt1_vs_alt10_different_families():
    # ALT1 and ALT10 must be different families, not prefixes!
    p_alt1 = parse_preset_id("general ALT1 1.10.3 (game filter).txt")
    p_alt10 = parse_preset_id("general ALT10 1.10.3 (game filter).txt")
    p_alt10_plain = parse_preset_id("general ALT10.txt")

    assert p_alt1.family == "general ALT1"
    assert p_alt1.version == "1.10.3"
    assert p_alt1.game_filter is True
    assert p_alt1.id == "general ALT1 1.10.3 (game filter).txt"

    assert p_alt10.family == "general ALT10"
    assert p_alt10.version == "1.10.3"
    assert p_alt10.game_filter is True

    assert p_alt10_plain.family == "general ALT10"
    assert p_alt10_plain.version is None
    assert p_alt10_plain.game_filter is False

    assert p_alt1.family != p_alt10.family


def test_parse_various_preset_names():
    # ALL TCP & UDP version variations
    p_v3_1 = parse_preset_id("ALL TCP & UDP v3_1.txt")
    assert p_v3_1.family == "ALL TCP & UDP"
    assert p_v3_1.version == "v3_1"

    # Default circular version 2
    p_circ_v2 = parse_preset_id("Default (circular) v2.txt")
    assert p_circ_v2.family == "Default (circular)"
    assert p_circ_v2.version == "v2"

    # Game filter with version
    p_dbd = parse_preset_id("Dead by Daylight v2 (game filter).txt")
    assert p_dbd.family == "Dead by Daylight"
    assert p_dbd.version == "v2"
    assert p_dbd.game_filter is True


def test_catalog_all_136_presets_loaded_without_loss():
    catalog = PresetCatalog.load_from_directory(PRESETS_DIR)

    assert catalog.total_count == 136
    # Check that sum of items across all families strictly equals 136
    flattened = [preset.id for family in catalog.families.values() for preset in family]
    assert len(flattened) == 136
    assert len(set(flattened)) == 136

    # Every item's ID must match the golden snapshot
    expected_ids = set(SNAPSHOT_FILE.read_text(encoding="utf-8").strip().splitlines())
    assert set(flattened) == expected_ids


def test_normalized_key_never_leaks_to_id():
    catalog = PresetCatalog.load_from_directory(PRESETS_DIR)
    for entry in catalog.all_presets():
        assert entry.id.endswith(".txt")
        # Ensure id is strictly the filesystem name
        assert (PRESETS_DIR / entry.id).is_file()


def test_catalog_winws1_presets_loaded_without_loss():
    winws1_dir = Path("zapret2/presets/winws1_builtin")
    snapshot_file = Path("tests/snapshots/winws1_preset_ids.txt")
    assert winws1_dir.is_dir()
    assert snapshot_file.is_file()

    catalog = PresetCatalog.load_from_directory(winws1_dir)
    assert catalog.total_count == 165

    expected_ids = set(snapshot_file.read_text(encoding="utf-8").strip().splitlines())
    actual_ids = {p.id for p in catalog.all_presets()}
    assert actual_ids == expected_ids


def test_winws1_priority_families_parsed():
    winws1_dir = Path("zapret2/presets/winws1_builtin")
    catalog = PresetCatalog.load_from_directory(winws1_dir)

    # Priority families presence
    families = set(catalog.families.keys())
    priority_sample = ["YTDisBystro_31", "YTDisBystro_34", "bolvan", "mgts1", "Rosmega", "warp1"]
    for fam in priority_sample:
        assert any(fam.lower() in f.lower() for f in families), f"Priority family {fam} missing from parsed catalog"

    # Verify YTDisBystro has presets
    yt_presets = [p for p in catalog.all_presets() if "ytdisbystro" in p.id.lower()]
    assert len(yt_presets) >= 10


def test_preset_metadata_enrichment():
    catalog = PresetCatalog.load_from_directory(PRESETS_DIR)
    
    # Check that metadata fields exist on entries
    alt2_entries = [p for p in catalog.all_presets() if "general alt2" in p.family.lower()]
    assert alt2_entries
    for entry in alt2_entries:
        assert hasattr(entry, "author")
        assert hasattr(entry, "stability")
        assert hasattr(entry, "description")
        assert hasattr(entry, "source")
        assert entry.author is not None
        assert entry.stability in ("recommended", "game", "stable", "stock", "experimental")

