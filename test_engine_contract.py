from types import SimpleNamespace
from unittest.mock import MagicMock

import healer
import main
from main import Zapret2App


def dummy_app():
    return SimpleNamespace(
        active_preset="general", active_iface="enp5s0", active_dns="dns_ai",
        enable_ai_hosts=True, enable_quic=True, enable_discord_voice=False,
        conntrack_limit=12, hostlist_mode="strict_list", engine_mode="nfqws2",
        custom_params="", zapret2_preset="general ALT (game filter)",
        enable_youtube=False, enable_discord_tcp=True, enable_general_https=False,
    )


def test_main_and_healer_use_identical_engine_contract(monkeypatch):
    app = dummy_app()
    main_args = Zapret2App.engine_command(app)
    assert main_args[9] == "nfqws2"
    assert main_args[11] == "general ALT (game filter)"
    assert main_args[12:] == ("0", "1", "0")

    captured = []
    monkeypatch.setattr(healer, "run_engine_cmd", lambda *args: captured.append(args) or (True, "", ""))
    healer.restart_engine({
        "preset": "general", "iface": "enp5s0", "dns": "dns_ai", "ai_hosts": True,
        "enable_quic": True, "enable_discord_voice": False, "conntrack_limit": 12,
        "hostlist_mode": "strict_list", "engine_mode": "nfqws2", "custom_params": "",
        "zapret2_preset": "general ALT (game filter)", "enable_youtube": False,
        "enable_discord_tcp": True, "enable_general_https": False,
    })
    assert captured == [main_args]


def test_programmatic_engine_combo_does_not_restart_twice():
    app = dummy_app()
    app.save_config = lambda: (_ for _ in ()).throw(AssertionError("unexpected save"))
    combo = SimpleNamespace(get_active_id=lambda: "nfqws2")
    Zapret2App.on_engine_mode_changed(app, combo)


def setup_interactive_app(engine_mode="nfqws2"):
    app = dummy_app()
    app.engine_mode = engine_mode
    app.zapret2_preset = "Default (circular)"
    app.btn_auto_preset = SimpleNamespace(set_sensitive=MagicMock(), set_label=MagicMock())
    app.btn_run_check = SimpleNamespace(set_sensitive=MagicMock())
    app.top_tile_preset = SimpleNamespace(set_text=MagicMock())
    app.pill_preset = SimpleNamespace(set_text=MagicMock())
    app.combo_engine_mode = SimpleNamespace(set_active_id=MagicMock())
    app.preset_radios = {
        "general": SimpleNamespace(set_active=MagicMock()),
    }
    app.update_top_tile_mode = MagicMock()
    app.refresh_status = MagicMock()
    app.show_dialog = MagicMock()
    app.save_config = MagicMock()
    app.engine_command = lambda command="start": (
        command, app.active_preset, app.active_iface, app.active_dns,
        "1" if app.enable_ai_hosts else "0",
        "1" if app.enable_quic else "0",
        "1" if app.enable_discord_voice else "0",
        str(app.conntrack_limit), app.hostlist_mode, app.engine_mode,
        app.custom_params, app.zapret2_preset,
        "1" if app.enable_youtube else "0",
        "1" if app.enable_discord_tcp else "0",
        "1" if app.enable_general_https else "0",
    )
    return app


def test_auto_preset_nfqws2_candidates_and_mode_preservation(monkeypatch):
    app = setup_interactive_app(engine_mode="nfqws2")
    captured_runs = []

    monkeypatch.setattr(main.threading, "Thread", lambda target, daemon=True: SimpleNamespace(start=target))
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(main.GLib, "idle_add", lambda func, *args, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr(main, "run_engine", lambda *args: captured_runs.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""))

    requested_urls = []

    class DummyResp:
        def __init__(self, url):
            self.status = 204 if "generate_204" in url else 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(main.urllib.request, "urlopen", lambda req, timeout=3.5: (
        requested_urls.append(req.full_url) or DummyResp(req.full_url)
    ))

    Zapret2App.on_auto_preset_clicked(app, None)

    # Candidate presets tested for Zapret2
    expected_candidates = [
        "general ALT",
        "Default (circular)",
        "general FAKE TLS AUTO",
        "ALL TCP & UDP hostfakesplit",
    ]
    # 4 candidates tested + 1 final engine start
    assert len(captured_runs) == 5

    for i, candidate in enumerate(expected_candidates):
        call_args = captured_runs[i]
        assert call_args[0] == "start"
        assert call_args[9] == "nfqws2"
        assert call_args[11] == candidate

    # Zapret2 engine_mode must NOT be changed to nfqws!
    assert app.engine_mode == "nfqws2"
    assert app.zapret2_preset in expected_candidates
    app.top_tile_preset.set_text.assert_called_with(app.zapret2_preset)
    app.pill_preset.set_text.assert_called_with(f"⚡ {app.zapret2_preset}")

    # Check dialog content uses human-readable names
    assert app.show_dialog.call_count == 1
    dialog_title, dialog_msg = app.show_dialog.call_args[0]
    assert dialog_title == "Автоподбор завершен"
    assert "Default (circular)" in dialog_msg
    assert "general ALT" in dialog_msg


def test_auto_preset_nfqws_mode(monkeypatch):
    app = setup_interactive_app(engine_mode="nfqws")
    captured_runs = []

    monkeypatch.setattr(main.threading, "Thread", lambda target, daemon=True: SimpleNamespace(start=target))
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(main.GLib, "idle_add", lambda func, *args, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr(main, "run_engine", lambda *args: captured_runs.append(args) or SimpleNamespace(returncode=0, stdout="", stderr=""))

    class DummyResp:
        def __init__(self, url):
            self.status = 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(main.urllib.request, "urlopen", lambda req, timeout=3.5: DummyResp(req.full_url))

    Zapret2App.on_auto_preset_clicked(app, None)

    assert app.engine_mode == "nfqws"
    # 5 nfqws candidates tested + 1 final engine start
    assert len(captured_runs) == 6
    assert captured_runs[0][9] == "nfqws"
    assert captured_runs[0][1] == "general"


def test_auto_preset_markers(monkeypatch):
    app = setup_interactive_app(engine_mode="nfqws2")
    requested_urls = []

    monkeypatch.setattr(main.threading, "Thread", lambda target, daemon=True: SimpleNamespace(start=target))
    monkeypatch.setattr(main.time, "sleep", lambda s: None)
    monkeypatch.setattr(main.GLib, "idle_add", lambda func, *args, **kwargs: func(*args, **kwargs))
    monkeypatch.setattr(main, "run_engine", lambda *args: SimpleNamespace(returncode=0, stdout="", stderr=""))

    class DummyResp:
        def __init__(self, url):
            self.status = 204 if "generate_204" in url else 200
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass

    monkeypatch.setattr(main.urllib.request, "urlopen", lambda req, timeout=3.5: (
        requested_urls.append(req.full_url) or DummyResp(req.full_url)
    ))

    Zapret2App.on_auto_preset_clicked(app, None)

    unique_urls = sorted(list(set(requested_urls)))
    assert "https://www.youtube.com/generate_204" in unique_urls
    assert "https://redirector.googlevideo.com/report_mapping" in unique_urls
    assert "https://discord.com/api/v10/gateway" in unique_urls
    assert "https://rutracker.org" in unique_urls
    # Geoblocked OpenAI should not be tested
    assert not any("openai" in u for u in unique_urls)

