import json
from pathlib import Path

import pytest

import zapret2_core as core


SAMPLE = """# test preset
--lua-init=@lua/zapret-lib.lua
--blob=tls:@bin/tls.bin
--wf-tcp-out=80,443
--wf-udp-out=443,50000-50100
--wf-tcp-in=443
--new=YouTube
--filter-tcp=443
--hostlist=lists/list-general.txt
--lua-desync=multisplit:pos=1
--new=Discord
--skip
--filter-udp=50000-50100
--lua-desync=fake:blob=tls
"""


def test_profile_parse_toggle_and_replace_roundtrip():
    document = core.PresetDocument.parse(SAMPLE)
    assert [(p.name, p.enabled) for p in document.profiles] == [("YouTube", True), ("Discord", False)]
    document.set_profile_enabled(1, True)
    assert all(p.enabled for p in document.profiles)
    document.set_profile_enabled(0, False)
    assert [p.enabled for p in document.profiles] == [False, True]
    document.replace_profile(1, "--new=Voice\n--filter-udp=3478\n--lua-desync=fake\n")
    reparsed = core.PresetDocument.parse(document.text())
    assert reparsed.profiles[1].name == "Voice"
    assert reparsed.profiles[1].filters == ["--filter-udp=3478"]
    assert core.PresetDocument.parse(reparsed.text()).text() == reparsed.text()


def test_profile_editor_rejects_multiple_profiles():
    document = core.PresetDocument.parse(SAMPLE)
    with pytest.raises(core.PresetError, match="ровно один"):
        document.replace_profile(0, SAMPLE)


def test_adapter_maps_resources_and_windows_filters(tmp_path):
    app = tmp_path / "app"
    (app / "fake").mkdir(parents=True)
    (app / "lists").mkdir()
    (app / "zapret2" / "lua").mkdir(parents=True)
    (app / "fake" / "tls.bin").write_bytes(b"tls")
    (app / "lists" / "list-general.txt").write_text("youtube.com\n")
    (app / "zapret2" / "lua" / "zapret-lib.lua").write_text("-- lua\n")
    adapted = core.adapt_preset(SAMPLE, app, app / "zapret2", tmp_path / "writable")
    assert adapted.profile_count == 2
    assert not any(arg.startswith("--wf-") for arg in adapted.arguments)
    assert str(app / "zapret2" / "lua" / "zapret-lib.lua") in adapted.arguments[0]
    assert str(app / "fake" / "tls.bin") in adapted.arguments[1]
    assert adapted.firewall.tcp_out == ["80", "443"]
    assert adapted.firewall.udp_out == ["443", "50000-50100"]
    assert adapted.firewall.tcp_in == ["443"]


def test_adapter_allows_inline_lua_init(tmp_path):
    text = SAMPLE.replace("--lua-init=@lua/zapret-lib.lua", "--lua-init=fake_zero=string.rep(string.char(0),64)")
    text = text.replace("--blob=tls:@bin/tls.bin\n", "").replace("--hostlist=lists/list-general.txt\n", "")
    adapted = core.adapt_preset(text, tmp_path, tmp_path / "zapret2", tmp_path / "writable")
    assert "--lua-init=fake_zero=string.rep(string.char(0),64)" in adapted.arguments


def test_adapter_rejects_missing_resources_and_traversal(tmp_path):
    with pytest.raises(core.PresetError, match="Отсутствуют ресурсы"):
        core.adapt_preset(SAMPLE, tmp_path, tmp_path / "zapret2", tmp_path / "writable")
    evil = SAMPLE.replace("@bin/tls.bin", "@bin/../engine.sh")
    with pytest.raises(core.PresetError):
        core.adapt_preset(evil, tmp_path, tmp_path / "zapret2", tmp_path / "writable")


