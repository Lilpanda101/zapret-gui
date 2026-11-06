#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Unit tests for Support Bundle generator, PII sanitizer, and Log Analyzer."""

import json
import tarfile
from pathlib import Path

import pytest

from log_analyzer import (
    AnalysisReport,
    LogAnalyzer,
    LogIncident,
    analyze_log_text,
)
from support_bundle import PIISanitizer, create_support_bundle
from version import get_version


class TestPIISanitizer:
    """Tests for PII sanitization (IP, MAC, user home paths, secrets)."""

    def test_sanitize_private_and_public_ipv4(self):
        sanitizer = PIISanitizer()
        raw = (
            "Connected to local router 192.168.1.1 and server 10.0.4.15. "
            "DMZ host 172.20.1.88, link-local 169.254.10.20. "
            "Public target 93.184.216.34 and DNS 8.8.8.8 reached."
        )
        cleaned = sanitizer.sanitize_text(raw)

        # RFC 1918 subnets
        assert "192.168.1.1" not in cleaned
        assert "192.168.*.*" in cleaned

        assert "10.0.4.15" not in cleaned
        assert "10.*.*.*" in cleaned

        assert "172.20.1.88" not in cleaned
        assert "172.20.*.*" in cleaned

        assert "169.254.10.20" not in cleaned
        assert "169.254.*.*" in cleaned

        # Public IPs
        assert "93.184.216.34" not in cleaned
        assert "93.184.*.*" in cleaned

        assert "8.8.8.8" not in cleaned
        assert "8.8.*.*" in cleaned

    def test_preserve_safe_loopback_and_wildcards(self):
        sanitizer = PIISanitizer()
        raw = "Listening on 0.0.0.0:80, localhost 127.0.0.1:8080, systemd-resolved 127.0.0.53:53"
        cleaned = sanitizer.sanitize_text(raw)

        assert "0.0.0.0" in cleaned
        assert "127.0.0.1" in cleaned
        assert "127.0.0.53" in cleaned

    def test_preserve_app_version_literal(self):
        sanitizer = PIISanitizer()
        ver = get_version()
        raw = f"Starting Zapret 2 GUI v{ver} (build tag v{ver})"
        cleaned = sanitizer.sanitize_text(raw)
        assert ver in cleaned

    def test_sanitize_mac_addresses(self):
        sanitizer = PIISanitizer()
        raw = (
            "Interface eth0 has MAC 00:1a:2b:3c:4d:5e. "
            "WLAN interface MAC is 11-22-33-44-55-66."
        )
        cleaned = sanitizer.sanitize_text(raw)

        assert "00:1a:2b:3c:4d:5e" not in cleaned
        assert "11-22-33-44-55-66" not in cleaned
        assert "XX:XX:XX:XX:XX:XX" in cleaned

    def test_sanitize_ipv6(self):
        sanitizer = PIISanitizer()
        raw = (
            "IPv6 link-local fe80::1ff:fe23:4567:890a, "
            "global 2001:db8:85a3::8a2e:370:7334. "
            "Loopback ::1 is fine."
        )
        cleaned = sanitizer.sanitize_text(raw)

        assert "fe80::1ff:fe23:4567:890a" not in cleaned
        assert "2001:db8:85a3::8a2e:370:7334" not in cleaned
        assert "[REDACTED_IPV6]" in cleaned
        assert "::1" in cleaned

    def test_sanitize_user_home_paths(self):
        sanitizer = PIISanitizer(current_user="secretuser")
        raw = (
            "Config read from /home/secretuser/.config/zapret-gui/config.json. "
            "Another file at /home/admin_dev/work/test.txt."
        )
        cleaned = sanitizer.sanitize_text(raw)

        assert "/home/secretuser" not in cleaned
        assert "/home/admin_dev" not in cleaned
        assert "/home/<user>/.config/zapret-gui/config.json" in cleaned
        assert "/home/<user>/work/test.txt" in cleaned

    def test_sanitize_dict_and_sensitive_keys(self):
        sanitizer = PIISanitizer()
        data = {
            "user_path": "/home/alice/test",
            "api_key": "secret_token_12345",
            "password": "very_secure_password",
            "server_ip": "192.168.10.50",
            "nested": {
                "auth_token": "bearer xyz",
                "normal_field": "public_data",
                "mac": "AA:BB:CC:DD:EE:FF",
            },
            "ip_list": ["10.1.2.3", "127.0.0.1"],
        }
        cleaned = sanitizer.sanitize_data(data)

        assert cleaned["user_path"] == "/home/<user>/test"
        assert cleaned["api_key"] == "[REDACTED_SECRET]"
        assert cleaned["password"] == "[REDACTED_SECRET]"
        assert cleaned["server_ip"] == "192.168.*.*"
        assert cleaned["nested"]["auth_token"] == "[REDACTED_SECRET]"
        assert cleaned["nested"]["normal_field"] == "public_data"
        assert cleaned["nested"]["mac"] == "XX:XX:XX:XX:XX:XX"
        assert cleaned["ip_list"] == ["10.*.*.*", "127.0.0.1"]


