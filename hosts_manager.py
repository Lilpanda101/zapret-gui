#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Safe, atomic /etc/hosts manager with timestamped backups and RFC validation.
"""

import ipaddress
import os
import re
import shutil
import sys
import tempfile
import time
from typing import List, Tuple

START_MARKER = "# >>> ZAPRET_GUI_AI_HOSTS >>>"
END_MARKER = "# <<< ZAPRET_GUI_AI_HOSTS <<<"
LEGACY_START = "# >>> ZAPRET_GUI_AI_HOSTS"
LEGACY_END = "# <<< ZAPRET_GUI_AI_HOSTS"

DOMAIN_REGEX = re.compile(
    r"^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?(?:\.[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
)


def validate_hosts_line(line: str) -> Tuple[bool, str]:
    """
    Validates a single hosts line.
    Returns (is_valid, cleaned_line).
    Empty lines and comments are valid.
    """
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        return True, line

    parts = stripped.split()
    if len(parts) < 2:
        return False, ""

    ip_str = parts[0]
    try:
        ipaddress.ip_address(ip_str)
    except ValueError:
        return False, ""

    domains = parts[1:]
    valid_domains = [d for d in domains if DOMAIN_REGEX.match(d)]
    if not valid_domains:
        return False, ""

    return True, f"{ip_str}\t{' '.join(valid_domains)}\n"


def backup_hosts_file(hosts_path: str = "/etc/hosts") -> str:
    """Creates a timestamped backup of the hosts file."""
    if not os.path.exists(hosts_path):
        return ""
    dirname = os.path.dirname(hosts_path) or "."
    timestamp = int(time.time())
    backup_path = os.path.join(dirname, f"hosts.zapret.{timestamp}.bak")
    symlink_path = os.path.join(dirname, "hosts.zapret.bak")
    try:
        shutil.copy2(hosts_path, backup_path)
        shutil.copy2(hosts_path, symlink_path)
    except Exception:
        pass
    return backup_path


def clean_hosts_content(content: str) -> str:
    """
    Safely removes Zapret AI block without sed.
    Raises ValueError if markers are unbalanced, preventing wipeout.
    """
    lines = content.splitlines(keepends=True)
    new_lines: List[str] = []
    inside_block = False
    found_start = False
    found_end = False

    for line in lines:
        stripped = line.strip()
        if stripped in (START_MARKER, LEGACY_START):
            inside_block = True
            found_start = True
            continue
        if stripped in (END_MARKER, LEGACY_END):
            inside_block = False
            found_end = True
            continue
        if not inside_block:
            new_lines.append(line)

    if found_start and not found_end:
        raise ValueError("Corrupted hosts markers: START found without END! Aborting to prevent data loss.")

    return "".join(new_lines)


def atomic_write(target_path: str, content: str) -> None:
    """Writes content to target_path atomically using tempfile + os.replace."""
    target_dir = os.path.dirname(os.path.abspath(target_path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=target_dir, prefix=".hosts_tmp_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(target_path):
            mode = os.stat(target_path).st_mode & 0o777
            os.chmod(tmp_path, mode)
        else:
            os.chmod(tmp_path, 0o644)
        os.replace(tmp_path, target_path)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def apply_ai_hosts(src_path: str, target_path: str = "/etc/hosts") -> None:
    """Safely and atomically applies valid hosts entries from src_path to target_path."""
    if not os.path.exists(src_path):
        return

    valid_entries: List[str] = []
    with open(src_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            is_valid, cleaned = validate_hosts_line(line)
            if is_valid and cleaned and not cleaned.startswith("#"):
                valid_entries.append(cleaned)

    orig_content = ""
    if os.path.exists(target_path):
        backup_hosts_file(target_path)
        with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
            orig_content = f.read()

    cleaned_content = clean_hosts_content(orig_content)
    block = f"\n{START_MARKER}\n" + "".join(valid_entries) + f"{END_MARKER}\n"
    new_content = cleaned_content.rstrip() + "\n" + block
    atomic_write(target_path, new_content)


def remove_ai_hosts(target_path: str = "/etc/hosts") -> None:
    """Safely removes Zapret AI entries from target_path."""
    if not os.path.exists(target_path):
        return
    with open(target_path, "r", encoding="utf-8", errors="ignore") as f:
        orig = f.read()
    if "ZAPRET_GUI_AI_HOSTS" not in orig:
        return
    backup_hosts_file(target_path)
    cleaned = clean_hosts_content(orig)
    atomic_write(target_path, cleaned)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: hosts_manager.py {apply <src> [target]|clean [target]}")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "apply":
        src_file = sys.argv[2]
        dst_file = sys.argv[3] if len(sys.argv) > 3 else "/etc/hosts"
        apply_ai_hosts(src_file, dst_file)
    elif cmd == "clean":
        dst_file = sys.argv[2] if len(sys.argv) > 2 else "/etc/hosts"
        remove_ai_hosts(dst_file)
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