def test_nftables_has_both_directions_and_loop_guard():
    spec = core.FirewallSpec(["80", "443"], ["443"], ["443"], ["443"], True)
    script = core.render_nftables(spec, "enp5s0")
    assert 'oifname "enp5s0"' in script
    assert 'iifname "enp5s0" tcp sport 443' in script
    assert "meta mark & 0x40000000" in script
    assert "queue num 201 bypass" in script
    assert 'tcp dport { 53, 853 } accept' in script
    assert 'udp sport { 53, 853 } accept' in script
    assert "tcp flags & (syn|ack|rst) == syn" in script
    with pytest.raises(core.PresetError):
        core.render_nftables(spec, 'bad"; delete table inet filter')


def test_calling_user_home_under_pkexec(monkeypatch, tmp_path):
    monkeypatch.setattr(core.os, "geteuid", lambda: 0)
    monkeypatch.delenv("SUDO_USER", raising=False)
    monkeypatch.setenv("PKEXEC_UID", "1000")

    class Entry:
        pw_name = "user"
        pw_dir = str(tmp_path)

    monkeypatch.setattr(core.pwd, "getpwuid", lambda uid: Entry())
    monkeypatch.setattr(core.pwd, "getpwnam", lambda name: Entry())
    assert core._calling_user_home() == tmp_path


def test_catalog_rejects_path_traversal():
    with pytest.raises(core.PresetError):
        core.preset_path("../../engine.sh")


def test_prepare_runs_validation_before_publishing(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "USER_PRESETS", tmp_path / "user")
    app = tmp_path / "app"
    preset_dir = app / "zapret2" / "presets" / "winws2_builtin"
    preset_dir.mkdir(parents=True)
    (app / "fake").mkdir()
    (app / "lists").mkdir()
    (app / "zapret2" / "lua").mkdir()
    (app / "fake" / "tls.bin").write_bytes(b"tls")
    (app / "lists" / "list-general.txt").write_text("youtube.com\n")
    (app / "zapret2" / "lua" / "zapret-lib.lua").write_text("-- lua\n")
    (preset_dir / "sample.txt").write_text(SAMPLE)
    output = tmp_path / "runtime"
    metadata = core.prepare_runtime("sample", output, "enp5s0", Path("/bin/true"), app)
    assert metadata["dry_run"] is True
    argv = json.loads((output / "argv.json").read_text())
    assert argv[:5] == [
        "--qnum=201", "--bind-fix4", "--bind-fix6", "--debug=0", "--ctrack-timeouts=60:86400:60:3600"
    ]
    assert "--ipcache-lifetime=86400" in argv
    assert (output / "firewall.nft").is_file()


def test_log_analyzer_extracts_errors_and_strategies(tmp_path):
    log = tmp_path / "engine.log"
    log.write_text("profile=YouTube strategy=3\nERROR undefined function\nprofile=YouTube strategy=3\n")
    report = core.analyze_log(log)
    assert "ошибок: 1" in report["summary"]
    assert report["strategies"] == {"3": 2}
    assert "undefined function" in report["errors"][0]


def test_normalize_preset_id_resolves_and_prevents_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "USER_PRESETS", tmp_path / "user")
    # Проверка нормализации с .txt и без
    assert core.normalize_preset_id("general ALT") == "general ALT.txt"
    assert core.normalize_preset_id("general ALT.txt") == "general ALT.txt"
    assert core.normalize_preset_id("general ALT.txt.txt") == "general ALT.txt"
    assert core.normalize_preset_id("general ALT.TXT") == "general ALT.txt"

    # Некорректные имена и traversal
    for bad in ("", "   ", ".txt", ".", "..", "../../etc/passwd", "dir/preset.txt"):
        with pytest.raises(core.PresetError):
            core.normalize_preset_id(bad)

    # Сохранение пресета без дублирования расширения
    saved_path = core.save_user_preset("my_test_preset", SAMPLE)
    assert saved_path.name == "my_test_preset.txt"
    assert saved_path.is_file()

    # load_preset разрешает как с .txt так и без
    content_no_ext = core.load_preset("my_test_preset")
    content_with_ext = core.load_preset("my_test_preset.txt")
    assert content_no_ext == content_with_ext == core.PresetDocument.parse(SAMPLE).text()

    # reset_user_preset удаляет файл независимо от суффикса .txt
    core.reset_user_preset("my_test_preset")
    assert not saved_path.exists()