class TestLogAnalyzer:
    """Tests for log incident extraction and Russian recommendations."""

    def test_empty_log_returns_clean_report(self):
        report = analyze_log_text("")
        assert report.total_lines == 0
        assert len(report.incidents) == 0
        assert not report.has_errors
        assert not report.has_critical
        assert "успешно" in report.summary

    def test_detect_permission_binding_incident(self):
        lines = [
            "2026-11-06 12:00:01 [INFO] Starting zapret daemon",
            "2026-11-06 12:00:02 [ERROR] bind: Address already in use",
            "2026-11-06 12:00:03 [FATAL] cap_net_admin missing or permission denied on socket",
        ]
        analyzer = LogAnalyzer()
        report = analyzer.analyze_lines(lines)

        assert report.has_critical
        assert report.has_errors
        incident = next(i for i in report.incidents if i.category == "permission_binding")
        assert incident.severity == "CRITICAL"
        assert "CAP_NET_ADMIN" in incident.title
        assert "права" in incident.recommendation.lower()
        assert incident.count == 2  # matches "address already in use" and "cap_net_admin / permission denied"

    def test_detect_conntrack_overflow_incident(self):
        log_sample = (
            "kernel: nf_conntrack: table full, dropping packet\n"
            "zapret: warning: conntrack table limit reached\n"
        )
        report = analyze_log_text(log_sample)

        assert report.has_warnings
        incident = next(i for i in report.incidents if i.category == "conntrack_overflow")
        assert incident.severity == "WARNING"
        assert "conntrack" in incident.title.lower()
        assert "sysctl" in incident.recommendation
        assert incident.count == 2

    def test_detect_nftables_failure_incident(self):
        log_sample = (
            "nftables[1234]: Error: Could not process rule: table already exists\n"
            "engine.sh: line 42: nft: syntax error in chain missing\n"
        )
        report = analyze_log_text(log_sample)

        assert report.has_errors
        incident = next(i for i in report.incidents if i.category == "nftables_failure")
        assert incident.severity == "ERROR"
        assert "nftables" in incident.title.lower()
        assert "nft" in incident.recommendation

    def test_detect_dns_failure_incident(self):
        log_sample = (
            "systemd-resolved[500]: DNS query failed for example.com: NXDOMAIN\n"
            "warn: /etc/resolv.conf is broken symlink\n"
        )
        report = analyze_log_text(log_sample)

        assert report.has_warnings
        incident = next(i for i in report.incidents if i.category == "dns_failure")
        assert "DNS" in incident.title
        assert "resolv.conf" in incident.recommendation

    def test_detect_process_crash_incident(self):
        log_sample = (
            "kernel: nfqws[4321]: segfault at 00000000 ip 00007f sp 00007f error 4 in nfqws\n"
            "systemd[1]: zapret.service: Main process died, code=killed, status=11/SEGV\n"
        )
        report = analyze_log_text(log_sample)

        assert report.has_critical
        incident = next(i for i in report.incidents if i.category == "process_crash")
        assert incident.severity == "CRITICAL"
        assert "nfqws/tpws" in incident.title
        assert "архитектурой" in incident.recommendation

    def test_format_text_output(self):
        log_sample = (
            "2026-11-06 10:00:00 [ERROR] nfqws died with signal 11\n"
            "2026-11-06 10:00:01 [ERROR] failed to bind socket: Operation not permitted\n"
        )
        report = analyze_log_text(log_sample)
        formatted = report.format_text()

        assert "ОТЧЕТ АНАЛИЗАТОРА ЛОГОВ ZAPRET-GUI" in formatted
        assert "Рекомендация:" in formatted
        assert "CRITICAL:" in formatted


