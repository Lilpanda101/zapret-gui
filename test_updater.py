import hashlib
import json
import os

import pytest

import updater


def entry(path, data):
    return {"path": path, "size": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def test_sync_includes_lua_presets_and_filters(monkeypatch, tmp_path):
    payloads = {
        "bin/test.bin": b"fake",
        "lists/base/list-general.txt": b"youtube.com\n",
        "lua/test.lua": b"return true\n",
        "presets/winws2_builtin/test.txt": b"--new=test\n",
        "windivert.filter/test.txt": b"udp\n",
    }
    files = [entry(path, data) for path, data in payloads.items()]
    instance = updater.ZapretUpdater(str(tmp_path))
    monkeypatch.setattr(instance, "fetch_latest_release_info", lambda: {
        "tag_name": "test", "mirror": "local", "manifest": {"files": files},
    })
    monkeypatch.setattr(instance, "download_blob", lambda sha, size: next(
        data for data in payloads.values() if hashlib.sha256(data).hexdigest() == sha
    ))
    meta_file = tmp_path / "meta.json"
    monkeypatch.setattr(updater, "UPDATE_META_FILE", str(meta_file))

    meta = instance.sync_bases_and_fakes()
    assert meta["presets_count"] == 1
    assert meta["lua_count"] == 1
    assert (tmp_path / "fake" / "test.bin").read_bytes() == b"fake"
    assert (tmp_path / "zapret2" / "lua" / "test.lua").is_file()
    assert (tmp_path / "zapret2" / "presets" / "winws2_builtin" / "test.txt").is_file()
    assert (tmp_path / "zapret2" / "windivert.filter" / "test.txt").is_file()
    assert json.loads(meta_file.read_text())["version"] == "test"


def test_sync_does_not_report_partial_update_as_success(monkeypatch, tmp_path):
    good = b"good"
    files = [entry("lua/good.lua", good), entry("lua/bad.lua", b"bad")]
    instance = updater.ZapretUpdater(str(tmp_path))
    monkeypatch.setattr(instance, "fetch_latest_release_info", lambda: {
        "tag_name": "test", "mirror": "local", "manifest": {"files": files},
    })

    def download(sha, size):
        if sha == files[0]["sha256"]:
            return good
        raise RuntimeError("mirror failed")

    monkeypatch.setattr(instance, "download_blob", download)
    monkeypatch.setattr(updater, "UPDATE_META_FILE", str(tmp_path / "meta.json"))
    with pytest.raises(RuntimeError, match="Обновление не завершено"):
        instance.sync_bases_and_fakes()
    assert not (tmp_path / "meta.json").exists()


def test_build_update_plan_properties(tmp_path):
    instance = updater.ZapretUpdater(str(tmp_path))
    plan = instance.build_update_plan("22.0.0.1", from_version="22.0.0.0")

    assert plan["version"] == "22.0.0.1"
    assert plan["from_version"] == "22.0.0.0"

    # Process keep-running assertions: Windows binaries must not exist, Linux daemons present
    assert "winws" not in plan["keep_running"]
    assert "winws2" not in plan["keep_running"]
    assert "engine.sh" in plan["keep_running"]
    assert "nfqws" in plan["keep_running"]
    assert "nfqws2" in plan["keep_running"]
    assert "zapret2_core" in plan["keep_running"]

    # Preserve paths assertions: Windows folders absent, Linux config and hosts present
    assert "user" not in plan["preserve"]
    assert "settings" not in plan["preserve"]
    assert "logs" not in plan["preserve"]
    assert any(".config/zapret-gui" in p for p in plan["preserve"])
    assert os.path.expanduser("~/.config/zapret-gui/config.json") in plan["preserve"]
    assert "custom_hosts.txt" in plan["preserve"]
    assert "hosts.txt" in plan["preserve"]
    assert "badsum_hosts.txt" in plan["preserve"]
    assert "exclude.txt" in plan["preserve"]

    assert plan["rescue_dir"] == updater.RESCUE_DIR


def test_bsdiff_delta_apply_and_fallback(monkeypatch, tmp_path):
    import bz2
    from signed_manifest import _offtout

    instance = updater.ZapretUpdater(str(tmp_path))

    old_data = b"Old original engine data version 1"
    new_data = b"New patched engine data version 2 with extra bytes"

    target_file = tmp_path / "engine_data.bin"
    target_file.write_bytes(old_data)

    old_sha = hashlib.sha256(old_data).hexdigest()
    new_sha = hashlib.sha256(new_data).hexdigest()

    # Craft synthetic BSDIFF40 patch
    diff_bytes = bytes((b2 - b1) & 0xFF for b1, b2 in zip(old_data, new_data[:len(old_data)]))
    extra_bytes = new_data[len(old_data):]
    ctrl = _offtout(len(old_data)) + _offtout(len(extra_bytes)) + _offtout(0)
    ctrl_bz = bz2.compress(ctrl)
    diff_bz = bz2.compress(diff_bytes)
    extra_bz = bz2.compress(extra_bytes)
    patch = b"BSDIFF40" + _offtout(len(ctrl_bz)) + _offtout(len(diff_bz)) + _offtout(len(new_data)) + ctrl_bz + diff_bz + extra_bz

    bsdiff_map = {(old_sha, new_sha): {"size": len(patch)}}
    monkeypatch.setattr(instance, "download_bsdiff_patch", lambda f, t: patch)

    file_info = {"sha256": new_sha, "size": len(new_data)}
    updated, mode = instance.apply_file_update(str(target_file), file_info, bsdiff_map=bsdiff_map)

    assert updated is True
    assert mode == "bsdiff"
    assert target_file.read_bytes() == new_data

    # Test fallback on broken patch
    target_file.write_bytes(old_data)
    monkeypatch.setattr(instance, "download_bsdiff_patch", lambda f, t: b"BROKEN_PATCH")
    monkeypatch.setattr(instance, "download_blob", lambda sha, size: new_data)

    updated_fb, mode_fb = instance.apply_file_update(str(target_file), file_info, bsdiff_map=bsdiff_map)
    assert updated_fb is True
    assert mode_fb == "full_blob"
    assert target_file.read_bytes() == new_data


def test_update_failure_with_rescue_rollback(tmp_path):
    instance = updater.ZapretUpdater(str(tmp_path))
    rescue_dir = tmp_path / "rescue"
    rescue_dir.mkdir(parents=True)

    test_file = tmp_path / "important_config.json"
    original_content = b'{"settings": "critical user state"}'
    test_file.write_bytes(original_content)

    rel_name = "important_config.json"
    journal = {
        "target_version": "22.0.0.1",
        "files": [rel_name]
    }
    journal_path = rescue_dir / "journal.json"
    journal_path.write_text(json.dumps(journal))

    # Backup into rescue
    backup_file = rescue_dir / rel_name
    backup_file.write_bytes(original_content)

    # Corrupt target file during aborted update
    test_file.write_bytes(b'CORRUPTED_INCOMPLETE_WRITE')

    # Trigger rollback
    success = instance.rollback_from_rescue(str(journal_path), rescue_dir=str(rescue_dir))
    assert success is True
    assert test_file.read_bytes() == original_content