def test_preset_categorization_and_game_warning():
    # Recommended
    assert core.categorize_preset("general ALT") == "recommended"
    assert core.categorize_preset("general ALT.txt") == "recommended"
    assert core.categorize_preset("general ALT2.txt") == "recommended"
    assert core.categorize_preset("Default (circular)") == "recommended"
    assert core.categorize_preset("general FAKE TLS AUTO") == "recommended"
    assert core.categorize_preset("ALL TCP & UDP hostfakesplit") == "recommended"
    assert core.categorize_preset("ALL TCP & UDP hostfakesplit_multi_syndata.txt") == "recommended"

    # Game
    assert core.categorize_preset("Default (game filter)") == "game"
    assert core.categorize_preset("Gaming (game filter).txt") == "game"
    assert core.categorize_preset("general ALT (game filter).txt") == "game"

    # Circular
    assert core.categorize_preset("custom (circular)") == "circular"
    assert core.categorize_preset("custom (circular).txt") == "circular"
    assert core.categorize_preset("some_custom", text="--lua-desync=zapret-multishake") == "circular"
    assert core.categorize_preset("some_custom", text="--lua-desync=zapret-auto") == "circular"

    # Other
    assert core.categorize_preset("slow disorder") == "other"
    assert core.categorize_preset("tls records.txt") == "other"

    # Предупреждение для игровых пресетов
    assert core.get_preset_warning("Default (game filter)") == core.GAME_PRESET_WARNING
    assert "ipset вместо SNI hostlist" in core.GAME_PRESET_WARNING
    assert core.get_preset_warning("general ALT") is None


def test_discover_presets_includes_categories():
    presets = core.discover_presets()
    assert presets, "Каталог пресетов не должен быть пустым"
    categories = {p["category"] for p in presets}
    assert "recommended" in categories
    assert "game" in categories
    for p in presets:
        assert p["category"] in {"recommended", "game", "circular", "other"}
        if p["category"] == "game":
            assert "warning" in p
            assert "ipset" in p["warning"]


def test_auto_hostlist_functions(tmp_path, monkeypatch):
    # Приоритет runtime файла
    fake_runtime = tmp_path / "runtime_autohostlist.txt"
    fake_runtime.write_text("domain.com\n")
    monkeypatch.setattr(core, "RUNTIME_AUTOHOSTLIST", fake_runtime)
    assert core.get_auto_hostlist_path() == fake_runtime

    # Фолбэк для root vs обычного пользователя, если runtime нет
    monkeypatch.setattr(core, "RUNTIME_AUTOHOSTLIST", tmp_path / "nonexistent.txt")
    monkeypatch.setattr(core.os, "geteuid", lambda: 0)
    assert core.get_auto_hostlist_path() == Path("/var/lib/zapret-gui/autohostlist.txt")

    monkeypatch.setattr(core.os, "geteuid", lambda: 1000)
    monkeypatch.setattr(core, "_calling_user_home", lambda: tmp_path)
    assert core.get_auto_hostlist_path() == tmp_path / ".config" / "zapret-gui" / "autohostlist.txt"

    # Статистика несуществующего файла
    fake_file = tmp_path / "autohostlist.txt"
    stats_empty = core.get_auto_hostlist_stats(fake_file)
    assert stats_empty == {"count": 0, "size": 0, "domains": []}

    # Запись доменов и получение статистики
    fake_file.write_text("# Auto hostlist\ngoogle.com\n\nntc.party\n# comment\n", encoding="utf-8")
    stats = core.get_auto_hostlist_stats(fake_file)
    assert stats["count"] == 2
    assert stats["domains"] == ["google.com", "ntc.party"]
    assert stats["size"] > 0

    # Очистка файла
    assert core.clear_auto_hostlist(fake_file) is True
    stats_after_clear = core.get_auto_hostlist_stats(fake_file)
    assert stats_after_clear["count"] == 0
    assert stats_after_clear["size"] == 0
    assert stats_after_clear["domains"] == []


