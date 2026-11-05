import json

import healer


def test_active_status_is_healthy(monkeypatch):
    monkeypatch.setattr(healer, "run_engine_cmd", lambda *args: (True, "ACTIVE\n", ""))
    assert healer.get_engine_status()[0] is True
    monkeypatch.setattr(healer, "run_engine_cmd", lambda *args: (False, "INACTIVE\n", ""))
    assert healer.get_engine_status()[0] is False


def test_restart_keeps_failure_progress(monkeypatch):
    state = healer.HealerState.__new__(healer.HealerState)
    state.last_restart = 0
    state.restart_history = []
    state.fail_count = 3
    monkeypatch.setattr(state, "save", lambda: None)
    state.record_restart()
    assert state.fail_count == 3
    assert len(state.restart_history) == 1


def test_restart_uses_actual_config_keys(monkeypatch):
    captured = []

    def fake_run(*args):
        captured.append(args)
        return True, "", ""

    monkeypatch.setattr(healer, "run_engine_cmd", fake_run)
    config = {
        "preset": "alt_split", "iface": "enp5s0", "dns": "system", "ai_hosts": False,
        "engine_mode": "nfqws2", "zapret2_preset": "Default v1 (game filter)",
        "enable_youtube": False, "enable_discord_tcp": True, "enable_general_https": False,
    }
    assert healer.restart_engine(config)
    args = captured[0]
    assert args[1:4] == ("alt_split", "enp5s0", "system")
    assert args[4] == "0"
    assert args[11] == "Default v1 (game filter)"
    assert args[12:] == ("0", "1", "0")


