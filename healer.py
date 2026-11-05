#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zapret 2 Auto-Healing Daemon
Автоматический мониторинг и восстановление обхода DPI.
"""

import os
import sys
import json
import time
import threading
import subprocess
import urllib.request
import urllib.error
from datetime import datetime

APP_DIR = os.path.dirname(os.path.abspath(__file__))
HEALER_LOG = "/run/zapret-gui/zapret-healer.log" if (os.path.isdir("/run/zapret-gui") and os.access("/run/zapret-gui", os.W_OK)) else "/tmp/zapret-healer.log"
HEALER_STATE = os.path.expanduser("~/.config/zapret-gui/healer_state.json")
CONFIG_FILE = os.path.expanduser("~/.config/zapret-gui/config.json")

TEST_TARGETS = {
    "google": ("https://www.google.com/generate_204", 5),
    "youtube": ("https://www.youtube.com/generate_204", 5),
    "discord": ("https://discord.com/api/v10/gateway", 5),
    "cloudflare": ("https://1.1.1.1/cdn-cgi/trace", 4),
}

FAIL_THRESHOLD = 3
CHECK_INTERVAL = 30
RESTART_COOLDOWN = 60
MAX_RESTARTS_PER_HOUR = 10


class HealerState:
    def __init__(self):
        self.fail_count = 0
        self.dns_fail_count = 0
        self.last_dns_failover = 0
        self.last_restart = 0
        self.restart_history = []
        self.current_preset = None
        self.last_check = {}
        self.is_healthy = True
        self.load()

    def load(self):
        try:
            if os.path.exists(HEALER_STATE):
                with open(HEALER_STATE, "r") as f:
                    data = json.load(f)
                    self.fail_count = data.get("fail_count", 0)
                    self.dns_fail_count = data.get("dns_fail_count", 0)
                    self.last_dns_failover = data.get("last_dns_failover", 0)
                    self.last_restart = data.get("last_restart", 0)
                    self.restart_history = data.get("restart_history", [])
                    self.current_preset = data.get("current_preset")
                    self.is_healthy = data.get("is_healthy", True)
        except Exception:
            pass

    def save(self):
        try:
            os.makedirs(os.path.dirname(HEALER_STATE), exist_ok=True)
            with open(HEALER_STATE, "w") as f:
                json.dump({
                    "fail_count": self.fail_count,
                    "dns_fail_count": self.dns_fail_count,
                    "last_dns_failover": self.last_dns_failover,
                    "last_restart": self.last_restart,
                    "restart_history": self.restart_history[-20:],
                    "current_preset": self.current_preset,
                    "is_healthy": self.is_healthy,
                    "updated": datetime.now().isoformat()
                }, f, indent=2)
        except Exception:
            pass

    def can_restart(self):
        now = time.time()
        if now - self.last_restart < RESTART_COOLDOWN:
            return False, f"Cooldown: {int(RESTART_COOLDOWN - (now - self.last_restart))}s"
        hour_ago = now - 3600
        self.restart_history = [t for t in self.restart_history if t > hour_ago]
        if len(self.restart_history) >= MAX_RESTARTS_PER_HOUR:
            return False, "Rate limit: max restarts per hour reached"
        return True, "OK"

    def record_restart(self):
        now = time.time()
        self.last_restart = now
        self.restart_history.append(now)
        self.save()


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    try:
        with open(HEALER_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


def load_config():
    try:
        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, "r") as f:
                return json.load(f)
    except Exception:
        pass
    return {}


def check_url(url, timeout=5):
    t0 = time.time()
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
                "Accept": "*/*",
            },
            method="HEAD",
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            latency = int((time.time() - t0) * 1000)
            if resp.status in (200, 204, 301, 302, 307):
                return True, latency, None
            return False, latency, f"HTTP {resp.status}"
    except urllib.error.HTTPError as e:
        latency = int((time.time() - t0) * 1000)
        if e.code < 500:
            return True, latency, None
        return False, latency, f"HTTP {e.code}"
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        return False, latency, str(e)


def check_all_targets():
    results = {}
    all_ok = True
    for name, (url, timeout) in TEST_TARGETS.items():
        ok, lat, err = check_url(url, timeout)
        results[name] = {"ok": ok, "latency": lat, "error": err}
        if not ok:
            all_ok = False
    return all_ok, results


def run_engine_cmd(*args):
    cmd = [os.path.join(APP_DIR, "engine.sh")] + list(args)
    try:
        if args and args[0] == "status":
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        else:
            res = subprocess.run(["sudo", "-n"] + cmd, capture_output=True, text=True, timeout=30)
            if res.returncode != 0 and "password" in res.stderr.lower():
                res = subprocess.run(["pkexec"] + cmd, capture_output=True, text=True, timeout=60)
        return res.returncode == 0, res.stdout, res.stderr
    except Exception as e:
        return False, "", str(e)


def get_engine_status():
    ok, stdout, stderr = run_engine_cmd("status")
    status_str = (stdout or "").strip()
    if ok and status_str == "ACTIVE":
        return True, "ACTIVE"
    if status_str == "NFQWS_ONLY":
        return False, "NFQWS_ONLY"
    return False, status_str or stderr or "INACTIVE"


def restart_engine(config):
    from engine_params import EngineParams
    params = EngineParams.from_dict(config)
    log(f"Restarting engine with preset={params.zapret2_preset if params.engine_mode == 'nfqws2' else params.preset}")
    ok, stdout, stderr = run_engine_cmd(*params.to_argv("start"))
    if ok:
        log("Engine restarted successfully")
    else:
        log(f"Engine restart failed: {stderr}", "ERROR")
    return ok


def is_dns_error(err_str):
    if not err_str:
        return False
    lower = str(err_str).lower()
    return any(p in lower for p in (
        "name or service not known",
        "temporary failure in name resolution",
        "getaddrinfo failed",
        "nameresolutionerror",
        "nodename nor servname",
        "dns",
        "resolv",
    ))


def check_dns_failure(results):
    """
    Проверяет, вызван ли сбой неисправностью DNS.
    Сбой считается проблемой DNS, если:
    1) Любой доменный таргет (google, youtube, discord) упал с ошибкой резолвинга DNS.
    2) Или прямой IP cloudflare (1.1.1.1) ответил успешно, но доменные имена падают.
    """
    domain_targets = [k for k in ("google", "youtube", "discord") if k in results]
    failed_targets = [k for k in domain_targets if not results[k].get("ok")]
    if not failed_targets:
        return False

    if any(is_dns_error(results[k].get("error")) for k in failed_targets):
        return True

    if results.get("cloudflare", {}).get("ok") and len(failed_targets) >= 2:
        return True

    return False


def switch_dns_to_cloudflare(config, state):
    iface = config.get("iface", config.get("active_iface", "any"))
    log("DNS failover to cloudflare", "WARN")
    ok, stdout, stderr = run_engine_cmd("dns", iface, "cloudflare")
    config["dns"] = "cloudflare"
    config["active_dns"] = "cloudflare"
    try:
        temporary = CONFIG_FILE + ".tmp"
        with open(temporary, "w") as f:
            json.dump(config, f, indent=2)
        os.replace(temporary, CONFIG_FILE)
    except Exception as e:
        log(f"Failed to save config: {e}", "ERROR")
    state.last_dns_failover = time.time()
    state.save()
    return ok


def switch_to_next_preset(config, state):
    if config.get("engine_mode") == "nfqws2":
        # Безопасные универсальные пресеты Zapret2 с полной поддержкой SNI и YouTube/Discord
        presets = ["general ALT", "Default (circular)", "general FAKE TLS AUTO", "ALL TCP & UDP hostfakesplit"]
        key = "zapret2_preset"
        current = config.get(key, presets[0])
    else:
        presets = ["general", "youtube_discord", "alt_fakedsplit", "alt_split", "multidisorder"]
        key = "preset"
        current = config.get(key, "general")

    # Сравниваем названия без расширения .txt для устранения конфликтов
    current_stem = current.removesuffix(".txt") if isinstance(current, str) else ""
    stems = [p.removesuffix(".txt") for p in presets]
    try:
        idx = stems.index(current_stem)
        next_idx = (idx + 1) % len(presets)
    except ValueError:
        next_idx = 0
    next_preset = presets[next_idx]
    log(f"Switching preset: {current} -> {next_preset}")
    config[key] = next_preset
    try:
        temporary = CONFIG_FILE + ".tmp"
        with open(temporary, "w") as f:
            json.dump(config, f, indent=2)
        os.replace(temporary, CONFIG_FILE)
    except Exception as e:
        log(f"Failed to save config: {e}", "ERROR")
    state.current_preset = next_preset
    state.save()
    return next_preset


class AutoHealer:
    def __init__(self):
        self.state = HealerState()
        self.running = False
        self.thread = None
        self.on_status_change = None

    def start(self):
        if self.running and self.thread and self.thread.is_alive():
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        log("AutoHealer started")

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        log("AutoHealer stopped")

    def _loop(self):
        while self.running:
            try:
                self._check_and_heal()
            except Exception as e:
                log(f"Healer loop error: {e}", "ERROR")
            time.sleep(CHECK_INTERVAL)

    def _check_and_heal(self):
        config = load_config()
        if not config.get("healer_enabled", True):
            return

        engine_ok, engine_info = get_engine_status()
        if not engine_ok:
            if engine_info == "NFQWS_ONLY":
                log("Broken engine state: NFQWS is running without nftables rules (NFQWS_ONLY). Healing...", "WARN")
                self.state.is_healthy = False
                self.state.save()
                self._notify_status(False, "Broken: NFQWS without nftables")
                can_restart, reason = self.state.can_restart()
                if can_restart:
                    if restart_engine(config):
                        self.state.record_restart()
                        log("Engine and nftables recovered successfully")
                else:
                    log(f"Cannot restart to heal NFQWS_ONLY: {reason}", "WARN")
                return

            log("Engine is not running, skipping health check", "WARN")
            self.state.is_healthy = False
            self.state.save()
            return

        all_ok, results = check_all_targets()
        self.state.last_check = {"timestamp": datetime.now().isoformat(), "all_ok": all_ok, "results": results}

        if all_ok:
            if not self.state.is_healthy:
                log("All services recovered")
            self.state.is_healthy = True
            self.state.fail_count = 0
            self.state.dns_fail_count = 0
            self.state.save()
            self._notify_status(True, "All services OK")
            return

        # Если прямое соединение с Cloudflare 1.1.1.1 недоступно, значит упала вся физическая сеть (Wi-Fi/шлюз)
        # В таком случае перезапуск Zapret бесполезен и вреден
        if "cloudflare" in results and not results["cloudflare"].get("ok"):
            log("Core internet access (1.1.1.1) is unreachable; skipping engine restart (network offline)", "WARN")
            self.state.is_healthy = False
            self.state.save()
            self._notify_status(False, "Offline: core internet unreachable")
            return

        failed = [k for k, v in results.items() if not v["ok"]]
        log(f"Failed services: {', '.join(failed)}", "WARN")
        self.state.is_healthy = False
        is_dpi_failure = ("youtube" in failed) or (len(failed) >= 2)
        if is_dpi_failure:
            self.state.fail_count += 1
        else:
            log(f"Transient single endpoint failure: {', '.join(failed)} (core bypass OK, skipping restart)", "INFO")

        # Проверка DNS-сбоя
        if check_dns_failure(results):
            self.state.dns_fail_count += 1
            log(f"DNS failure detected (count={self.state.dns_fail_count})", "WARN")
            current_dns = config.get("dns", config.get("active_dns", ""))
            now = time.time()
            if current_dns != "cloudflare" or (now - getattr(self.state, "last_dns_failover", 0) > 300):
                switch_dns_to_cloudflare(config, self.state)
        else:
            self.state.dns_fail_count = 0

        self.state.save()
        self._notify_status(False, f"Failed: {', '.join(failed)}")

        if self.state.fail_count < FAIL_THRESHOLD:
            log(f"Fail count {self.state.fail_count}/{FAIL_THRESHOLD}, waiting...")
            return

        log(f"Fail threshold reached ({FAIL_THRESHOLD}), attempting recovery...")
        can_restart, reason = self.state.can_restart()
        if not can_restart:
            log(f"Cannot restart: {reason}", "WARN")
            return

        if self.state.fail_count == FAIL_THRESHOLD:
            log("Strategy: Restart engine")
            if restart_engine(config):
                self.state.record_restart()
                log("Engine restarted, monitoring...")
            return

        if self.state.fail_count >= FAIL_THRESHOLD + 4:
            log("Strategy: Full reset (stop + start)")
            run_engine_cmd("stop", config.get("iface", config.get("active_iface", "any")))
            time.sleep(2)
            if restart_engine(config):
                self.state.record_restart()
                log("Full reset completed")
            return

        if self.state.fail_count >= FAIL_THRESHOLD + 2:
            log("Strategy: Switch to next preset")
            new_preset = switch_to_next_preset(config, self.state)
            if restart_engine(config):
                self.state.record_restart()
                log(f"Switched to preset '{new_preset}' and restarted")

    def _notify_status(self, healthy, message):
        if self.on_status_change:
            try:
                self.on_status_change(healthy, message)
            except Exception:
                pass

    def get_status(self):
        return {
            "running": self.running,
            "healthy": self.state.is_healthy,
            "fail_count": self.state.fail_count,
            "dns_fail_count": getattr(self.state, "dns_fail_count", 0),
            "last_check": self.state.last_check,
            "last_restart": self.state.last_restart,
            "current_preset": self.state.current_preset
        }


_healer_instance = None

def get_healer():
    global _healer_instance
    if _healer_instance is None:
        _healer_instance = AutoHealer()
    return _healer_instance


if __name__ == "__main__":
    healer = AutoHealer()
    healer.start()
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        healer.stop()
