from pathlib import Path
import pytest

from profile_manager import ProfileManager, ServiceProfileTemplate
import zapret2_core as core


def test_profile_manager_loads_templates():
    mgr = ProfileManager.load()
    assert mgr.total_count >= 100

    # Ensure strict ban on Discord/Telegram
    for tpl in mgr.templates:
        lower = f"{tpl.name} {tpl.raw_text}".lower()
        assert "discord" not in lower, f"Discord found in template: {tpl.name}"
        assert "telegram" not in lower, f"Telegram found in template: {tpl.name}"


def test_profile_manager_categories_and_services():
    mgr = ProfileManager.load()
    categories = mgr.categories
    assert "видео" in categories
    assert "игры" in categories
    assert "стриминг" in categories
    assert "торренты" in categories
    assert "веб" in categories

    services = mgr.services
    assert "YouTube" in services
    assert "Twitch" in services
    assert "Steam" in services
    assert "Rutracker" in services


def test_attach_service_profile_overlay_preset():
    mgr = ProfileManager.load()
    sample_tpl = next(t for t in mgr.templates if t.service == "YouTube" and "googlevideo" in t.name.lower())

    initial_preset_text = (
        "# Preset: Test Overlay\n"
        "--lua-desync=fake:blob=tls_google\n"
        "--name=Основной веб\n"
        "--filter-tcp=443\n"
        "--hostlist=lists/allzone.txt\n"
    )
    doc = core.PresetDocument.parse(initial_preset_text)
    assert len(doc.profiles) == 1
    assert doc.profiles[0].name == "Основной веб"

    updated_doc = mgr.attach_to_preset_doc(doc, sample_tpl)
    assert len(updated_doc.profiles) == 2
    # First profile intact
    assert updated_doc.profiles[0].name == "Основной веб"
    assert updated_doc.profiles[0].filters == ["--filter-tcp=443", "--hostlist=lists/allzone.txt"]

    # Second profile attached from template
    new_prof = updated_doc.profiles[1]
    assert new_prof.name == sample_tpl.name
    assert any("googlevideo" in f for f in new_prof.filters)
