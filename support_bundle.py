#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Support bundle generator for Zapret 2 GUI.

Collects diagnostic information, system status, active configuration,
and sanitized application logs into a compressed support bundle:
`support_bundle_YYYYMMDD_HHMMSS.tar.gz`.

Includes strict PII sanitization:
- IPv4 (RFC 1918 private subnets and public addresses masked as x.x.*.*)
- IPv6 addresses masked
- MAC addresses masked
- User home directory paths (/home/username -> /home/<user>)
- Secrets and tokens redacted
"""

from __future__ import annotations

import getpass
import hashlib
import ipaddress
import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from config_manager import load_config_from_file
from log_analyzer import LogAnalyzer, default_analyzer
from version import APP_NAME, get_version

logger = logging.getLogger("zapret_gui.support_bundle")


class PIISanitizer:
    """Strict PII sanitizer for logs, configs, and system diagnostics."""

    # Loopback and unspecified addresses that are safe and needed for diagnosing local DNS
    PRESERVED_IPS = {"127.0.0.1", "127.0.0.53", "0.0.0.0", "255.255.255.255"}

    # Pattern for IPv4 addresses
    IPV4_PATTERN = re.compile(
        r"(?<![0-9a-zA-Z])"
        r"((?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\."
        r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\."
        r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9])\."
        r"(?:25[0-5]|2[0-4][0-9]|1[0-9]{2}|[1-9]?[0-9]))"
        r"(?!\.[0-9])(?![0-9a-zA-Z])"
    )

    # Pattern for standard MAC addresses
    MAC_PATTERN = re.compile(
        r"\b(?:[0-9a-fA-F]{2}[:-]){5}[0-9a-fA-F]{2}\b"
    )

    # Candidate pattern for IPv6 addresses
    IPV6_CANDIDATE = re.compile(
        r"(?<![0-9a-zA-Z_:])"
        r"([0-9a-fA-F:]{2,39})"
        r"(?![0-9a-zA-Z_:])"
    )

    # User path pattern: /home/<username> -> /home/<user>
    USER_PATH_PATTERN = re.compile(r"/home/(?!<user>)[a-zA-Z0-9_.-]+")

    # Sensitive key pattern for dictionaries
    SENSITIVE_KEY_PATTERN = re.compile(
        r"(?:password|passwd|token|secret|auth|api[_-]?key|credentials)",
        re.IGNORECASE,
    )

    def __init__(self, current_user: Optional[str] = None) -> None:
        try:
            self.current_user = current_user or getpass.getuser()
        except Exception:
            self.current_user = None

    def _mask_ipv4_match(self, match: re.Match) -> str:
        ip_str = match.group(0)
        if ip_str in self.PRESERVED_IPS:
            return ip_str

        # Protect application version literal if identical
        app_ver = get_version()
        if ip_str == app_ver:
            return ip_str

        try:
            octets = [int(p) for p in ip_str.split(".")]
            if len(octets) != 4 or any(o < 0 or o > 255 for o in octets):
                return ip_str

            # Private RFC 1918 & link-local
            if octets[0] == 192 and octets[1] == 168:
                return "192.168.*.*"
            if octets[0] == 10:
                return "10.*.*.*"
            if octets[0] == 172 and (16 <= octets[1] <= 31):
                return f"172.{octets[1]}.*.*"
            if octets[0] == 169 and octets[1] == 254:
                return "169.254.*.*"

            # Public IPs: mask last 2 octets
            return f"{octets[0]}.{octets[1]}.*.*"
        except (ValueError, IndexError):
            return ip_str

    def _mask_ipv6_match(self, match: re.Match) -> str:
        val = match.group(0)
        # Require at least 2 colons to be an IPv6 address
        if val.count(":") < 2:
            return val
        if val in ("::1", "::"):
            return val
        try:
            addr = ipaddress.IPv6Address(val)
            if addr.is_loopback or addr.is_unspecified:
                return val
            return "[REDACTED_IPV6]"
        except ValueError:
            return val

    def sanitize_text(self, text: str) -> str:
        """Sanitize raw text string by masking all PII."""
        if not text:
            return text

        # 1. Mask user home paths: /home/username -> /home/<user>
        result = self.USER_PATH_PATTERN.sub("/home/<user>", text)

        # 2. If current user is known, mask /Users/<current_user> if applicable
        if self.current_user and self.current_user not in ("root", "<user>"):
            result = re.sub(
                rf"/Users/{re.escape(self.current_user)}",
                "/Users/<user>",
                result,
            )

        # 3. Mask MAC addresses: XX:XX:XX:XX:XX:XX
        result = self.MAC_PATTERN.sub("XX:XX:XX:XX:XX:XX", result)

        # 4. Mask IPv6 addresses
        result = self.IPV6_CANDIDATE.sub(self._mask_ipv6_match, result)

        # 5. Mask IPv4 addresses
        result = self.IPV4_PATTERN.sub(self._mask_ipv4_match, result)

        return result

    def sanitize_data(self, data: Any) -> Any:
        """Recursively sanitize dictionaries, lists, and strings."""
        if isinstance(data, str):
            return self.sanitize_text(data)
        if isinstance(data, dict):
            clean_dict = {}
            for k, v in data.items():
                if isinstance(k, str) and self.SENSITIVE_KEY_PATTERN.search(k):
                    clean_dict[k] = "[REDACTED_SECRET]"
                else:
                    clean_dict[k] = self.sanitize_data(v)
            return clean_dict
        if isinstance(data, list):
            return [self.sanitize_data(item) for item in data]
        if isinstance(data, tuple):
            return tuple(self.sanitize_data(item) for item in data)
        return data


default_sanitizer = PIISanitizer()


def _get_os_info() -> Dict[str, str]:
    """Collect Linux distribution and release details."""
    info: Dict[str, str] = {
        "os": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
    }

    # Read /etc/os-release if available
    os_release = Path("/etc/os-release")
    if os_release.is_file():
        try:
            with os_release.open("r", encoding="utf-8", errors="replace") as f:
                for line in f:
                    if "=" in line:
                        k, v = line.strip().split("=", 1)
                        v = v.strip('"\'')
                        if k in ("PRETTY_NAME", "NAME", "ID", "VERSION_ID", "BUILD_ID"):
                            info[k.lower()] = v
        except Exception as exc:
            info["os_release_read_error"] = str(exc)

    return info


def _get_network_subsystem_info() -> Dict[str, Any]:
    """Collect status of systemd, nftables, and conntrack."""
    data: Dict[str, Any] = {
        "systemd_running": False,
        "nftables_installed": False,
        "conntrack_stats": {},
        "raw_diagnostics": "",
    }

    diag_lines: List[str] = []

    # 1. Systemd status
    try:
        res = subprocess.run(
            ["systemctl", "is-system-running"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        data["systemd_running"] = res.returncode == 0
        diag_lines.append(f"systemctl is-system-running: {res.stdout.strip()}")
    except Exception as exc:
        diag_lines.append(f"systemctl check failed: {exc}")

    # 2. Zapret service status if exists
    try:
        res = subprocess.run(
            ["systemctl", "status", "zapret-gui", "--no-pager"],
            capture_output=True,
            text=True,
            check=False,
            timeout=3,
        )
        diag_lines.append("=== systemctl status zapret-gui ===")
        diag_lines.append(res.stdout.strip() or res.stderr.strip() or "Нет вывода")
    except Exception as exc:
        diag_lines.append(f"zapret-gui service status error: {exc}")

    # 3. nftables availability and ruleset
    try:
        nft_bin = shutil.which("nft")
        data["nftables_installed"] = bool(nft_bin)
        if nft_bin:
            res_v = subprocess.run(
                ["nft", "-v"],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
            diag_lines.append(f"=== nftables version: {res_v.stdout.strip()} ===")

            res_rules = subprocess.run(
                ["nft", "list", "table", "inet", "zapret"],
                capture_output=True,
                text=True,
                check=False,
                timeout=3,
            )
            diag_lines.append("=== nft list table inet zapret ===")
            diag_lines.append(res_rules.stdout.strip() or res_rules.stderr.strip() or "Таблица inet zapret не найдена")
    except Exception as exc:
        diag_lines.append(f"nftables inspect failed: {exc}")

    # 4. Conntrack sysctl
    for sysctl_file in (
        "/proc/sys/net/netfilter/nf_conntrack_count",
        "/proc/sys/net/netfilter/nf_conntrack_max",
    ):
        p = Path(sysctl_file)
        if p.is_file():
            try:
                val = p.read_text(encoding="utf-8").strip()
                data["conntrack_stats"][p.name] = val
                diag_lines.append(f"{p.name} = {val}")
            except Exception as exc:
                data["conntrack_stats"][p.name] = f"error: {exc}"

    data["raw_diagnostics"] = "\n".join(diag_lines)
    return data


def _collect_logs(
    custom_log_path: Optional[Union[str, Path]] = None,
    max_lines: int = 2000,
) -> Tuple[str, List[str]]:
    """Gather and truncate application logs safely."""
    collected_lines: List[str] = []
    sources: List[str] = []

    candidates: List[Path] = []
    if custom_log_path:
        candidates.append(Path(custom_log_path))
    candidates.extend(LogAnalyzer.get_default_log_paths())

    seen_real_paths = set()
    for cand in candidates:
        if cand.is_file():
            try:
                real_p = cand.resolve()
                if real_p in seen_real_paths:
                    continue
                seen_real_paths.add(real_p)

                sources.append(str(cand))
                with cand.open("r", encoding="utf-8", errors="replace") as f:
                    file_lines = f.readlines()
                tail = file_lines[-max_lines:]
                collected_lines.append(f"--- LOG FILE: {cand} (последние {len(tail)} строк) ---")
                collected_lines.extend(line.rstrip("\r\n") for line in tail)
            except Exception as exc:
                collected_lines.append(f"--- Ошибка чтения {cand}: {exc} ---")

    # If no file logs found, attempt journalctl
    if not sources:
        try:
            res = subprocess.run(
                ["journalctl", "-u", "zapret-gui", "-n", str(max_lines), "--no-pager"],
                capture_output=True,
                text=True,
                check=False,
                timeout=4,
            )
            if res.stdout.strip():
                sources.append("journalctl -u zapret-gui")
                collected_lines.append(f"--- JOURNALCTL zapret-gui (последние {max_lines} строк) ---")
                collected_lines.extend(res.stdout.splitlines())
        except Exception:
            pass

    if not collected_lines:
        collected_lines.append("Журналы zapret-gui не найдены на стандартных путях и в journalctl.")

    return "\n".join(collected_lines), sources


def create_support_bundle(
    output_dir: Optional[Union[str, Path]] = None,
    custom_log_path: Optional[Union[str, Path]] = None,
    custom_config_path: Optional[Union[str, Path]] = None,
    sanitizer: Optional[PIISanitizer] = None,
) -> Path:
    """Generate a diagnostic tar.gz archive with sanitized information.

    Args:
        output_dir: Directory where the bundle .tar.gz will be saved.
                    Defaults to current working directory.
        custom_log_path: Optional specific log file to include.
        custom_config_path: Optional specific configuration file.
        sanitizer: Optional custom PIISanitizer instance.

    Returns:
        Path to the generated `support_bundle_YYYYMMDD_HHMMSS.tar.gz`.
    """
    cleaner = sanitizer or default_sanitizer
    target_out_dir = Path(output_dir) if output_dir else Path.cwd()
    target_out_dir.mkdir(parents=True, exist_ok=True)

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    bundle_name = f"support_bundle_{timestamp_str}"
    archive_path = target_out_dir / f"{bundle_name}.tar.gz"

    with tempfile.TemporaryDirectory(prefix="zapret_bundle_") as tmp_dir:
        bundle_root = Path(tmp_dir) / bundle_name
        bundle_root.mkdir(parents=True, exist_ok=True)

        manifest: Dict[str, Any] = {
            "bundle_name": bundle_name,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "generator": f"{APP_NAME} Support Bundle Generator",
            "app_version": get_version(),
            "files": {},
        }

        # 1. System Information
        sys_info = {
            "app_name": APP_NAME,
            "app_version": get_version(),
            "python_version": platform.python_version(),
            "os_info": _get_os_info(),
        }
        sys_info_sanitized = cleaner.sanitize_data(sys_info)
        sys_info_path = bundle_root / "system_info.json"
        sys_info_path.write_text(
            json.dumps(sys_info_sanitized, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 2. Systemd / nftables status
        net_info = _get_network_subsystem_info()
        diag_raw = net_info.pop("raw_diagnostics", "")
        net_info_sanitized = cleaner.sanitize_data(net_info)
        net_status_path = bundle_root / "system_status.json"
        net_status_path.write_text(
            json.dumps(net_info_sanitized, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        diag_sanitized = cleaner.sanitize_text(diag_raw)
        diag_path = bundle_root / "system_diagnostics.txt"
        diag_path.write_text(diag_sanitized, encoding="utf-8")

        # 3. Active configuration
        cfg_path_cand = (
            Path(custom_config_path)
            if custom_config_path
            else Path(os.path.expanduser("~/.config/zapret-gui/config.json"))
        )
        if cfg_path_cand.is_file():
            try:
                raw_cfg_text = cfg_path_cand.read_text(encoding="utf-8")
                loaded_cfg = json.loads(raw_cfg_text)
            except Exception:
                loaded_cfg = load_config_from_file(cfg_path_cand)
        else:
            loaded_cfg = {"info": f"Config not found at {cfg_path_cand}"}

        sanitized_cfg = cleaner.sanitize_data(loaded_cfg)
        cfg_out_path = bundle_root / "config.json"
        cfg_out_path.write_text(
            json.dumps(sanitized_cfg, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 4. Logs
        raw_logs, log_sources = _collect_logs(custom_log_path=custom_log_path)
        sanitized_logs = cleaner.sanitize_text(raw_logs)
        logs_out_path = bundle_root / "zapret_logs.txt"
        logs_out_path.write_text(sanitized_logs, encoding="utf-8")

        # 5. Log Analysis Report
        analysis_report = default_analyzer.analyze_text(
            sanitized_logs,
            source=", ".join(log_sources) if log_sources else "collected_logs",
        )
        analysis_json_path = bundle_root / "analysis_report.json"
        analysis_json_path.write_text(
            json.dumps(analysis_report.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        analysis_txt_path = bundle_root / "analysis_report.txt"
        analysis_txt_path.write_text(analysis_report.format_text(), encoding="utf-8")

        # 6. Compute manifest checksums
        for fpath in bundle_root.glob("*"):
            if fpath.is_file():
                h = hashlib.sha256(fpath.read_bytes()).hexdigest()
                manifest["files"][fpath.name] = {
                    "size_bytes": fpath.stat().st_size,
                    "sha256": h,
                }

        manifest_path = bundle_root / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 7. Create tar.gz archive
        with tarfile.open(archive_path, mode="w:gz") as tar:
            tar.add(bundle_root, arcname=bundle_name)

    return archive_path
