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