class TestSupportBundleCreation:
    """Tests for generating diagnostic bundle archive."""

    def test_create_bundle_end_to_end(self, tmp_path: Path):
        # Prepare mock config
        mock_config = tmp_path / "mock_config.json"
        mock_config.write_text(
            json.dumps({
                "version": 2,
                "preset": "general",
                "custom_hosts": "/home/tester_user/hosts.txt",
                "auth_token": "super_secret_value",
                "server_target": "192.168.1.55",
            }),
            encoding="utf-8",
        )

        # Prepare mock log
        mock_log = tmp_path / "mock_zapret.log"
        mock_log.write_text(
            "2026-11-06 10:00:00 Connection from 10.0.0.5 with MAC AA:BB:CC:11:22:33\n"
            "2026-11-06 10:00:01 /home/tester_user/zapret-gui/engine.sh: bind() failed: Permission denied\n"
            "2026-11-06 10:00:02 nf_conntrack: table full, dropping packet\n",
            encoding="utf-8",
        )

        out_dir = tmp_path / "bundles"
        archive_path = create_support_bundle(
            output_dir=out_dir,
            custom_log_path=mock_log,
            custom_config_path=mock_config,
        )

        assert archive_path.is_file()
        assert archive_path.name.startswith("support_bundle_")
        assert archive_path.name.endswith(".tar.gz")

        # Inspect archive content
        extract_dir = tmp_path / "extracted"
        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(extract_dir)

        bundle_folders = list(extract_dir.glob("support_bundle_*"))
        assert len(bundle_folders) == 1
        bundle_root = bundle_folders[0]

        expected_files = {
            "manifest.json",
            "system_info.json",
            "system_status.json",
            "system_diagnostics.txt",
            "config.json",
            "zapret_logs.txt",
            "analysis_report.json",
            "analysis_report.txt",
        }
        existing_file_names = {f.name for f in bundle_root.iterdir() if f.is_file()}
        assert expected_files.issubset(existing_file_names)

        # Check manifest
        manifest_data = json.loads((bundle_root / "manifest.json").read_text(encoding="utf-8"))
        assert manifest_data["app_version"] == get_version()
        for fname in expected_files:
            if fname != "manifest.json":
                assert fname in manifest_data["files"]
                assert manifest_data["files"][fname]["sha256"]

        # Check system_info
        sys_info = json.loads((bundle_root / "system_info.json").read_text(encoding="utf-8"))
        assert sys_info["app_version"] == get_version()
        assert "os_info" in sys_info

        # Verify strict PII sanitization in config.json
        cfg_text = (bundle_root / "config.json").read_text(encoding="utf-8")
        assert "tester_user" not in cfg_text
        assert "/home/<user>/hosts.txt" in cfg_text
        assert "super_secret_value" not in cfg_text
        assert "[REDACTED_SECRET]" in cfg_text
        assert "192.168.1.55" not in cfg_text
        assert "192.168.*.*" in cfg_text

        # Verify strict PII sanitization in zapret_logs.txt
        logs_text = (bundle_root / "zapret_logs.txt").read_text(encoding="utf-8")
        assert "tester_user" not in logs_text
        assert "10.0.0.5" not in logs_text
        assert "10.*.*.*" in logs_text
        assert "AA:BB:CC:11:22:33" not in logs_text
        assert "XX:XX:XX:XX:XX:XX" in logs_text

        # Verify analysis report inside bundle
        analysis_json = json.loads((bundle_root / "analysis_report.json").read_text(encoding="utf-8"))
        assert analysis_json["has_critical"]
        categories = {inc["category"] for inc in analysis_json["incidents"]}
        assert "permission_binding" in categories
        assert "conntrack_overflow" in categories
