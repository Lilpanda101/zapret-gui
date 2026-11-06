import re
import pytest
import zapret2_core as core

VOICE_RANGES = ((3478, 3480), (19294, 19344), (50000, 50100))


def _is_strictly_voice(port_spec: str) -> bool:
    try:
        parts = port_spec.split("-")
        low = int(parts[0])
        high = int(parts[1]) if len(parts) > 1 else low
        return any(v_low <= low and high <= v_high for v_low, v_high in VOICE_RANGES)
    except (ValueError, IndexError):
        return False


def _extract_ports(rule: str) -> list[str]:
    m = re.search(r"udp (?:dport|sport) (?:\{ ([^}]+) \}|([0-9-]+))", rule)
    if not m:
        return []
    if m.group(1):
        return [p.strip() for p in m.group(1).split(",")]
    if m.group(2):
        return [m.group(2).strip()]
    return []


def test_is_voice_media_port():
    # Narrow voice ports & sub-ranges
    assert core.is_voice_media_port("3478-3480") is True
    assert core.is_voice_media_port("3478") is True
    assert core.is_voice_media_port("3479") is True
    assert core.is_voice_media_port("3480") is True
    assert core.is_voice_media_port("19294-19344") is True
    assert core.is_voice_media_port("19300") is True
    assert core.is_voice_media_port("50000-50100") is True
    assert core.is_voice_media_port("50000-50099") is True

    # Wide ranges and web ports MUST NEVER be voice
    assert core.is_voice_media_port("443-65535") is False
    assert core.is_voice_media_port("1-65535") is False
    assert core.is_voice_media_port("1024-65535") is False
    assert core.is_voice_media_port("8080") is False
    assert core.is_voice_media_port("443") is False
    assert core.is_voice_media_port("53") is False


def test_carve_voice_ports_boundaries():
    # Carving 443-65535 must produce exact disjoint segments
    carved = core.carve_range_from_voices(443, 65535)
    assert carved == ["443-3477", "3481-19293", "19345-49999", "50101-65535"]

    # Boundary tests: 3477 is in web, 3478-3480 are carved out, 3481 is in web
    assert core.is_voice_media_port("3477") is False
    assert core.is_voice_media_port("3478") is True
    assert core.is_voice_media_port("3480") is True
    assert core.is_voice_media_port("3481") is False


def test_all_136_presets_udp_rules_strict_ct_or_voice():
    presets = core.discover_presets()
    assert len(presets) == 136

    violations = []
    for p in presets:
        pid = p["id"]
        text = core.load_preset(pid)
        adapted = core.adapt_preset(text)
        script = core.render_nftables(adapted.firewall, "eth0")

        for line in script.splitlines():
            if ("udp dport" in line or "udp sport" in line) and "queue" in line:
                has_ct = ("ct original packets" in line) or ("ct reply packets" in line)
                if not has_ct:
                    ports = _extract_ports(line)
                    non_voice = [port for port in ports if not _is_strictly_voice(port)]
                    if non_voice:
                        violations.append(f"[{pid}] non-voice without ct limit: {non_voice} in rule:\n  {line}")

    assert not violations, f"Обнаружено {len(violations)} нарушений UDP ct-лимита:\n" + "\n".join(violations[:10])


def test_golden_snapshots_and_nft_syntax():
    import subprocess
    import shutil
    from pathlib import Path

    snap_dir = Path("tests/snapshots")
    presets = {
        "general_fake_tls_auto.nft": "general FAKE TLS AUTO.txt",
        "discord_urgent_sni.nft": "ALL TCP & UDP discord_urgent_sni.txt",
        "default_circular.nft": "Default (circular).txt",
        "preset_x_v2_game.nft": "Preset X v2 (game filter).txt",
    }

    for filename, pid in presets.items():
        snap_path = snap_dir / filename
        assert snap_path.is_file(), f"Golden snapshot {filename} missing"
        expected = snap_path.read_text(encoding="utf-8")

        text = core.load_preset(pid)
        adapted = core.adapt_preset(text)
        actual = core.render_nftables(adapted.firewall, "eth0")
        assert actual == expected, f"Snapshot mismatch for {pid}"

        # Проверка синтаксиса nftables в unshare (только если бинарники доступны в системе)
        if not shutil.which("unshare") or not shutil.which("nft"):
            continue

        try:
            res = subprocess.run(["unshare", "-rn", "nft", "-c", "-f", "-"], input=actual, text=True, capture_output=True)
            if res.returncode == 0:
                pass  # Синтаксис проверен в изолированном netns ядра
            elif "Operation not permitted" in res.stderr:
                pytest.skip("unshare netns not allowed in this environment")
            else:
                pytest.fail(f"nft syntax error in {pid}:\n{res.stderr}")
        except FileNotFoundError:
            continue
