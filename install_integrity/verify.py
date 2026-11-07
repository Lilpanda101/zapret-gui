"""
install_integrity/verify.py - Быстрая и полная проверка целостности установки.
Быстрая (fast): наличие и размер перед запуском.
Полная (full): SHA-256 только в фоне после обновления.
Заблокированный файл (OSError при чтении) пережидает через retry 0.2, 0.5, 1.0 с
и НЕ считается повреждением (CORRUPTED).
"""

from __future__ import annotations

import os
from pathlib import Path
import time
from typing import List, Optional, Tuple

from install_integrity.manifest import MANIFEST_SCOPES, load_manifest, sha256_file
from install_integrity.models import (
    InstallManifest,
    IntegrityCause,
    IntegrityFinding,
    IntegrityReport,
    KIND_CORRUPTED,
    KIND_MISSING,
)

_LOCKED_FILE_RETRY_DELAYS_S: Tuple[float, ...] = (0.2, 0.5, 1.0)


def _install_root(root: str | os.PathLike[str] | None) -> Path:
    if root is not None:
        return Path(root)
    return Path(__file__).resolve().parent.parent


def _scope_of(relative_path: str) -> str:
    head = relative_path.split("/", 1)[0]
    return head if head in MANIFEST_SCOPES else ""


def _classify(
    install_root: Path,
    findings: Tuple[IntegrityFinding, ...],
    *,
    total_entries: int,
) -> IntegrityCause:
    if not findings:
        return IntegrityCause.OK

    missing = tuple(f for f in findings if f.kind == KIND_MISSING)
    if not missing:
        return IntegrityCause.CORRUPTED

    # Пропала вся поставка целиком
    if total_entries and len(missing) >= total_entries:
        return IntegrityCause.INCOMPLETE_INSTALL

    # Каталога поставки нет вообще
    for finding in missing:
        scope = _scope_of(finding.path)
        if scope and not (install_root / scope).is_dir():
            return IntegrityCause.INCOMPLETE_INSTALL

    # Каталоги на месте, отдельные файлы исчезли
    return IntegrityCause.REMOVED_AFTER_INSTALL


def _sha256_with_retry(target: Path, retry_delays: Tuple[float, ...] = _LOCKED_FILE_RETRY_DELAYS_S) -> str:
    """Хэш файла; короткую блокировку чтения (антивирус/другой процесс) пережидает."""
    for delay in retry_delays:
        try:
            return sha256_file(target)
        except FileNotFoundError:
            raise
        except OSError:
            time.sleep(delay)
    return sha256_file(target)


def verify_installation(
    *,
    root: str | os.PathLike[str] | None = None,
    manifest_dir: str | os.PathLike[str] | None = None,
    manifest: Optional[InstallManifest] = None,
    deep: bool = False,
    retry_delays: Tuple[float, ...] = _LOCKED_FILE_RETRY_DELAYS_S,
) -> IntegrityReport:
    install_root = _install_root(root)
    if manifest is None:
        manifest = load_manifest(manifest_dir or install_root)
    if manifest is None:
        return IntegrityReport(cause=IntegrityCause.MANIFEST_ABSENT, deep=bool(deep))

    findings: List[IntegrityFinding] = []
    for entry in manifest.entries:
        target = install_root / entry.path
        try:
            stat_result = target.stat()
        except OSError:
            findings.append(
                IntegrityFinding(
                    path=entry.path,
                    kind=KIND_MISSING,
                    role=entry.role,
                    engines=entry.engines,
                )
            )
            continue

        if entry.size and stat_result.st_size != entry.size:
            findings.append(
                IntegrityFinding(
                    path=entry.path,
                    kind=KIND_CORRUPTED,
                    role=entry.role,
                    engines=entry.engines,
                )
            )
            continue

        if not deep or not entry.sha256:
            continue

        try:
            actual = _sha256_with_retry(target, retry_delays=retry_delays)
        except FileNotFoundError:
            findings.append(
                IntegrityFinding(
                    path=entry.path,
                    kind=KIND_MISSING,
                    role=entry.role,
                    engines=entry.engines,
                )
            )
            continue
        except OSError:
            # Заблокированный файл при наличии и верном размере НЕ считаем повреждением
            continue

        if actual != entry.sha256:
            findings.append(
                IntegrityFinding(
                    path=entry.path,
                    kind=KIND_CORRUPTED,
                    role=entry.role,
                    engines=entry.engines,
                )
            )

    frozen = tuple(findings)
    return IntegrityReport(
        cause=_classify(install_root, frozen, total_entries=len(manifest.entries)),
        findings=frozen,
        manifest_version=manifest.version,
        checked_files=len(manifest.entries),
        deep=bool(deep),
    )


def verify_fast(**kwargs) -> IntegrityReport:
    return verify_installation(deep=False, **kwargs)


def verify_full(**kwargs) -> IntegrityReport:
    return verify_installation(deep=True, **kwargs)
