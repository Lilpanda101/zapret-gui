"""Тесты проверки Ed25519-подписи update-manifest.json.

Тестовая ключевая пара - только для тестов, боевые ключи лежат в
signed_manifest.TRUSTED_KEYS и здесь не используются.
"""

from __future__ import annotations

import base64
import hashlib
import json

import pytest

from ed25519 import public_key_from_seed, sign_ed25519, verify_ed25519_signature
from signed_manifest import ManifestSignatureError, dumps_manifest, load_signed_manifest

import updater

SEED = hashlib.sha256(b"test key").digest()
OTHER_SEED = hashlib.sha256(b"someone else").digest()
KEYS = {"test-a": public_key_from_seed(SEED)}


def _manifest_bytes(version="99.1.2.3", *, channel="dev", key="test-a"):
    return dumps_manifest(
        {
            "schema": 1,
            "product": "zapret-gui",
            "channel": channel,
            "version": version,
            "created": 1792000000,
            "key": key,
            "files": [{"path": "bin/x.bin", "size": 3, "sha256": "b" * 64}],
            "installer": {"name": "Zapret2Setup.exe", "size": 12345, "sha256": "a" * 64},
        }
    )


def _sig(raw, seed=SEED):
    return base64.b64encode(sign_ed25519(seed, raw))


class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _opener(raw, sig, *, fail_sig=False):
    def fake_open(self, url, timeout=None):
        if "releases?limit=1" in url:
            body = json.dumps([{"tag_name": "99.1.2.3", "name": "t", "published_at": "", "body": ""}]).encode()
            return _Resp(body)
        if url.endswith("update-manifest.json"):
            return _Resp(raw)
        if url.endswith("update-manifest.json.sig"):
            if fail_sig:
                raise RuntimeError("404")
            return _Resp(sig)
        raise RuntimeError("404")

    return fake_open


def test_valid_signature_passes():
    raw = _manifest_bytes()
    payload = load_signed_manifest(raw, _sig(raw), trusted=KEYS)
    assert payload["version"] == "99.1.2.3"
    assert payload["key"] == "test-a"


def test_tampered_manifest_fails():
    raw = _manifest_bytes()
    sig = _sig(raw)
    tampered = raw.replace(b"99.1.2.3", b"99.1.2.4", 1)
    with pytest.raises(ManifestSignatureError):
        load_signed_manifest(tampered, sig, trusted=KEYS)


def test_signature_from_other_key_fails():
    raw = _manifest_bytes()
    with pytest.raises(ManifestSignatureError):
        load_signed_manifest(raw, _sig(raw, OTHER_SEED), trusted=KEYS)


def test_missing_signature_fails():
    raw = _manifest_bytes()
    with pytest.raises(ManifestSignatureError):
        load_signed_manifest(raw, b"", trusted=KEYS)


def test_rfc8032_vector():
    seed = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    pub = public_key_from_seed(seed)
    assert pub.hex() == "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
    sig = sign_ed25519(seed, b"")
    assert verify_ed25519_signature(pub, sig, b"")
    assert not verify_ed25519_signature(pub, sig, b"tampered")


def test_fetch_verified_manifest_applies(monkeypatch, tmp_path):
    raw = _manifest_bytes()
    sig = _sig(raw)
    monkeypatch.setattr(updater, "TRUSTED_KEYS", KEYS)
    monkeypatch.setattr(updater, "LOCAL_MANIFEST_CACHE", str(tmp_path / "update-manifest.json"))
    monkeypatch.setattr(updater, "LOCAL_MANIFEST_SIGNATURE_CACHE", str(tmp_path / "update-manifest.json.sig"))
    instance = updater.ZapretUpdater(str(tmp_path))
    monkeypatch.setattr(updater.ZapretUpdater, "_open_url", _opener(raw, sig))
    info = instance.fetch_latest_release_info()
    assert info["manifest"]["version"] == "99.1.2.3"
    assert (tmp_path / "update-manifest.json").read_bytes() == raw
    assert (tmp_path / "update-manifest.json.sig").read_bytes() == sig


def test_fetch_bad_signature_refuses_and_ignores_cache(monkeypatch, tmp_path):
    raw = _manifest_bytes()
    cache = tmp_path / "update-manifest.json"
    cache.write_bytes(_manifest_bytes(version="21.1.7.1"))
    monkeypatch.setattr(updater, "TRUSTED_KEYS", KEYS)
    monkeypatch.setattr(updater, "LOCAL_MANIFEST_CACHE", str(cache))
    monkeypatch.setattr(updater, "LOCAL_MANIFEST_SIGNATURE_CACHE", str(tmp_path / "update-manifest.json.sig"))
    instance = updater.ZapretUpdater(str(tmp_path))
    monkeypatch.setattr(updater.ZapretUpdater, "_open_url", _opener(raw, _sig(raw, OTHER_SEED)))
    with pytest.raises(RuntimeError, match="Подпись"):
        instance.fetch_latest_release_info()


def test_fetch_no_signature_refuses(monkeypatch, tmp_path):
    raw = _manifest_bytes()
    cache = tmp_path / "update-manifest.json"
    cache.write_bytes(_manifest_bytes(version="21.1.7.1"))
    monkeypatch.setattr(updater, "TRUSTED_KEYS", KEYS)
    monkeypatch.setattr(updater, "LOCAL_MANIFEST_CACHE", str(cache))
    monkeypatch.setattr(updater, "LOCAL_MANIFEST_SIGNATURE_CACHE", str(tmp_path / "update-manifest.json.sig"))
    instance = updater.ZapretUpdater(str(tmp_path))
    monkeypatch.setattr(updater.ZapretUpdater, "_open_url", _opener(raw, b"", fail_sig=True))
    with pytest.raises(RuntimeError):
        instance.fetch_latest_release_info()


def test_fetch_network_failure_does_not_use_cache(monkeypatch, tmp_path):
    cache = tmp_path / "update-manifest.json"
    cache.write_bytes(_manifest_bytes(version="21.1.7.1"))
    monkeypatch.setattr(updater, "LOCAL_MANIFEST_CACHE", str(cache))
    instance = updater.ZapretUpdater(str(tmp_path))

    def _down(self, url, timeout=None):
        raise RuntimeError("down")

    monkeypatch.setattr(updater.ZapretUpdater, "_open_url", _down)
    with pytest.raises(RuntimeError):
        instance.fetch_latest_release_info()
