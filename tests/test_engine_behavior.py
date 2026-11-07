import os
import stat
import subprocess
import pytest

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE_SH = os.path.join(APP_DIR, "engine.sh")


def test_wait_for_process_start_honors_pidfile_even_if_unit_failed(tmp_path):
    """
    Critical behavioral test: If systemd-run fails, the unit is marked failed
    (systemctl is-failed returns 0), but the fallback branch launched the process
    directly into PIDFILE. wait_for_process_start MUST check the PID file FIRST,
    verify /proc/<pid>/exe, and NOT abort due to the failed unit!
    """
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_systemctl = fake_bin / "systemctl"
    fake_systemctl.write_text(
        "#!/bin/sh\n"
        "# Fake systemctl where is-failed returns 0 (failed) and is-active returns 3 (inactive)\n"
        "for arg in \"$@\"; do\n"
        "    if [ \"$arg\" = \"is-failed\" ]; then exit 0; fi\n"
        "    if [ \"$arg\" = \"is-active\" ]; then exit 3; fi\n"
        "done\n"
        "exit 1\n",
        encoding="utf-8"
    )
    fake_systemctl.chmod(fake_systemctl.stat().st_mode | stat.S_IEXEC)

    pid_file = tmp_path / "test.pid"
    proc = subprocess.Popen(["sleep", "5"])
    pid_file.write_text(str(proc.pid), encoding="utf-8")

    try:
        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

        bash_cmd = (
            f"source '{ENGINE_SH}' && "
            f"wait_for_process_start 'zapret2-nfqws' '{pid_file}' 2 'sleep'"
        )

        res = subprocess.run(
            ["bash", "-c", bash_cmd],
            env=env,
            capture_output=True,
            text=True
        )

        assert res.returncode == 0, f"wait_for_process_start failed because unit was failed, ignoring alive PID:\n{res.stderr}\n{res.stdout}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()

