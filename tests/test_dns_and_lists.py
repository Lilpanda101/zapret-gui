#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for DNS Providers and Advanced Domain Lists Manager with '!' Syntax.
"""

import io
import json
import socket
import struct
import urllib.error
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

import dns_providers
from dns_providers import (
    DNS_CATALOG,
    DNSProvider,
    DNSResolutionError,
    build_dns_query,
    get_provider,
    list_providers,
    parse_dns_response,
    probe_all_rtt,
    probe_rtt,
    resolve_doh,
    resolve_dot,
    resolve_with_fallback,
)
import list_manager
from list_manager import (
    CompilationResult,
    ListManager,
    ListType,
    compile_effective_lists,
    normalize_domain,
    parse_list_text,
    parse_rule_line,
)


# ==============================================================================
# 1. DNS Providers Catalog Tests
# ==============================================================================

class TestDNSCatalog:
    """Tests the DNS catalog completeness and specifications."""

    @pytest.mark.parametrize("provider_id", [
        "cloudflare",
        "google",
        "quad9",
        "adguard",
        "mullvad",
        "comss",
        "nextdns",
    ])
    def test_required_providers_exist(self, provider_id):
        assert provider_id in DNS_CATALOG
        prov = DNS_CATALOG[provider_id]
        assert isinstance(prov, DNSProvider)
        assert prov.id == provider_id
        assert prov.name
        assert prov.doh_url.startswith("https://")
        assert prov.dot_host
        assert len(prov.dot_ips) > 0
        assert prov.dot_port == 853
        assert prov.is_encrypted is True
        assert prov.badge

    def test_get_provider_case_insensitive(self):
        prov1 = get_provider("CLOUDFLARE")
        prov2 = get_provider("  Cloudflare  ")
        assert prov1.id == "cloudflare"
        assert prov1 == prov2

    def test_get_provider_object(self):
        prov = DNS_CATALOG["google"]
        assert get_provider(prov) is prov

    def test_get_unknown_provider_raises(self):
        with pytest.raises(KeyError, match="Unknown DNS provider"):
            get_provider("nonexistent_dns_xyz")

    def test_list_providers(self):
        all_provs = list_providers(include_system=True)
        assert any(p.id == "system" for p in all_provs)

        encrypted_only = list_providers(include_system=False)
        assert not any(p.id == "system" for p in encrypted_only)
        assert len(encrypted_only) >= 7

    def test_provider_matches(self):
        cf = DNS_CATALOG["cloudflare"]
        assert cf.matches("cloud")
        assert cf.matches("CLOUDFLARE")
        assert cf.matches("cloudflare-dns.com")
        assert not cf.matches("adguard")


# ==============================================================================
# 2. DNS Wire Protocol & Resolution Tests
# ==============================================================================

class TestDNSResolution:
    """Tests DNS packet building, parsing, and DoH/DoT resolvers with mocks."""

    def test_build_dns_query(self):
        wire = build_dns_query("example.com", record_type="A", query_id=0x1234)
        assert len(wire) > 12
        # Check Transaction ID
        qid = struct.unpack("!H", wire[:2])[0]
        assert qid == 0x1234
        # Check standard question format contains 'example' and 'com'
        assert b"\x07example\x03com\x00" in wire

    def test_parse_dns_response_ipv4(self):
        # Fake standard response for "example.com" -> 93.184.215.14
        header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)
        qname = b"\x07example\x03com\x00"
        question = qname + struct.pack("!HH", 1, 1)  # QTYPE=A, QCLASS=IN

        # Answer with pointer to qname (0xC00C)
        answer = (
            b"\xc0\x0c"  # pointer to offset 12
            + struct.pack("!HHIH", 1, 1, 300, 4)  # TYPE=A, CLASS=IN, TTL=300, RDLENGTH=4
            + socket.inet_pton(socket.AF_INET, "93.184.215.14")
        )
        fake_response = header + question + answer

        ips = parse_dns_response(fake_response)
        assert ips == ["93.184.215.14"]

    def test_parse_dns_response_error_rcode(self):
        # Response with NXDOMAIN (RCODE = 3)
        header = struct.pack("!HHHHHH", 0x1234, 0x8183, 1, 0, 0, 0)
        qname = b"\x07example\x03com\x00"
        question = qname + struct.pack("!HH", 1, 1)
        ips = parse_dns_response(header + question)
        assert ips == []

    @patch("urllib.request.urlopen")
    def test_resolve_doh_wire_success(self, mock_urlopen):
        # Setup mock wire response
        header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)
        qname = b"\x07example\x03com\x00"
        question = qname + struct.pack("!HH", 1, 1)
        answer = (
            b"\xc0\x0c"
            + struct.pack("!HHIH", 1, 1, 300, 4)
            + socket.inet_pton(socket.AF_INET, "1.1.1.1")
        )
        wire_data = header + question + answer

        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/dns-message"}
        mock_resp.read.return_value = wire_data
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        ips = resolve_doh("example.com", "cloudflare")
        assert ips == ["1.1.1.1"]

    @patch("urllib.request.urlopen")
    def test_resolve_doh_json_fallback_success(self, mock_urlopen):
        # Setup mock JSON response for DoH GET
        json_payload = json.dumps({
            "Status": 0,
            "Answer": [
                {"name": "example.com.", "type": 1, "data": "93.184.215.14"}
            ]
        }).encode("utf-8")

        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "application/dns-json"}
        mock_resp.read.return_value = json_payload
        mock_resp.__enter__.return_value = mock_resp
        mock_urlopen.return_value = mock_resp

        ips = resolve_doh("example.com", "google")
        assert ips == ["93.184.215.14"]

    @patch("urllib.request.urlopen")
    def test_resolve_doh_failure_raises(self, mock_urlopen):
        mock_urlopen.side_effect = urllib.error.URLError("Network unreachable")
        with pytest.raises(DNSResolutionError, match="Failed to resolve"):
            resolve_doh("example.com", "cloudflare")

    def test_resolve_doh_unsupported_provider(self):
        with pytest.raises(DNSResolutionError, match="does not support DoH"):
            resolve_doh("example.com", "system")

    @patch("socket.socket")
    @patch("ssl.create_default_context")
    def test_resolve_dot_success(self, mock_ssl_ctx, mock_socket_cls):
        # Mock TLS connection and response for DoT
        header = struct.pack("!HHHHHH", 0x1234, 0x8180, 1, 1, 0, 0)
        qname = b"\x07example\x03com\x00"
        question = qname + struct.pack("!HH", 1, 1)
        answer = (
            b"\xc0\x0c"
            + struct.pack("!HHIH", 1, 1, 300, 4)
            + socket.inet_pton(socket.AF_INET, "8.8.8.8")
        )
        wire_data = header + question + answer
        prefixed = struct.pack("!H", len(wire_data)) + wire_data

        mock_sock = MagicMock()
        mock_ssl_sock = MagicMock()
        mock_ssl_ctx.return_value.wrap_socket.return_value.__enter__.return_value = mock_ssl_sock

        # Mock recv calls: first returns 2-byte length, second returns wire_data
        mock_ssl_sock.recv.side_effect = [prefixed[:2], prefixed[2:]]

        ips = resolve_dot("example.com", "google")
        assert ips == ["8.8.8.8"]

    @patch("dns_providers.resolve_doh")
    def test_resolve_with_fallback_success_first_try(self, mock_doh):
        mock_doh.return_value = ["1.1.1.1"]
        prov_id, ips = resolve_with_fallback("example.com", providers=["cloudflare", "google"])
        assert prov_id == "cloudflare"
        assert ips == ["1.1.1.1"]

    @patch("dns_providers.resolve_dot")
    @patch("dns_providers.resolve_doh")
    def test_resolve_with_fallback_fallback_to_second(self, mock_doh, mock_dot):
        # Both DoH and DoT fail on first provider, DoH succeeds on second
        mock_doh.side_effect = [
            DNSResolutionError("Cloudflare timeout"),
            ["8.8.8.8"],
        ]
        mock_dot.side_effect = DNSResolutionError("DoT port closed")
        prov_id, ips = resolve_with_fallback("example.com", providers=["cloudflare", "google"])
        assert prov_id == "google"
        assert ips == ["8.8.8.8"]

    @patch("dns_providers.resolve_doh")
    @patch("dns_providers.resolve_dot")
    @patch("dns_providers.resolve_system")
    def test_resolve_with_fallback_system_fallback(self, mock_sys, mock_dot, mock_doh):
        mock_doh.side_effect = DNSResolutionError("DoH down")
        mock_dot.side_effect = DNSResolutionError("DoT down")
        mock_sys.return_value = ["192.168.1.10"]

        prov_id, ips = resolve_with_fallback("example.com", providers=["cloudflare"])
        assert prov_id == "system"
        assert ips == ["192.168.1.10"]


class TestDNSProbing:
    """Tests RTT probe mechanics."""

    @patch("dns_providers.probe_rtt")
    def test_probe_all_rtt(self, mock_probe):
        mock_probe.side_effect = lambda pid, **kwargs: 15.5 if "cloud" in str(pid) else 25.0
        results = probe_all_rtt(["cloudflare", "google"])
        assert results["cloudflare"] == 15.5
        assert results["google"] == 25.0


# ==============================================================================
# 3. List Manager & '!' Exclusion Syntax Tests
# ==============================================================================

class TestListManagerNormalization:
    """Tests RFC 1123 normalization, IDN punycode, and URL parsing."""

    def test_normalize_valid_domains(self):
        assert normalize_domain("example.com") == "example.com"
        assert normalize_domain("SUB.Example.COM") == "sub.example.com"
        assert normalize_domain("api-v2.cdn.discord.gg") == "api-v2.cdn.discord.gg"

    def test_normalize_url_and_path_stripping(self):
        assert normalize_domain("https://youtube.com/watch?v=123") == "youtube.com"
        assert normalize_domain("http://ntc.party:8080/forum") == "ntc.party"
        assert normalize_domain("ftp://files.example.com/pub/") == "files.example.com"

    def test_normalize_leading_wildcards(self):
        assert normalize_domain("*.google.com") == "google.com"
        assert normalize_domain(".discordapp.com") == "discordapp.com"
        assert normalize_domain("*.*.doubleclick.net") == "doubleclick.net"

    def test_normalize_cyrillic_punycode(self):
        # яндекс.рф -> xn--d1acpjx3f.xn--p1ai
        norm = normalize_domain("яндекс.рф")
        assert norm == "xn--d1acpjx3f.xn--p1ai"

    def test_normalize_invalid_inputs(self):
        assert normalize_domain("") is None
        assert normalize_domain("   ") is None
        assert normalize_domain("# comment") is None
        assert normalize_domain("; another comment") is None
        assert normalize_domain("-invalid.com") is None
        assert normalize_domain("invalid-.com") is None
        assert normalize_domain("not_a_valid_domain_!@#") is None


class TestListRulesParsing:
    """Tests parsing rule lines and extended '!' syntax."""

    def test_parse_rule_line_inclusion(self):
        res = parse_rule_line("google.com")
        assert res == ("google.com", False)

        res2 = parse_rule_line("*.googlevideo.com")
        assert res2 == ("googlevideo.com", False)

    def test_parse_rule_line_exclusion(self):
        res = parse_rule_line("!google.com")
        assert res == ("google.com", True)

        res2 = parse_rule_line("! *.rutracker.org")
        assert res2 == ("rutracker.org", True)

        res3 = parse_rule_line("!https://mail.ru/inbox")
        assert res3 == ("mail.ru", True)

    def test_parse_rule_line_comments_and_empty(self):
        assert parse_rule_line("") is None
        assert parse_rule_line("   ") is None
        assert parse_rule_line("# !google.com but commented") is None

    def test_parse_list_text(self):
        text = """
        # Zapret Rules
        google.com
        *.youtube.com
        !yandex.ru
        ! *.vk.com
        twitch.tv
        # invalid lines
        !!!
        """
        includes, excludes = parse_list_text(text)
        assert "google.com" in includes
        assert "youtube.com" in includes
        assert "twitch.tv" in includes
        assert "yandex.ru" in excludes
        assert "vk.com" in excludes
        assert len(includes) == 3
        assert len(excludes) == 2


class TestListCompilationAndPrecedence:
    """Tests unconditional exclusion '!' precedence over inclusions."""

    def test_unconditional_exclusion_direct_override(self):
        # Domain exists in user list, but also has '!' in user or auto list
        user_inc = ["google.com", "discord.com"]
        user_exc = ["google.com"]  # !google.com

        res = compile_effective_lists(
            user_includes=user_inc,
            user_excludes=user_exc,
        )
        # google.com must NOT be in hostlist, must be in exclude_list
        assert "google.com" not in res.hostlist
        assert "google.com" in res.exclude_list
        assert "google.com" in res.overridden_by_exclusion
        assert "discord.com" in res.hostlist

    def test_unconditional_exclusion_subdomain_pruning(self):
        # !google.com must exclude mail.google.com and drive.google.com from hostlist
        user_inc = ["mail.google.com", "drive.google.com", "discord.com"]
        explicit_exc = ["google.com"]

        res = compile_effective_lists(
            user_includes=user_inc,
            explicit_excludes=explicit_exc,
            prune_subdomains=True,
        )
        assert res.hostlist == ["discord.com"]
        assert "google.com" in res.exclude_list
        assert "mail.google.com" in res.overridden_by_exclusion
        assert "drive.google.com" in res.overridden_by_exclusion

    def test_multi_source_deduplication_and_sorting(self):
        user_inc = ["b.com", "a.com", "c.com"]
        auto_inc = ["c.com", "d.com"]
        user_exc = ["z.com"]
        explicit_exc = ["x.com", "z.com"]

        res = compile_effective_lists(
            user_includes=user_inc,
            auto_includes=auto_inc,
            user_excludes=user_exc,
            explicit_excludes=explicit_exc,
        )
        assert res.hostlist == ["a.com", "b.com", "c.com", "d.com"]
        assert res.exclude_list == ["x.com", "z.com"]


class TestListManagerLifecycle:
    """Tests high-level ListManager methods, file persistence, and engine exports."""

    def test_list_manager_add_remove_toggle(self, tmp_path):
        mgr = ListManager(base_dir=tmp_path)

        # Add inclusion
        mgr.add_domain("discord.com", list_type=ListType.USER, is_exclusion=False)
        assert "discord.com" in mgr._user_rules[0]
        assert "discord.com" not in mgr._user_rules[1]

        # Toggle to exclusion (!discord.com)
        now_exc = mgr.toggle_exclusion("discord.com", list_type=ListType.USER)
        assert now_exc is True
        assert "discord.com" not in mgr._user_rules[0]
        assert "discord.com" in mgr._user_rules[1]

        # Toggle back to inclusion
        now_exc = mgr.toggle_exclusion("discord.com", list_type=ListType.USER)
        assert now_exc is False
        assert "discord.com" in mgr._user_rules[0]

        # Remove domain
        removed = mgr.remove_domain("discord.com", list_type=ListType.USER)
        assert removed is True
        assert "discord.com" not in mgr._user_rules[0]

    def test_list_manager_save_and_reload(self, tmp_path):
        user_file = tmp_path / "custom_hosts.txt"
        mgr = ListManager(base_dir=tmp_path, user_list_path=user_file)

        mgr.add_domain("youtube.com", list_type=ListType.USER, is_exclusion=False)
        mgr.add_domain("google.com", list_type=ListType.USER, is_exclusion=True)  # !google.com
        mgr.save_user_list()

        saved_text = user_file.read_text(encoding="utf-8")
        assert "!google.com" in saved_text
        assert "youtube.com" in saved_text

        # Reload fresh instance from disk
        mgr2 = ListManager(base_dir=tmp_path, user_list_path=user_file)
        res = mgr2.compile()
        assert res.hostlist == ["youtube.com"]
        assert res.exclude_list == ["google.com"]

    def test_list_manager_export_for_engine(self, tmp_path):
        out_dir = tmp_path / "engine_lists"
        mgr = ListManager(base_dir=tmp_path)
        mgr.add_domain("allowed.org", list_type=ListType.USER, is_exclusion=False)
        mgr.add_domain("blocked.org", list_type=ListType.USER, is_exclusion=True)

        hl_path, exc_path = mgr.export_for_engine(
            output_dir=out_dir,
            hostlist_filename="hostlist.txt",
            exclude_filename="hostlist-exclude.txt",
        )
        assert hl_path.is_file()
        assert exc_path.is_file()

        assert hl_path.read_text(encoding="utf-8").strip() == "allowed.org"
        assert exc_path.read_text(encoding="utf-8").strip() == "blocked.org"

        args = mgr.get_engine_args(hl_path, exc_path)
        assert args == [
            f"--hostlist={hl_path}",
            f"--hostlist-exclude={exc_path}",
        ]
