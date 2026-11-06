import os
from pathlib import Path
import pytest

PRESETS_DIR = Path("zapret2/presets/winws2_builtin")
SNAPSHOT_FILE = Path("tests/snapshots/preset_ids.txt")


def test_preset_catalog_ids_immutable():
    """
    Bidirectional golden snapshot test for preset IDs.
    Guarantees:
    1. Exactly 136 preset IDs exist.
    2. No existing preset ID is deleted or renamed (missing set must be empty).
    3. No new or accidental files are added without an intentional golden snapshot update (extra set must be empty).
    4. Every ID is a valid .txt filename.
    """
    assert SNAPSHOT_FILE.is_file(), f"Golden snapshot file {SNAPSHOT_FILE} missing!"

    raw_expected = SNAPSHOT_FILE.read_text(encoding="utf-8").strip().splitlines()
    expected_ids = set(line.strip() for line in raw_expected if line.strip())

    assert len(expected_ids) == 136, f"Expected exactly 136 preset IDs in golden snapshot, found {len(expected_ids)}"

    assert PRESETS_DIR.is_dir(), f"Presets directory {PRESETS_DIR} missing!"

    actual_files = [f.name for f in PRESETS_DIR.iterdir() if f.is_file() and not f.name.startswith(".")]
    actual_ids = set(actual_files)

    missing = expected_ids - actual_ids
    extra = actual_ids - expected_ids

    error_msgs = []
    if missing:
        error_msgs.append(f"Missing {len(missing)} preset(s) that were deleted or renamed:\n  " + "\n  ".join(sorted(missing)))
    if extra:
        error_msgs.append(f"Found {len(extra)} unexpected new preset(s) not in golden snapshot:\n  " + "\n  ".join(sorted(extra)))

    assert not error_msgs, "\n\n".join(error_msgs)
    assert len(actual_ids) == 136, f"Expected 136 presets, got {len(actual_ids)}"

    for pid in actual_ids:
        assert pid.endswith(".txt"), f"Preset ID must end with .txt: {pid}"
        assert "/" not in pid and "\\" not in pid, f"Preset ID must be a basename: {pid}"
