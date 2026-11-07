"""
install_integrity/__init__.py
"""

from install_integrity.models import (
    ALL_ROLES,
    InstallManifest,
    IntegrityCause,
    IntegrityFinding,
    IntegrityReport,
    KIND_CORRUPTED,
    KIND_MISSING,
    MANIFEST_FILE_NAME,
    MANIFEST_SCHEMA_VERSION,
    ManifestEntry,
    ROLE_CRITICAL,
    ROLE_REQUIRED,
)
from install_integrity.manifest import (
    MANIFEST_SCOPES,
    build_manifest,
    load_manifest,
    manifest_path,
    normalize_relative_path,
    parse_manifest,
    sha256_file,
    write_manifest,
)
from install_integrity.verify import (
    verify_fast,
    verify_full,
    verify_installation,
)

__all__ = [
    "ALL_ROLES",
    "InstallManifest",
    "IntegrityCause",
    "IntegrityFinding",
    "IntegrityReport",
    "KIND_CORRUPTED",
    "KIND_MISSING",
    "MANIFEST_FILE_NAME",
    "MANIFEST_SCHEMA_VERSION",
    "MANIFEST_SCOPES",
    "ManifestEntry",
    "ROLE_CRITICAL",
    "ROLE_REQUIRED",
    "build_manifest",
    "load_manifest",
    "manifest_path",
    "normalize_relative_path",
    "parse_manifest",
    "sha256_file",
    "verify_fast",
    "verify_full",
    "verify_installation",
    "write_manifest",
]
