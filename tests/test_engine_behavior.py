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
