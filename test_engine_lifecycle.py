from pathlib import Path
import re
import pytest

ENGINE_SH_PATH = Path(__file__).parent / "engine.sh"


def test_no_blind_pkill_in_engine_sh():
    content = ENGINE_SH_PATH.read_text(encoding="utf-8")
    # pkill -9 -x nfqws/tpws must NEVER exist (kills other users/system processes)
    assert not re.search(r"pkill\s+-[0-9]+\s+-x\s+(?:nfqws|nfqws2|tpws)", content), (
        "Found blind 'pkill -x' in engine.sh! It must stop only its own units or verify /proc/<pid>/exe."
    )


def test_state_dir_and_lock_in_run():
    content = ENGINE_SH_PATH.read_text(encoding="utf-8")
    assert 'STATE_DIR="/run/zapret-gui"' in content
    assert 'PIDFILE="$STATE_DIR/zapret-gui.pid"' in content
    assert 'LOGFILE="$STATE_DIR/zapret-gui.log"' in content
    assert 'LOCKFILE="$STATE_DIR/engine.lock"' in content
    assert 'WATCHDOG_SCRIPT="$STATE_DIR/zapret-watchdog.sh"' in content
    assert "flock -w 10 200" in content


def test_watchdog_not_in_tmp():
    content = ENGINE_SH_PATH.read_text(encoding="utf-8")
    assert "/tmp/zapret-watchdog.sh" not in content
    assert "/tmp/zapret-gui.pid" not in content


def test_wait_for_process_start_and_rollback_defined():
    content = ENGINE_SH_PATH.read_text(encoding="utf-8")
    assert "wait_for_process_start()" in content
    assert "rollback_startup()" in content
    assert 'wait_for_process_start "zapret2-nfqws"' in content
    assert 'wait_for_process_start "zapret-tpws"' in content
    assert 'wait_for_process_start "zapret-nfqws"' in content


def test_no_false_success_before_health_verified():
    content = ENGINE_SH_PATH.read_text(encoding="utf-8")
    # nft-active marker must only be created after wait_for_process_start succeeds
    assert not re.search(r'nft-active"\s*\n\s*systemctl stop', content), (
        "nft-active marker must NOT be created before launching the engine!"
    )


def test_status_engine_inspects_nft_list_table():
    content = ENGINE_SH_PATH.read_text(encoding="utf-8")
    assert 'nft list table inet "$NFT_TABLE"' in content
    assert 'echo "NFQWS_ONLY"' in content


def test_dns_resolver_preflight_in_engine_sh():
    content = ENGINE_SH_PATH.read_text(encoding="utf-8")
    assert "verify_dns_resolver()" in content
    assert "revert_dns" in content
    assert "restore_blockcheck_dns()" in content


def test_main_restores_dns_after_blockcheck_when_engine_was_stopped():
    main_py = Path(__file__).parent / "main.py"
    content = main_py.read_text(encoding="utf-8")
    assert 'run_engine("dns", self.active_iface, "system")' in content


def test_validate_exec_target_security_in_engine_sh():
    content = ENGINE_SH_PATH.read_text(encoding="utf-8")
    assert "validate_exec_target()" in content
    assert 'validate_exec_target "$DIR/zapret2_core.py"' in content


def test_check_installation_security_logic():
    import main
    # Running from project folder -> portable mode
    is_sys = main.check_installation_security()
    assert is_sys is False