def test_adapt_preset_auto_hostlist_injection(tmp_path):
    app = tmp_path / "app"
    (app / "fake").mkdir(parents=True)
    (app / "lists").mkdir()
    (app / "zapret2" / "lua").mkdir(parents=True)
    (app / "fake" / "tls.bin").write_bytes(b"tls")
    (app / "lists" / "list-general.txt").write_text("youtube.com\n")
    (app / "zapret2" / "lua" / "zapret-lib.lua").write_text("-- lua\n")

    writable = tmp_path / "writable"

    # Без enable_auto_hostlist
    adapted_normal = core.adapt_preset(SAMPLE, app, app / "zapret2", writable, enable_auto_hostlist=False)
    assert not any(a.startswith("--hostlist-auto=") for a in adapted_normal.arguments)

    # С enable_auto_hostlist=True
    adapted_auto = core.adapt_preset(SAMPLE, app, app / "zapret2", writable, enable_auto_hostlist=True)
    auto_args = [a for a in adapted_auto.arguments if a.startswith("--hostlist-auto=")]
    # В SAMPLE два профиля: первый (YouTube) с --hostlist, второй (Discord) без --hostlist
    assert len(auto_args) == 1
    assert str(writable / "autohostlist.txt") in auto_args[0]

    # Проверяем позицию: должен идти сразу после --hostlist
    hl_idx = [i for i, a in enumerate(adapted_auto.arguments) if a.startswith("--hostlist=")][0]
    auto_idx = adapted_auto.arguments.index(auto_args[0])
    assert auto_idx == hl_idx + 1


def test_render_nftables_discord_voice_unlimited_packets():
    # Discord voice and STUN ports must not be cut off after 5 packets
    spec = core.FirewallSpec(
        tcp_out=["80", "443"],
        udp_out=["443", "50000-50100", "19294-19344"],
        tcp_in=["443"],
        udp_in=["50000-50100"],
    )
    script = core.render_nftables(spec, "enp5s0")
    # Web UDP (443) has ct original packets
    assert 'udp dport 443 ct original packets 1-12' in script
    # Discord voice / STUN UDP has NO ct packet count limit
    assert 'udp dport { 50000-50100, 19294-19344 } queue num 201 bypass' in script
    # Discord voice incoming has NO ct packet count limit
    assert 'udp sport 50000-50100 queue num 201 bypass' in script

    # Numeric sub-ranges (like 50000-50099 from Windows bat presets) must also be detected
    spec_sub = core.FirewallSpec(udp_out=["443", "50000-50099"])
    script_sub = core.render_nftables(spec_sub, "enp5s0")
    assert 'udp dport 50000-50099 queue num 201 bypass' in script_sub


def test_adapt_preset_boosts_ipcache_lifetime(tmp_path):
    app = tmp_path / "app"
    (app / "fake").mkdir(parents=True)
    (app / "lists").mkdir()
    (app / "zapret2" / "lua").mkdir(parents=True)
    (app / "fake" / "tls.bin").write_bytes(b"tls")
    (app / "lists" / "list-general.txt").write_text("youtube.com\n")
    (app / "zapret2" / "lua" / "zapret-lib.lua").write_text("-- lua\n")

    sample_with_ipcache = SAMPLE + "\n--ipcache-lifetime=8400\n"
    adapted = core.adapt_preset(sample_with_ipcache, app, app / "zapret2", tmp_path / "writable")
    assert "--ipcache-lifetime=86400" in adapted.arguments
    assert "--ipcache-lifetime=8400" not in adapted.arguments

