"""
install_integrity/manifest.py - Чтение и создание манифеста установки.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from install_integrity.models import (
    InstallManifest,
    MANIFEST_FILE_NAME,
    MANIFEST_SCHEMA_VERSION,
    ManifestEntry,
    ROLE_CRITICAL,
    ROLE_REQUIRED,
)

MANIFEST_SCOPES = ("bin", "lua", "zapret2", "presets", "lists")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def normalize_relative_path(value: str | os.PathLike[str]) -> str:
    return str(value).replace("\\", "/").strip("/")


def manifest_path(manifest_dir: str | os.PathLike[str] | None = None) -> Path:
    if manifest_dir is None:
        return Path(__file__).resolve().parent.parent / MANIFEST_FILE_NAME
    return Path(manifest_dir) / MANIFEST_FILE_NAME


def parse_manifest(payload: Any) -> Optional[InstallManifest]:
    if not isinstance(payload, dict):
        return None
    try:
        schema = int(payload.get("schema") or 0)
    except (TypeError, ValueError):
        return None
    if schema != MANIFEST_SCHEMA_VERSION:
        return None

    entries: List[ManifestEntry] = []
    for item in payload.get("files") or ():
        if not isinstance(item, dict):
            continue
        path = normalize_relative_path(str(item.get("path") or ""))
        if not path:
            continue
        try:
            size = int(item.get("size") or 0)
        except (TypeError, ValueError):
            continue
        role = str(item.get("role") or ROLE_REQUIRED).strip().lower()
        if role not in (ROLE_CRITICAL, ROLE_REQUIRED):
            role = ROLE_REQUIRED
        engines = tuple(
            str(engine).strip().lower()
            for engine in (item.get("engines") or ())
            if str(engine).strip()
        )
        entries.append(
            ManifestEntry(
                path=path,
                size=max(size, 0),
                sha256=str(item.get("sha256") or "").strip().lower(),
                role=role,
                engines=engines,
            )
        )

    if not entries:
        return None

    return InstallManifest(
        schema=schema,
        version=str(payload.get("version") or "").strip(),
        channel=str(payload.get("channel") or "").strip().lower(),
        entries=tuple(entries),
    )


def load_manifest(manifest_dir: str | os.PathLike[str] | None = None) -> Optional[InstallManifest]:
    path = manifest_path(manifest_dir)
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    try:
        payload = json.loads(raw)
    except (ValueError, TypeError):
        return None
    return parse_manifest(payload)


def build_manifest(
    stage_root: str | os.PathLike[str],
    *,
    version: str,
    channel: str = "release",
    scopes: Tuple[str, ...] = MANIFEST_SCOPES,
) -> InstallManifest:
    root = Path(stage_root)
    entries: List[ManifestEntry] = []
    for scope in scopes:
        scope_root = root / scope
        if not scope_root.is_dir():
            continue
        for path in sorted(scope_root.rglob("*")):
            if not path.is_file():
                continue
            relative = normalize_relative_path(path.relative_to(root))
            role = ROLE_CRITICAL if ("nfqws" in relative or "engine.sh" in relative) else ROLE_REQUIRED
            entries.append(
                ManifestEntry(
                    path=relative,
                    size=path.stat().st_size,
                    sha256=sha256_file(path),
                    role=role,
                    engines=("nfqws", "nfqws2"),
                )
            )
    return InstallManifest(
        schema=MANIFEST_SCHEMA_VERSION,
        version=str(version or "").strip(),
        channel=str(channel or "").strip().lower(),
        entries=tuple(entries),
    )


def write_manifest(manifest: InstallManifest, destination: str | os.PathLike[str]) -> Path:
    path = Path(destination)
    if path.is_dir():
        path = path / MANIFEST_FILE_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path