def test_switch_to_next_zapret2_preset(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(healer, "CONFIG_FILE", str(config_file))
    config = {"engine_mode": "nfqws2", "zapret2_preset": "general ALT"}

    class State:
        current_preset = None

        def save(self):
            pass

    result = healer.switch_to_next_preset(config, State())
    assert result == "Default (circular)"
    assert json.loads(config_file.read_text())["zapret2_preset"] == result


def test_switch_from_unknown_preset_uses_first_working(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(healer, "CONFIG_FILE", str(config_file))
    config = {"engine_mode": "nfqws2", "zapret2_preset": "unknown_custom_preset"}

    class State:
        current_preset = None

        def save(self):
            pass

    assert healer.switch_to_next_preset(config, State()) == "general ALT"


def test_failure_count_reaches_preset_switch(monkeypatch):
    instance = healer.AutoHealer.__new__(healer.AutoHealer)
    instance.on_status_change = None

    class State:
        fail_count = healer.FAIL_THRESHOLD
        is_healthy = True
        last_check = {}

        def save(self):
            pass

        def can_restart(self):
            return True, "OK"

        def record_restart(self):
            pass

    instance.state = State()
    monkeypatch.setattr(healer, "load_config", lambda: {"engine_mode": "nfqws"})
    monkeypatch.setattr(healer, "get_engine_status", lambda: (True, "ACTIVE"))
    monkeypatch.setattr(healer, "check_all_targets", lambda: (False, {"youtube": {"ok": False}}))
    monkeypatch.setattr(healer, "restart_engine", lambda config: True)
    switched = []
    monkeypatch.setattr(healer, "switch_to_next_preset", lambda config, state: switched.append(True) or "alt_split")

    instance._check_and_heal()
    assert instance.state.fail_count == healer.FAIL_THRESHOLD + 1
    assert not switched
    instance._check_and_heal()
    assert instance.state.fail_count == healer.FAIL_THRESHOLD + 2
    assert switched == [True]


def test_switch_preset_rotation_handles_txt_suffix_and_cycles(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    monkeypatch.setattr(healer, "CONFIG_FILE", str(config_file))

    class State:
        current_preset = None

        def save(self):
            pass

    state = State()

    # Начинаем с суффиксом .txt
    config = {"engine_mode": "nfqws2", "zapret2_preset": "general ALT.txt"}
    res1 = healer.switch_to_next_preset(config, state)
    assert res1 == "Default (circular)"

    res2 = healer.switch_to_next_preset(config, state)
    assert res2 == "general FAKE TLS AUTO"

    # Теперь симулируем, что текущий был сохранён как .txt
    config["zapret2_preset"] = "general FAKE TLS AUTO.txt"
    res3 = healer.switch_to_next_preset(config, state)
    assert res3 == "ALL TCP & UDP hostfakesplit"

    # Замыкание цикла обратно на первый
    config["zapret2_preset"] = "ALL TCP & UDP hostfakesplit.txt"
    res4 = healer.switch_to_next_preset(config, state)
    assert res4 == "general ALT"


def test_healer_state_dns_tracking(tmp_path, monkeypatch):
    state_file = tmp_path / "healer_state.json"
    monkeypatch.setattr(healer, "HEALER_STATE", str(state_file))

    state = healer.HealerState()
    assert state.dns_fail_count == 0
    assert state.last_dns_failover == 0

    state.dns_fail_count = 3
    state.last_dns_failover = 123456.0
    state.save()

    loaded = healer.HealerState()
    assert loaded.dns_fail_count == 3
    assert loaded.last_dns_failover == 123456.0


def test_dns_failure_detection():
    # DNS ошибки
    assert healer.is_dns_error("socket.gaierror: [Errno -2] Name or service not known")
    assert healer.is_dns_error("Temporary failure in name resolution")
    assert healer.is_dns_error("getaddrinfo failed")
    assert not healer.is_dns_error("HTTP 502 Bad Gateway")
    assert not healer.is_dns_error("timed out")

    # check_dns_failure с ошибкой DNS
    results_dns = {
        "google": {"ok": False, "error": "[Errno -3] Temporary failure in name resolution"},
        "youtube": {"ok": False, "error": "[Errno -3] Temporary failure in name resolution"},
        "cloudflare": {"ok": True, "error": None},
    }
    assert healer.check_dns_failure(results_dns) is True

    # check_dns_failure без ошибки DNS (обычные HTTP ошибки)
    results_http = {
        "google": {"ok": False, "error": "HTTP 500"},
        "youtube": {"ok": True, "error": None},
        "cloudflare": {"ok": True, "error": None},
    }
    assert healer.check_dns_failure(results_http) is False


def test_dns_failover_triggers_and_updates_config(monkeypatch, tmp_path):
    config_file = tmp_path / "config.json"
    config = {"engine_mode": "nfqws2", "dns": "system", "iface": "eth0"}
    config_file.write_text(json.dumps(config), encoding="utf-8")
    monkeypatch.setattr(healer, "CONFIG_FILE", str(config_file))

    captured_cmds = []

    def fake_cmd(*args):
        captured_cmds.append(args)
        return True, "", ""

    monkeypatch.setattr(healer, "run_engine_cmd", fake_cmd)

    instance = healer.AutoHealer.__new__(healer.AutoHealer)
    instance.on_status_change = None

    class State:
        fail_count = 0
        dns_fail_count = 0
        last_dns_failover = 0
        is_healthy = True
        last_check = {}
        last_restart = 0

        def save(self):
            pass

        def can_restart(self):
            return True, "OK"

        def record_restart(self):
            pass

    instance.state = State()
    monkeypatch.setattr(healer, "load_config", lambda: json.loads(config_file.read_text()))
    monkeypatch.setattr(healer, "get_engine_status", lambda: (True, "ACTIVE"))
    monkeypatch.setattr(healer, "check_all_targets", lambda: (
        False,
        {
            "google": {"ok": False, "error": "[Errno -2] Name or service not known"},
            "youtube": {"ok": False, "error": "[Errno -2] Name or service not known"},
            "cloudflare": {"ok": True, "error": None},
        }
    ))

    instance._check_and_heal()

    # Должен зафиксировать сбой DNS
    assert instance.state.dns_fail_count == 1
    # Должна вызваться команда смены DNS на cloudflare
    assert ("dns", "eth0", "cloudflare") in captured_cmds
    # Конфиг должен обновиться
    updated_cfg = json.loads(config_file.read_text())
    assert updated_cfg["dns"] == "cloudflare"


def test_healer_ignores_single_discord_failure(monkeypatch):
    instance = healer.AutoHealer.__new__(healer.AutoHealer)
    instance.on_status_change = None

    class State:
        fail_count = 0
        dns_fail_count = 0
        is_healthy = True
        last_check = {}

        def save(self):
            pass

    instance.state = State()
    monkeypatch.setattr(healer, "load_config", lambda: {"engine_mode": "nfqws2"})
    monkeypatch.setattr(healer, "get_engine_status", lambda: (True, "ACTIVE"))
    # Only discord is failing; youtube, google, cloudflare are OK
    monkeypatch.setattr(healer, "check_all_targets", lambda: (
        False,
        {
            "google": {"ok": True, "error": None},
            "youtube": {"ok": True, "error": None},
            "discord": {"ok": False, "error": "HTTP 429 Too Many Requests"},
            "cloudflare": {"ok": True, "error": None},
        }
    ))

    instance._check_and_heal()
    # fail_count must NOT be incremented because primary bypass is working
    assert instance.state.fail_count == 0


def test_healer_ignores_core_internet_outage(monkeypatch):
    instance = healer.AutoHealer.__new__(healer.AutoHealer)
    instance.on_status_change = None

    class State:
        fail_count = 0
        dns_fail_count = 0
        is_healthy = True
        last_check = {}

        def save(self):
            pass

    instance.state = State()
    monkeypatch.setattr(healer, "load_config", lambda: {"engine_mode": "nfqws2"})
    monkeypatch.setattr(healer, "get_engine_status", lambda: (True, "ACTIVE"))
    # Direct IP 1.1.1.1 is unreachable -> general internet outage
    monkeypatch.setattr(healer, "check_all_targets", lambda: (
        False,
        {
            "google": {"ok": False, "error": "Connection timed out"},
            "youtube": {"ok": False, "error": "Connection timed out"},
            "discord": {"ok": False, "error": "Connection timed out"},
            "cloudflare": {"ok": False, "error": "Network unreachable"},
        }
    ))

    instance._check_and_heal()
    # Must NOT increment fail count or trigger restart during general network outage
    assert instance.state.fail_count == 0

