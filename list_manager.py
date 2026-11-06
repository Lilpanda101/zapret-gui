#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Advanced Domain Lists Manager with '!' Exclusion Syntax for Zapret GUI Linux.
Handles user lists, auto lists, and exclude lists.
Parses, normalizes, deduplicates, and compiles lists for nfqws / engine.sh.
"""

from __future__ import annotations

import enum
import logging
import os
import re
import shutil
import tempfile
import urllib.parse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple, Union

logger = logging.getLogger("zapret_gui.list_manager")

# Regex to match valid RFC 1123 domain names
DOMAIN_REGEX = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$"
)


class ListType(str, enum.Enum):
    USER = "user"          # Manually added user domains (custom_hosts.txt, list-general.txt)
    AUTO = "auto"          # Dynamically discovered domains (autohostlist.txt)
    EXCLUDE = "exclude"    # Domains explicitly excluded from processing (exclude.txt)


def normalize_domain(raw_domain: str) -> Optional[str]:
    """
    Normalizes a domain string:
    - Strips protocols (http://, https://, etc.)
    - Strips ports (:443, :8080)
    - Strips URL paths (/path/to/page)
    - Strips leading wildcards (*. or .)
    - Converts IDN (unicode) to ASCII Punycode
    - Converts to lowercase
    - Validates against RFC 1123 rules
    Returns normalized domain string or None if invalid.
    """
    if not raw_domain or not isinstance(raw_domain, str):
        return None

    cleaned = raw_domain.strip()
    if not cleaned or cleaned.startswith(("#", ";")):
        return None

    # Strip scheme if present
    if "://" in cleaned:
        try:
            parsed = urllib.parse.urlsplit(cleaned)
            cleaned = parsed.netloc or parsed.path
        except Exception:
            cleaned = cleaned.split("://", 1)[-1]

    # Strip URL path or query
    if "/" in cleaned:
        cleaned = cleaned.split("/", 1)[0]
    if "?" in cleaned:
        cleaned = cleaned.split("?", 1)[0]
    if "#" in cleaned:
        cleaned = cleaned.split("#", 1)[0]

    # Strip port (e.g., example.com:443, [::1]:80)
    if ":" in cleaned:
        # Check if it's IPv6 in brackets
        if cleaned.startswith("[") and "]" in cleaned:
            cleaned = cleaned.split("]")[0].lstrip("[")
        else:
            cleaned = cleaned.split(":", 1)[0]

    # Strip leading wildcards
    while cleaned.startswith("*.") or cleaned.startswith("."):
        cleaned = cleaned.lstrip("*.")

    # Strip trailing dot
    cleaned = cleaned.rstrip(".")

    if not cleaned:
        return None

    # Handle Internationalized Domain Names (IDN) via Punycode
    try:
        cleaned = cleaned.encode("idna").decode("ascii").lower()
    except Exception:
        cleaned = cleaned.lower()

    # Length check (RFC: max 253 characters)
    if len(cleaned) > 253 or len(cleaned) < 3:
        return None

    # Check against domain regex
    if not DOMAIN_REGEX.match(cleaned):
        return None

    # Validate label length (max 63 per label)
    labels = cleaned.split(".")
    if any(len(label) > 63 or not label for label in labels):
        return None

    return cleaned


def parse_rule_line(line: str) -> Optional[Tuple[str, bool]]:
    """
    Parses a single list rule line.
    Returns (normalized_domain, is_exclusion) or None if line is blank/comment/invalid.
    Rules starting with '!' are treated as unconditional exclusions (is_exclusion=True).
    """
    if not line or not isinstance(line, str):
        return None

    stripped = line.strip()
    if not stripped or stripped.startswith(("#", ";")):
        return None

    is_exclusion = False
    if stripped.startswith("!"):
        is_exclusion = True
        stripped = stripped[1:].strip()

    norm = normalize_domain(stripped)
    if not norm:
        return None

    return norm, is_exclusion


def parse_list_text(text: str) -> Tuple[Set[str], Set[str]]:
    """
    Parses multiline text content into (includes, excludes).
    Lines starting with '!' are added to excludes.
    Normal lines are added to includes.
    """
    includes: Set[str] = set()
    excludes: Set[str] = set()

    for line in text.splitlines():
        parsed = parse_rule_line(line)
        if not parsed:
            continue
        domain, is_exclusion = parsed
        if is_exclusion:
            excludes.add(domain)
        else:
            includes.add(domain)

    return includes, excludes


def is_subdomain_or_equal(candidate: str, parent: str) -> bool:
    """
    Returns True if candidate is equal to parent or is a subdomain of parent.
    e.g. 'sub.google.com' is subdomain of 'google.com'.
    """
    return candidate == parent or candidate.endswith("." + parent)


@dataclass
class CompilationResult:
    """Result of compiling domain lists for zapret/nfqws engine."""
    hostlist: List[str]               # Clean domains for --hostlist
    exclude_list: List[str]           # Clean domains for --hostlist-exclude
    total_included: int = 0
    total_excluded: int = 0
    overridden_by_exclusion: List[str] = field(default_factory=list)


def compile_effective_lists(
    user_includes: Iterable[str] = (),
    user_excludes: Iterable[str] = (),
    auto_includes: Iterable[str] = (),
    auto_excludes: Iterable[str] = (),
    explicit_excludes: Iterable[str] = (),
    prune_subdomains: bool = True,
) -> CompilationResult:
    """
    Compiles effective hostlist and exclude_list adhering to extended '!' precedence.
    - If a domain is marked with '!' in ANY list or present in explicit_excludes,
      it is UNCONDITIONALLY EXCLUDED from hostlist and placed into exclude_list.
    - Any included domain that matches or is a subdomain of an excluded domain
      is pruned from hostlist to prevent leaking through DPI engine.
    - Returns deduplicated and sorted lists.
    """
    # 1. Aggregate all unconditional exclusions
    all_excludes: Set[str] = set()
    for item in explicit_excludes:
        norm = normalize_domain(item)
        if norm:
            all_excludes.add(norm)
    for item in user_excludes:
        norm = normalize_domain(item)
        if norm:
            all_excludes.add(norm)
    for item in auto_excludes:
        norm = normalize_domain(item)
        if norm:
            all_excludes.add(norm)

    # 2. Aggregate all candidate inclusions
    raw_includes: Set[str] = set()
    for item in user_includes:
        norm = normalize_domain(item)
        if norm:
            raw_includes.add(norm)
    for item in auto_includes:
        norm = normalize_domain(item)
        if norm:
            raw_includes.add(norm)

    # 3. Apply unconditional exclusion precedence
    effective_hostlist: Set[str] = set()
    overridden: List[str] = []

    for dom in raw_includes:
        # Check direct match with exclusion
        if dom in all_excludes:
            overridden.append(dom)
            continue

        # Check if domain is subdomain of any excluded domain
        if prune_subdomains:
            excluded_parent = any(
                dom.endswith("." + exc) for exc in all_excludes
            )
            if excluded_parent:
                overridden.append(dom)
                continue

        effective_hostlist.add(dom)

    sorted_hostlist = sorted(effective_hostlist)
    sorted_exclude = sorted(all_excludes)

    return CompilationResult(
        hostlist=sorted_hostlist,
        exclude_list=sorted_exclude,
        total_included=len(sorted_hostlist),
        total_excluded=len(sorted_exclude),
        overridden_by_exclusion=sorted(overridden),
    )


def atomic_write_text(target_path: Union[str, Path], content: str, mode: int = 0o644) -> Path:
    """Safely and atomically writes content to target_path using tempfile and os.replace."""
    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp_path_str = tempfile.mkstemp(dir=str(target.parent), prefix=".zapret_list_tmp_")
    tmp_path = Path(tmp_path_str)
    try:
        with open(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp_path, mode)
        os.replace(tmp_path, target)
        return target
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


class ListManager:
    """
    High-level manager for domain lists with extended '!' syntax support.
    Manages user lists, auto lists, and exclude lists.
    """

    def __init__(
        self,
        base_dir: Optional[Union[str, Path]] = None,
        user_list_path: Optional[Union[str, Path]] = None,
        auto_list_path: Optional[Union[str, Path]] = None,
        exclude_list_path: Optional[Union[str, Path]] = None,
    ):
        self.base_dir = Path(base_dir).resolve() if base_dir else Path.cwd()

        self.user_list_path = Path(user_list_path) if user_list_path else self.base_dir / "custom_hosts.txt"
        self.auto_list_path = Path(auto_list_path) if auto_list_path else self.base_dir / "lists" / "autohostlist.txt"
        self.exclude_list_path = Path(exclude_list_path) if exclude_list_path else self.base_dir / "exclude.txt"

        # In-memory storage for loaded rules:
        # includes: set of normalized domains
        # excludes: set of normalized domains (marked with '!')
        self._user_rules: Tuple[Set[str], Set[str]] = (set(), set())
        self._auto_rules: Tuple[Set[str], Set[str]] = (set(), set())
        self._explicit_excludes: Set[str] = set()

        self.reload_all()

    def reload_all(self) -> None:
        """Reloads all lists from disk."""
        self._user_rules = self._load_file_rules(self.user_list_path)
        self._auto_rules = self._load_file_rules(self.auto_list_path)
        self._explicit_excludes = self._load_plain_excludes(self.exclude_list_path)

    @staticmethod
    def _load_file_rules(path: Path) -> Tuple[Set[str], Set[str]]:
        if not path or not path.is_file():
            return set(), set()
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
            return parse_list_text(text)
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
            return set(), set()

    @staticmethod
    def _load_plain_excludes(path: Path) -> Set[str]:
        if not path or not path.is_file():
            return set()
        excludes: Set[str] = set()
        try:
            for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
                # In plain exclude file, lines might have or not have '!'
                parsed = parse_rule_line(line)
                if parsed:
                    excludes.add(parsed[0])
        except Exception as exc:
            logger.warning("Failed to read %s: %s", path, exc)
        return excludes

    def add_domain(
        self,
        domain: str,
        list_type: Union[str, ListType] = ListType.USER,
        is_exclusion: bool = False,
    ) -> bool:
        """
        Adds a domain or an exclusion rule (!domain) to specified list.
        Returns True if added or updated.
        """
        norm = normalize_domain(domain)
        if not norm:
            return False

        ltype = ListType(list_type)
        if ltype == ListType.USER:
            includes, excludes = self._user_rules
            if is_exclusion:
                includes.discard(norm)
                excludes.add(norm)
            else:
                excludes.discard(norm)
                includes.add(norm)
            return True
        elif ltype == ListType.AUTO:
            includes, excludes = self._auto_rules
            if is_exclusion:
                includes.discard(norm)
                excludes.add(norm)
            else:
                excludes.discard(norm)
                includes.add(norm)
            return True
        elif ltype == ListType.EXCLUDE:
            self._explicit_excludes.add(norm)
            return True

        return False

    def remove_domain(
        self,
        domain: str,
        list_type: Union[str, ListType] = ListType.USER,
    ) -> bool:
        """Removes a domain from the specified list (both regular and exclusion)."""
        norm = normalize_domain(domain)
        if not norm:
            return False

        ltype = ListType(list_type)
        if ltype == ListType.USER:
            inc, exc = self._user_rules
            removed = (norm in inc) or (norm in exc)
            inc.discard(norm)
            exc.discard(norm)
            return removed
        elif ltype == ListType.AUTO:
            inc, exc = self._auto_rules
            removed = (norm in inc) or (norm in exc)
            inc.discard(norm)
            exc.discard(norm)
            return removed
        elif ltype == ListType.EXCLUDE:
            removed = norm in self._explicit_excludes
            self._explicit_excludes.discard(norm)
            return removed

        return False

    def toggle_exclusion(
        self,
        domain: str,
        list_type: Union[str, ListType] = ListType.USER,
    ) -> bool:
        """
        Toggles a domain between regular inclusion and '!' exclusion in the list.
        Returns the new exclusion state (True = now excluded, False = now included).
        """
        norm = normalize_domain(domain)
        if not norm:
            raise ValueError(f"Invalid domain: {domain}")

        ltype = ListType(list_type)
        if ltype == ListType.EXCLUDE:
            # Exclude list is always excluded
            return True

        inc, exc = self._user_rules if ltype == ListType.USER else self._auto_rules
        if norm in exc:
            exc.remove(norm)
            inc.add(norm)
            return False
        else:
            inc.discard(norm)
            exc.add(norm)
            return True

    def compile(self) -> CompilationResult:
        """
        Compiles all managed lists into effective hostlist and exclude_list.
        Applies unconditional exclusion rules.
        """
        user_inc, user_exc = self._user_rules
        auto_inc, auto_exc = self._auto_rules

        return compile_effective_lists(
            user_includes=user_inc,
            user_excludes=user_exc,
            auto_includes=auto_inc,
            auto_excludes=auto_exc,
            explicit_excludes=self._explicit_excludes,
        )

    def save_user_list(self, path: Optional[Union[str, Path]] = None) -> Path:
        """
        Saves current user rules to file, keeping '!' syntax for exclusions.
        """
        target = Path(path) if path else self.user_list_path
        inc, exc = self._user_rules

        lines: List[str] = ["# Zapret GUI User Domain List"]
        if exc:
            lines.append("# --- Excluded Domains (!domain) ---")
            for dom in sorted(exc):
                lines.append(f"!{dom}")
        if inc:
            lines.append("# --- Included Domains ---")
            for dom in sorted(inc):
                lines.append(dom)
        lines.append("")

        return atomic_write_text(target, "\n".join(lines))

    def save_auto_list(self, path: Optional[Union[str, Path]] = None) -> Path:
        """Saves current auto rules to file."""
        target = Path(path) if path else self.auto_list_path
        inc, exc = self._auto_rules

        lines: List[str] = ["# Zapret GUI Auto Hostlist"]
        for dom in sorted(exc):
            lines.append(f"!{dom}")
        for dom in sorted(inc):
            lines.append(dom)
        lines.append("")

        return atomic_write_text(target, "\n".join(lines))

    def save_exclude_list(self, path: Optional[Union[str, Path]] = None) -> Path:
        """Saves explicit exclude list to file."""
        target = Path(path) if path else self.exclude_list_path
        lines = sorted(self._explicit_excludes)
        content = "\n".join(lines) + ("\n" if lines else "")
        return atomic_write_text(target, content)

    def export_for_engine(
        self,
        output_dir: Union[str, Path],
        hostlist_filename: str = "hostlist.txt",
        exclude_filename: str = "hostlist-exclude.txt",
    ) -> Tuple[Path, Path]:
        """
        Exports compiled, clean lists ready for nfqws / engine.sh.
        Returns (hostlist_path, exclude_path).
        """
        res = self.compile()
        out_dir = Path(output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)

        hl_content = "\n".join(res.hostlist) + ("\n" if res.hostlist else "")
        exc_content = "\n".join(res.exclude_list) + ("\n" if res.exclude_list else "")

        hl_path = atomic_write_text(out_dir / hostlist_filename, hl_content)
        exc_path = atomic_write_text(out_dir / exclude_filename, exc_content)

        return hl_path, exc_path

    @staticmethod
    def get_engine_args(hostlist_path: Union[str, Path], exclude_path: Union[str, Path]) -> List[str]:
        """Returns standard CLI flags for nfqws engine."""
        return [
            f"--hostlist={hostlist_path}",
            f"--hostlist-exclude={exclude_path}",
        ]