def test_acquire_lock_idempotency_keeps_flock_locked(tmp_path):
    """
    Behavioral test: Calling acquire_lock multiple times (e.g. start_engine calling stop_engine)
    must NOT close fd 200 and must NOT drop the flock.
    A parallel process attempting non-blocking flock during this time must fail with exit code 1.
    """
    lock_file = tmp_path / "engine.lock"

    # Script: acquires lock, re-acquires (nested), and sleeps while holding lock
    holder_script = (
        f"source '{ENGINE_SH}'\n"
        f"STATE_DIR='{tmp_path}'\n"
        f"LOCKFILE='{lock_file}'\n"
        f"FORCE_LOCK=1\n"
        f"acquire_lock\n"
        f"acquire_lock\n"  # Nested call, should be idempotent
        f"echo 'LOCKED'\n"
        f"sleep 2\n"
        f"release_lock\n"
    )

    proc = subprocess.Popen(
        ["bash", "-c", holder_script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )

    try:
        # Wait until holder confirms lock is acquired
        line = proc.stdout.readline().strip()
        assert line == "LOCKED", f"Holder failed to acquire lock: {proc.stderr.read()}"

        # Parallel process attempts to grab lock non-blockingly
        probe = subprocess.run(
            ["flock", "-n", str(lock_file), "true"],
            capture_output=True
        )
        assert probe.returncode != 0, "Flock was unexpectedly released or not held during nested call!"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()

def test_legacy_path_does_not_create_nft_active_marker_prematurely(tmp_path):
    """
    Behavioral test: In legacy nfqws start path, nft-active marker must NOT be created
    prior to process startup and health verification. If startup fails before or during
    process launch, marker must not be left behind.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    marker = state_dir / "nft-active"

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "nft").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake_bin / "nft").chmod(0o755)

    test_script = (
        f"source '{ENGINE_SH}'\n"
        f"STATE_DIR='{state_dir}'\n"
        f"NFQWS2_STATE_DIR='{state_dir}'\n"
        f"LOCKFILE='{state_dir}/engine.lock'\n"
        f"NFT_TABLE='zapret_test'\n"
        f"LOGFILE='{tmp_path}/test.log'\n"
        f"PIDFILE='{tmp_path}/test.pid'\n"
        f"FORCE_LOCK=1\n"
        f"check_root() {{ return 0; }}\n"
        f"validate_exec_target() {{ return 0; }}\n"
        f"stop_engine() {{ return 0; }}\n"
        f"apply_dns() {{ return 0; }}\n"
        f"apply_ai_hosts() {{ return 0; }}\n"
        f"sync_general_hostlist() {{ return 0; }}\n"
        # Simulate failure in the middle of preparing startup
        f"start_engine 'general' 'any' 'cloudflare' '1' '1' '1' '12' 'all_except_exclude' 'nfqws'\n"
    )

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

    res = subprocess.run(
        ["bash", "-c", test_script],
        env=env,
        capture_output=True,
        text=True
    )

    assert not marker.exists(), f"Premature nft-active marker was created at {marker} before process was verified alive!"

import sys

def test_wait_for_process_start_nfqws2_python_fallback_without_hint(tmp_path):
    """
    Simulates production nfqws2 fallback:
    nohup /usr/bin/python3 "$DIR/zapret2_core.py" run --runtime "$NFQWS2_RUNTIME" &
    The call in engine.sh is 3-argument without hint:
    wait_for_process_start "zapret2-nfqws" "$PIDFILE" 2
    MUST succeed by matching zapret2_core in /proc/<pid>/cmdline!
    """
    fake_script = tmp_path / "zapret2_core.py"
    fake_script.write_text("import time; time.sleep(5)\n", encoding="utf-8")

    proc = subprocess.Popen([sys.executable, str(fake_script), "run", "--runtime", "/tmp/rt"])
    pid_file = tmp_path / "zapret2.pid"
    pid_file.write_text(str(proc.pid), encoding="utf-8")

    try:
        bash_cmd = (
            f"source '{ENGINE_SH}' && "
            f"wait_for_process_start 'zapret2-nfqws' '{pid_file}' 2"
        )
        res = subprocess.run(["bash", "-c", bash_cmd], capture_output=True, text=True)
        assert res.returncode == 0, f"Failed to recognize nfqws2 python process:\n{res.stderr}\n{res.stdout}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()

def test_wait_for_process_start_tpws_fallback_without_hint(tmp_path):
    fake_script = tmp_path / "tpws"
    fake_script.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    fake_script.chmod(0o755)

    proc = subprocess.Popen([str(fake_script)])
    pid_file = tmp_path / "tpws.pid"
    pid_file.write_text(str(proc.pid), encoding="utf-8")

    try:
        bash_cmd = (
            f"source '{ENGINE_SH}' && "
            f"wait_for_process_start 'zapret-tpws' '{pid_file}' 2"
        )
        res = subprocess.run(["bash", "-c", bash_cmd], capture_output=True, text=True)
        assert res.returncode == 0, f"Failed to recognize tpws process:\n{res.stderr}\n{res.stdout}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()

def test_wait_for_process_start_nfqws1_fallback_without_hint(tmp_path):
    fake_script = tmp_path / "nfqws"
    fake_script.write_text("#!/bin/sh\nsleep 5\n", encoding="utf-8")
    fake_script.chmod(0o755)

    proc = subprocess.Popen([str(fake_script)])
    pid_file = tmp_path / "nfqws.pid"
    pid_file.write_text(str(proc.pid), encoding="utf-8")

    try:
        bash_cmd = (
            f"source '{ENGINE_SH}' && "
            f"wait_for_process_start 'zapret-nfqws' '{pid_file}' 2"
        )
        res = subprocess.run(["bash", "-c", bash_cmd], capture_output=True, text=True)
        assert res.returncode == 0, f"Failed to recognize nfqws process:\n{res.stderr}\n{res.stdout}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_init_state_dir_sets_0755_permissions(tmp_path):
    """
    Ensure init_state_dir sets 0755 directory mode (rwxr-xr-x) so that
    unprivileged GUI processes can inspect nft-active and pid files.
    """
    state_dir = tmp_path / "state_test"
    state_dir.mkdir()
    # Emulate previously restrictive 0700 permissions
    state_dir.chmod(0o700)
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o700

    bash_cmd = (
        f"source '{ENGINE_SH}'\n"
        f"STATE_DIR='{state_dir}'\n"
        f"EFFECTIVE_UID=0\n"
        f"init_state_dir\n"
    )
    res = subprocess.run(["bash", "-c", bash_cmd], capture_output=True, text=True)
    assert res.returncode == 0, f"init_state_dir failed: {res.stderr}"
    assert stat.S_IMODE(state_dir.stat().st_mode) == 0o755, "STATE_DIR must be 0755 for unprivileged access"


def test_status_engine_unprivileged_fallback_with_nft_active_returns_active(tmp_path):
    """
    When running as unprivileged user (EUID!=0), direct `nft list` fails (CAP_NET_ADMIN required).
    If the daemon process is alive and $STATE_DIR/nft-active exists, status_engine must
    honour the marker and output ACTIVE with exit code 0.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o755)
    marker = state_dir / "nft-active"
    marker.write_text("", encoding="utf-8")
    marker.chmod(0o644)

    pid_file = state_dir / "zapret-gui.pid"
    proc = subprocess.Popen(["sleep", "10"])
    pid_file.write_text(str(proc.pid), encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    # Mock systemctl to report inactive, so status_engine checks PIDFILE
    (fake_bin / "systemctl").write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    (fake_bin / "systemctl").chmod(0o755)
    # Mock nft to simulate unprivileged permission denied
    (fake_bin / "nft").write_text("#!/bin/sh\necho 'Error: Could not process rule: Permission denied' >&2\nexit 1\n", encoding="utf-8")
    (fake_bin / "nft").chmod(0o755)

    try:
        bash_cmd = (
            f"source '{ENGINE_SH}'\n"
            f"STATE_DIR='{state_dir}'\n"
            f"PIDFILE='{pid_file}'\n"
            f"NFT_TABLE='zapret_test'\n"
            f"EFFECTIVE_UID=1000\n"
            f"status_engine\n"
        )
        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

        res = subprocess.run(["bash", "-c", bash_cmd], env=env, capture_output=True, text=True)
        assert res.returncode == 0, f"Expected ACTIVE (0), got {res.returncode}: stdout={res.stdout}, stderr={res.stderr}"
        assert res.stdout.strip() == "ACTIVE"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_status_engine_unprivileged_fallback_without_nft_active_returns_nfqws_only(tmp_path):
    """
    When running as unprivileged user and nft-active is missing/deleted,
    status_engine must report NFQWS_ONLY with exit code 2.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o755)
    pid_file = state_dir / "zapret-gui.pid"
    proc = subprocess.Popen(["sleep", "10"])
    pid_file.write_text(str(proc.pid), encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "systemctl").write_text("#!/bin/sh\nexit 3\n", encoding="utf-8")
    (fake_bin / "systemctl").chmod(0o755)
    (fake_bin / "nft").write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
    (fake_bin / "nft").chmod(0o755)

    try:
        bash_cmd = (
            f"source '{ENGINE_SH}'\n"
            f"STATE_DIR='{state_dir}'\n"
            f"PIDFILE='{pid_file}'\n"
            f"NFT_TABLE='zapret_test'\n"
            f"EFFECTIVE_UID=1000\n"
            f"status_engine\n"
        )
        env = dict(os.environ)
        env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

        res = subprocess.run(["bash", "-c", bash_cmd], env=env, capture_output=True, text=True)
        assert res.returncode == 2, f"Expected NFQWS_ONLY (2), got {res.returncode}: stdout={res.stdout}, stderr={res.stderr}"
        assert res.stdout.strip() == "NFQWS_ONLY"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()


def test_start_engine_under_set_u_does_not_fail_on_unbound_variable(tmp_path):
    """
    Ensure engine.sh start / restart runs cleanly under `set -euo pipefail` without
    crashing on ENABLE_AUTO_HOSTLIST or missing positional parameters.
    """
    state_dir = tmp_path / "state"
    state_dir.mkdir(mode=0o755)

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    (fake_bin / "nft").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake_bin / "nft").chmod(0o755)
    (fake_bin / "python3").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake_bin / "python3").chmod(0o755)
    (fake_bin / "sysctl").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    (fake_bin / "sysctl").chmod(0o755)

    test_script = (
        f"set -euo pipefail\n"
        f"source '{ENGINE_SH}'\n"
        f"STATE_DIR='{state_dir}'\n"
        f"NFQWS2_RUNTIME='{tmp_path}/runtime'\n"
        f"LOCKFILE='{state_dir}/engine.lock'\n"
        f"NFT_TABLE='zapret_test'\n"
        f"LOGFILE='{tmp_path}/test.log'\n"
        f"PIDFILE='{tmp_path}/test.pid'\n"
        f"FORCE_LOCK=1\n"
        f"check_root() {{ return 0; }}\n"
        f"validate_exec_target() {{ return 0; }}\n"
        f"get_active_iface() {{ echo 'eth0'; }}\n"
        f"stop_engine() {{ return 0; }}\n"
        f"sync_general_hostlist() {{ return 0; }}\n"
        f"start_nfqws2_engine() {{ return 0; }}\n"
        # Test start_engine with 0, partial, and 14 parameters under set -u
        f"start_engine\n"
        f"start_engine 'general' 'any'\n"
        f"start_engine 'general' 'any' 'cloudflare' '1' '1' '1' '12' 'all_except_exclude' 'nfqws2' '' 'Default (circular)' '1' '1' '1'\n"
    )

    env = dict(os.environ)
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"

    res = subprocess.run(
        ["bash", "-c", test_script],
        env=env,
        capture_output=True,
        text=True
    )
    assert res.returncode == 0, f"start_engine failed under set -u:\nSTDOUT: {res.stdout}\nSTDERR: {res.stderr}"

