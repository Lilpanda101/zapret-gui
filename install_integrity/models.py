"""
install_integrity/models.py - Модель целостности установки по образцу оригинала.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

MANIFEST_SCHEMA_VERSION = 1
MANIFEST_FILE_NAME = "install_manifest.json"

ROLE_CRITICAL = "critical"
ROLE_REQUIRED = "required"
ALL_ROLES = (ROLE_CRITICAL, ROLE_REQUIRED)

KIND_MISSING = "missing"
KIND_CORRUPTED = "corrupted"


class IntegrityCause(str, Enum):
    """Единственная причина, объясняющая состояние установки."""

    OK = "ok"
    # Манифеста нет: запуск из исходников или сборка без манифеста.
    MANIFEST_ABSENT = "manifest_absent"
    # Каталоги поставки на месте, отдельные файлы исчезли: файл удалили уже после установки.
    REMOVED_AFTER_INSTALL = "removed_after_install"
    # Каталогов поставки нет: установка не завершилась или была повреждена.
    INCOMPLETE_INSTALL = "incomplete_install"
    # Файлы на месте, но их содержимое (размер или хэш) не совпадает с манифестом.
    CORRUPTED = "corrupted"


@dataclass(frozen=True)
class ManifestEntry:
    path: str
    size: int
    sha256: str
    role: str = ROLE_REQUIRED
    engines: Tuple[str, ...] = ()

    @property
    def is_critical(self) -> bool:
        return self.role == ROLE_CRITICAL

    def required_for(self, engine: Optional[str]) -> bool:
        if not self.engines or not engine:
            return True
        return str(engine) in self.engines

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "path": self.path,
            "size": int(self.size),
            "sha256": self.sha256,
            "role": self.role,
        }
        if self.engines:
            payload["engines"] = list(self.engines)
        return payload


@dataclass(frozen=True)
class InstallManifest:
    schema: int
    version: str
    channel: str
    entries: Tuple[ManifestEntry, ...]

    def critical_entries(self) -> Tuple[ManifestEntry, ...]:
        return tuple(entry for entry in self.entries if entry.is_critical)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema": int(self.schema),
            "version": self.version,
            "channel": self.channel,
            "files": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True)
class IntegrityFinding:
    path: str
    kind: str
    role: str
    engines: Tuple[str, ...] = ()

    @property
    def is_critical(self) -> bool:
        return self.role == ROLE_CRITICAL

    def blocks(self, engine: Optional[str]) -> bool:
        if not self.is_critical:
            return False
        if not self.engines or not engine:
            return True
        return str(engine) in self.engines


@dataclass(frozen=True)
class IntegrityReport:
    cause: IntegrityCause
    findings: Tuple[IntegrityFinding, ...] = ()
    manifest_version: str = ""
    checked_files: int = 0
    deep: bool = False

    @property
    def ok(self) -> bool:
        return not self.findings

    @property
    def checked(self) -> bool:
        return self.cause is not IntegrityCause.MANIFEST_ABSENT

    @property
    def missing(self) -> Tuple[str, ...]:
        return tuple(f.path for f in self.findings if f.kind == KIND_MISSING)

    @property
    def corrupted(self) -> Tuple[str, ...]:
        return tuple(f.path for f in self.findings if f.kind == KIND_CORRUPTED)

    def blocking_findings(self, engine: Optional[str] = None) -> Tuple[IntegrityFinding, ...]:
        return tuple(finding for finding in self.findings if finding.blocks(engine))

    def blocks_launch(self, engine: Optional[str] = None) -> bool:
        return bool(self.blocking_findings(engine))
