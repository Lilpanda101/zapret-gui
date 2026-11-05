import os
from pathlib import Path
import pytest
import hosts_manager as hm


def test_validate_hosts_line():
    # Valid lines
    assert hm.validate_hosts_line("127.0.0.1 localhost")[0] is True
    assert hm.validate_hosts_line("::1 localhost ip6-localhost")[0] is True
    assert hm.validate_hosts_line("5.175.161.3 api.openai.com chatgpt.com")[0] is True
    assert hm.validate_hosts_line("# This is a comment")[0] is True
    assert hm.validate_hosts_line("   ")[0] is True

    # Invalid lines (missing domain, bad IP, invalid chars)
    assert hm.validate_hosts_line("not-an-ip localhost")[0] is False
    assert hm.validate_hosts_line("127.0.0.1")[0] is False
    assert hm.validate_hosts_line("999.999.999.999 domain.com")[0] is False
    assert hm.validate_hosts_line("127.0.0.1 domain..com")[0] is False
    assert hm.validate_hosts_line("127.0.0.1 -bad-domain.com")[0] is False


def test_atomic_write_simulation_of_failure(tmp_path, monkeypatch):
    target = tmp_path / "hosts"
    target.write_text("127.0.0.1 localhost\n::1 localhost\n", encoding="utf-8")

    # Simulate an exception during write
    def broken_write(*args, **kwargs):
        raise OSError("Disk full simulation")

    monkeypatch.setattr(os, "replace", broken_write)

    with pytest.raises(OSError, match="Disk full simulation"):
        hm.atomic_write(str(target), "CORRUPTED CONTENT")

    # Target must remain pristine, uncorrupted and not truncated!
    assert target.read_text(encoding="utf-8") == "127.0.0.1 localhost\n::1 localhost\n"


def test_clean_hosts_corrupted_markers_protection():
    # Start marker exists, but END marker is missing!
    corrupted = (
        "127.0.0.1 localhost\n"
        "# >>> ZAPRET_GUI_AI_HOSTS >>>\n"
        "5.175.161.3 api.openai.com\n"
        "# End marker accidentally deleted by user\n"
        "192.168.1.1 router.local\n"
    )

    # Must raise ValueError instead of silently deleting everything until EOF!
    with pytest.raises(ValueError, match="Corrupted hosts markers"):
        hm.clean_hosts_content(corrupted)


def test_apply_and_remove_ai_hosts_roundtrip(tmp_path):
    target = tmp_path / "hosts"
    target.write_text("127.0.0.1 localhost\n::1 localhost\n", encoding="utf-8")

    src = tmp_path / "hosts.txt"
    src.write_text(
        "# Smart hosts\n"
        "5.175.161.3 api.openai.com chatgpt.com\n"
        "invalid-ip bad.com\n"  # Must be ignored
        "5.175.161.3 cdn.oaistatic.com\n",
        encoding="utf-8",
    )

    # 1. Apply
    hm.apply_ai_hosts(str(src), str(target))
    content = target.read_text(encoding="utf-8")
    assert "127.0.0.1 localhost" in content
    assert "api.openai.com chatgpt.com" in content
    assert "cdn.oaistatic.com" in content
    assert "invalid-ip" not in content

    # Check backup was created
    backups = list(tmp_path.glob("hosts.zapret.*.bak"))
    assert len(backups) >= 1

    # 2. Remove
    hm.remove_ai_hosts(str(target))
    cleaned = target.read_text(encoding="utf-8")
    assert "127.0.0.1 localhost" in cleaned
    assert "api.openai.com" not in cleaned
    assert "ZAPRET_GUI_AI_HOSTS" not in cleaned
