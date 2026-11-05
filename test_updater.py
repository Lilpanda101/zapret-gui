import hashlib
import json

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
