import os
import json
import tempfile
import pytest

from config_manager import (
    CONFIG_VERSION,
    DEFAULT_CONFIG,
    migrate_config,
    load_config_from_file,
    save_config_to_file
)


def test_default_config_validity():
    assert DEFAULT_CONFIG["version"] == CONFIG_VERSION
    assert DEFAULT_CONFIG["minimize_to_tray"] is True
    assert 1 <= DEFAULT_CONFIG["conntrack_limit"] <= 64
    assert DEFAULT_CONFIG["engine_mode"] in ("nfqws2", "nfqws", "tpws")


def test_load_nonexistent_file():
    cfg = load_config_from_file("/path/to/definitely/nonexistent/config.json")
    assert cfg["version"] == CONFIG_VERSION
    assert cfg["minimize_to_tray"] is True
    assert cfg["conntrack_limit"] == 12


def test_load_corrupted_json(tmp_path):
    broken_file = tmp_path / "broken.json"
    broken_file.write_text("{corrupted json contents", encoding="utf-8")

    cfg = load_config_from_file(str(broken_file))
    assert cfg["version"] == CONFIG_VERSION
    assert cfg["conntrack_limit"] == 12


def test_migration_from_v1_legacy(tmp_path):
    legacy_data = {
        "preset": "general",
        "dns": "cloudflare",
        "ai_hosts": False,
        "conntrack_limit": 1048576,  # Old healer bug value
        "engine_mode": "nfqws2"
        # No version field, no minimize_to_tray
    }
    migrated = migrate_config(legacy_data)
    assert migrated["version"] == 2
    assert migrated["enable_ai_hosts"] is False
    assert migrated["ai_hosts"] is False
    assert migrated["conntrack_limit"] == 12  # Clamped / reset from 1048576
    assert migrated["minimize_to_tray"] is True


def test_invalid_types_sanitization():
    dirty_data = {
        "version": 1,
        "conntrack_limit": "not_a_number",
        "minimize_to_tray": None,
        "engine_mode": "hacked_engine",
        "enable_quic": "yes",
    }
    migrated = migrate_config(dirty_data)
    assert migrated["conntrack_limit"] == 12
    assert migrated["minimize_to_tray"] is True
    assert migrated["engine_mode"] == "nfqws2"
    assert migrated["enable_quic"] is True


def test_atomic_save_and_load(tmp_path):
    cfg_path = tmp_path / "sub" / "config.json"
    data = dict(DEFAULT_CONFIG)
    data["conntrack_limit"] = 16
    data["minimize_to_tray"] = False

    saved = save_config_to_file(str(cfg_path), data)
    assert saved is True
    assert cfg_path.exists()

    loaded = load_config_from_file(str(cfg_path))
    assert loaded["conntrack_limit"] == 16
    assert loaded["minimize_to_tray"] is False
    assert loaded["version"] == CONFIG_VERSION
