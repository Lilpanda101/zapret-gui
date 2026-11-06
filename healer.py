#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zapret 2 Auto-Healing Daemon
Автоматический мониторинг и восстановление обхода DPI на базе строгого FSM.
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
from enum import Enum
from typing import Callable, Optional

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

# Параметры экспоненциального backoff
BACKOFF_BASE = 5.0
BACKOFF_MAX = 300.0
BACKOFF_FACTOR = 2.0
MAX_CONSECUTIVE_FAILURES = 5
DEGRADED_COOLDOWN = 60.0


class HealerFSMState(str, Enum):
    """Состояния FSM демона самовосстановления."""
    IDLE = "IDLE"
    CHECKING = "CHECKING"
    RESTARTING = "RESTARTING"
    BACKOFF = "BACKOFF"
    DEGRADED = "DEGRADED"
    STOPPED = "STOPPED"


# Синоним для совместимости
HealerStateEnum = HealerFSMState


class HealerEvent(str, Enum):
    """События перехода FSM."""
    START = "START"
    CHECK = "CHECK"
    CHECK_SUCCESS = "CHECK_SUCCESS"
    CHECK_FAIL = "CHECK_FAIL"
    RESTART_SUCCESS = "RESTART_SUCCESS"
    RESTART_FAIL = "RESTART_FAIL"
    ATTEMPTS_EXHAUSTED = "ATTEMPTS_EXHAUSTED"
    BACKOFF_EXPIRED = "BACKOFF_EXPIRED"
    STOP = "STOP"


class InvalidTransitionError(Exception):
    """Исключение при попытке выполнить запрещённый переход состояний FSM."""
    def __init__(self, from_state, event):
        super().__init__(f"Invalid FSM transition from {from_state} via event {event}")
        self.from_state = from_state
        self.event = event


def calculate_backoff(attempt: int, base: float = BACKOFF_BASE, factor: float = BACKOFF_FACTOR, max_ceiling: float = BACKOFF_MAX) -> float:
    """Вычисляет экспоненциальную задержку backoff с верхним потолком."""
    if attempt <= 0:
        return 0.0
    delay = base * (factor ** (attempt - 1))
    return min(delay, max_ceiling)


def log(msg, level="INFO"):
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{level}] {msg}"
    print(line)
    try:
        with open(HEALER_LOG, "a") as f:
            f.write(line + "\n")
    except Exception:
        pass


class HealerFSM:
    """
    Строгий конечный автомат (FSM) демона самовосстановления.
    Переходы разрешены строго по таблице VALID_TRANSITIONS.
    """
    VALID_TRANSITIONS = {
        # Из STOPPED
        (HealerFSMState.STOPPED, HealerEvent.START): HealerFSMState.IDLE,
        (HealerFSMState.STOPPED, HealerEvent.STOP): HealerFSMState.STOPPED,

        # Из IDLE
        (HealerFSMState.IDLE, HealerEvent.CHECK): HealerFSMState.CHECKING,
        (HealerFSMState.IDLE, HealerEvent.STOP): HealerFSMState.STOPPED,
        (HealerFSMState.IDLE, HealerEvent.ATTEMPTS_EXHAUSTED): HealerFSMState.DEGRADED,

        # Из CHECKING
        (HealerFSMState.CHECKING, HealerEvent.CHECK_SUCCESS): HealerFSMState.IDLE,
        (HealerFSMState.CHECKING, HealerEvent.CHECK_FAIL): HealerFSMState.RESTARTING,
        (HealerFSMState.CHECKING, HealerEvent.CHECK): HealerFSMState.CHECKING,
        (HealerFSMState.CHECKING, HealerEvent.ATTEMPTS_EXHAUSTED): HealerFSMState.DEGRADED,
        (HealerFSMState.CHECKING, HealerEvent.STOP): HealerFSMState.STOPPED,

        # Из RESTARTING
        (HealerFSMState.RESTARTING, HealerEvent.RESTART_SUCCESS): HealerFSMState.IDLE,
        (HealerFSMState.RESTARTING, HealerEvent.RESTART_FAIL): HealerFSMState.BACKOFF,
        (HealerFSMState.RESTARTING, HealerEvent.ATTEMPTS_EXHAUSTED): HealerFSMState.DEGRADED,
        (HealerFSMState.RESTARTING, HealerEvent.STOP): HealerFSMState.STOPPED,

        # Из BACKOFF
        (HealerFSMState.BACKOFF, HealerEvent.BACKOFF_EXPIRED): HealerFSMState.IDLE,
        (HealerFSMState.BACKOFF, HealerEvent.CHECK): HealerFSMState.CHECKING,
        (HealerFSMState.BACKOFF, HealerEvent.ATTEMPTS_EXHAUSTED): HealerFSMState.DEGRADED,
        (HealerFSMState.BACKOFF, HealerEvent.STOP): HealerFSMState.STOPPED,

        # Из DEGRADED
        (HealerFSMState.DEGRADED, HealerEvent.CHECK): HealerFSMState.CHECKING,
        (HealerFSMState.DEGRADED, HealerEvent.CHECK_SUCCESS): HealerFSMState.IDLE,
        (HealerFSMState.DEGRADED, HealerEvent.RESTART_SUCCESS): HealerFSMState.IDLE,
        (HealerFSMState.DEGRADED, HealerEvent.ATTEMPTS_EXHAUSTED): HealerFSMState.DEGRADED,
        (HealerFSMState.DEGRADED, HealerEvent.STOP): HealerFSMState.STOPPED,
    }

    def __init__(self, initial_state: HealerFSMState = HealerFSMState.STOPPED, on_transition: Optional[Callable] = None):
        self.state = initial_state
        self.on_transition = on_transition
        self.history = []

    def can_transition(self, event: HealerEvent) -> bool:
        return (self.state, event) in self.VALID_TRANSITIONS

    def transition(self, event: HealerEvent, reason: str = "") -> HealerFSMState:
        pair = (self.state, event)
        if pair not in self.VALID_TRANSITIONS:
            log(f"FSM transition rejected: invalid move from {self.state.value} via event {event.value}", "ERROR")
            raise InvalidTransitionError(self.state, event)

        old_state = self.state
        new_state = self.VALID_TRANSITIONS[pair]
        self.state = new_state
        entry = (time.time(), old_state, new_state, event, reason)
        self.history.append(entry)

        log(f"FSM transition: {old_state.value} -> {new_state.value} [event={event.value}, reason='{reason}']")
        if self.on_transition:
            try:
                self.on_transition(old_state, new_state, event, reason)
            except Exception as e:
                log(f"FSM on_transition callback error: {e}", "WARN")

        return new_state


class HealerState:
    def __init__(self):
        self.fail_count = 0
        self.dns_fail_count = 0
        self.last_dns_failover = 0
        self.last_restart = 0
        self.restart_history = []
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


def switch_to_next_preset(config, state=None):
    if config.get("engine_mode") == "nfqws2":
        from catalog.preset_catalog import PresetCatalog, parse_preset_id
        builtin_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "zapret2", "presets", "winws2_builtin")
        catalog = PresetCatalog.load_from_directory(builtin_dir)
        top_entries = catalog.get_top_recommended()
        key = "zapret2_preset"
        current_raw = config.get(key, top_entries[0].id if top_entries else "")
        current_fam = parse_preset_id(current_raw).family
        top_families = [p.family for p in top_entries]
        try:
            idx = top_families.index(current_fam)
            next_idx = (idx + 1) % len(top_entries)
        except ValueError:
            next_idx = 0
        next_preset = top_entries[next_idx].id if top_entries else current_raw
    else:
        presets = ["general", "youtube_discord", "alt_fakedsplit", "alt_split", "multidisorder"]
        key = "preset"
        current_raw = config.get(key, "general")
        try:
            idx = presets.index(current_raw)
            next_idx = (idx + 1) % len(presets)
        except ValueError:
            next_idx = 0
        next_preset = presets[next_idx]

    log(f"Switching preset: {current_raw} -> {next_preset}")
    config[key] = next_preset
    try:
        temporary = CONFIG_FILE + ".tmp"
        with open(temporary, "w") as f:
            json.dump(config, f, indent=2)
        os.replace(temporary, CONFIG_FILE)
    except Exception as e:
        log(f"Failed to save config: {e}", "ERROR")
    return next_preset


class AutoHealer:
    """
    Демон автоматического восстановления обхода DPI.
    Управляется явным конечным автоматом HealerFSM и экспоненциальным backoff.
    """
    def __init__(self, fsm: Optional[HealerFSM] = None):
        self.state = HealerState()
        self.running = False
        self.thread = None
        self.on_status_change = None
        self.on_fsm_transition = None
        self._stop_event = threading.Event()
        self.consecutive_restart_failures = 0
        self.backoff_base = BACKOFF_BASE
        self.backoff_max = BACKOFF_MAX
        self.backoff_factor = BACKOFF_FACTOR
        self.check_interval = CHECK_INTERVAL
        self.degraded_cooldown = DEGRADED_COOLDOWN

        self.fsm = fsm or HealerFSM(
            initial_state=HealerFSMState.STOPPED,
            on_transition=self._handle_fsm_transition
        )

    def _handle_fsm_transition(self, old_state, new_state, event, reason):
        if self.on_fsm_transition:
            try:
                self.on_fsm_transition(old_state, new_state, event, reason)
            except Exception:
                pass
        if new_state == HealerFSMState.DEGRADED:
            self._notify_status(False, f"DEGRADED: {reason}")
        elif new_state == HealerFSMState.BACKOFF:
            self._notify_status(False, f"BACKOFF: {reason}")
        elif new_state == HealerFSMState.RESTARTING:
            self._notify_status(False, "Healing in progress...")

    def start(self):
        if self.running and self.thread and self.thread.is_alive():
            return
        self.running = True
        self._stop_event.clear()
        if self.fsm.state != HealerFSMState.IDLE:
            self.fsm.transition(HealerEvent.START, reason="AutoHealer daemon starting")
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()
        log("AutoHealer started")

    def stop(self):
        self.running = False
        self._stop_event.set()
        if self.fsm.state != HealerFSMState.STOPPED:
            self.fsm.transition(HealerEvent.STOP, reason="AutoHealer daemon stopped")
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=5)
        log("AutoHealer stopped")

    def _calculate_backoff(self) -> float:
        return calculate_backoff(
            self.consecutive_restart_failures,
            base=self.backoff_base,
            factor=self.backoff_factor,
            max_ceiling=self.backoff_max
        )

    def _loop(self):
        while not self._stop_event.is_set():
            current_state = self.fsm.state
            if current_state == HealerFSMState.STOPPED:
                break

            if current_state == HealerFSMState.BACKOFF:
                delay = self._calculate_backoff()
                log(f"FSM in BACKOFF: sleeping for {delay:.1f}s without busy-loop")
                if self._stop_event.wait(timeout=delay):
                    break
                self.fsm.transition(HealerEvent.BACKOFF_EXPIRED, reason="Backoff delay expired")
                continue

            if current_state == HealerFSMState.DEGRADED:
                log(f"FSM in DEGRADED: cooling down for {self.degraded_cooldown:.1f}s")
                if self._stop_event.wait(timeout=self.degraded_cooldown):
                    break
                can_restart, _ = self.state.can_restart()
                if not can_restart:
                    continue
                log("FSM leaving DEGRADED: cooldown elapsed, probing targets")

            try:
                self._check_and_heal()
            except Exception as e:
                log(f"Healer loop error: {e}", "ERROR")

            if self.fsm.state in (HealerFSMState.IDLE, HealerFSMState.DEGRADED):
                if self._stop_event.wait(timeout=self.check_interval):
                    break

    def _check_and_heal(self):
        # Инициализация свойств на случай вызова через __new__ в юнит-тестах
        if not hasattr(self, "fsm"):
            self.fsm = HealerFSM(initial_state=HealerFSMState.IDLE, on_transition=self._handle_fsm_transition)
        if not hasattr(self, "_stop_event"):
            self._stop_event = threading.Event()
        if not hasattr(self, "consecutive_restart_failures"):
            self.consecutive_restart_failures = 0
        if not hasattr(self, "on_status_change"):
            self.on_status_change = None

        if self.fsm.state == HealerFSMState.STOPPED:
            self.fsm.transition(HealerEvent.START, reason="Implicit start before check")

        self.fsm.transition(HealerEvent.CHECK, reason="Periodic health check")

        config = load_config()
        if not config.get("healer_enabled", True):
            self.fsm.transition(HealerEvent.CHECK_SUCCESS, reason="Healer disabled in config")
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
                    self.fsm.transition(HealerEvent.CHECK_FAIL, reason="NFQWS_ONLY detected")
                    if restart_engine(config):
                        self.state.record_restart()
                        self.consecutive_restart_failures = 0
                        self.fsm.transition(HealerEvent.RESTART_SUCCESS, reason="Engine and nftables recovered successfully")
                        log("Engine and nftables recovered successfully")
                    else:
                        self.consecutive_restart_failures += 1
                        if self.consecutive_restart_failures >= MAX_CONSECUTIVE_FAILURES:
                            self.fsm.transition(HealerEvent.ATTEMPTS_EXHAUSTED, reason=f"Restart failed {self.consecutive_restart_failures} times")
                        else:
                            self.fsm.transition(HealerEvent.RESTART_FAIL, reason="Restart command failed")
                else:
                    log(f"Cannot restart to heal NFQWS_ONLY: {reason}", "WARN")
                    self.fsm.transition(HealerEvent.ATTEMPTS_EXHAUSTED, reason=f"Cannot restart: {reason}")
                return

            log("Engine is not running, skipping health check", "WARN")
            self.state.is_healthy = False
            self.state.save()
            self.fsm.transition(HealerEvent.CHECK_SUCCESS, reason="Engine inactive, skipping")
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
            self.consecutive_restart_failures = 0
            self.fsm.transition(HealerEvent.CHECK_SUCCESS, reason="All targets OK")
            return

        # Если прямое соединение с Cloudflare 1.1.1.1 недоступно, значит упала вся физическая сеть (Wi-Fi/шлюз)
        if "cloudflare" in results and not results["cloudflare"].get("ok"):
            log("Core internet access (1.1.1.1) is unreachable; skipping engine restart (network offline)", "WARN")
            self.state.is_healthy = False
            self.state.save()
            self._notify_status(False, "Offline: core internet unreachable")
            self.fsm.transition(HealerEvent.CHECK_SUCCESS, reason="Core internet offline")
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
            self.fsm.transition(HealerEvent.CHECK_SUCCESS, reason=f"Fail count {self.state.fail_count} below threshold {FAIL_THRESHOLD}")
            return

        log(f"Fail threshold reached ({FAIL_THRESHOLD}), attempting recovery...")
        can_restart, reason = self.state.can_restart()
        if not can_restart:
            log(f"Cannot restart: {reason}", "WARN")
            self.fsm.transition(HealerEvent.ATTEMPTS_EXHAUSTED, reason=f"Cannot restart: {reason}")
            return

        # Проверяем, соответствует ли fail_count какой-либо стратегии
        strategy_matched = False
        if self.state.fail_count == FAIL_THRESHOLD:
            strategy_matched = True
            log("Strategy: Restart engine")
            self.fsm.transition(HealerEvent.CHECK_FAIL, reason="DPI failure threshold reached, restarting engine")
            ok = restart_engine(config)
            if ok:
                self.state.record_restart()
                self.consecutive_restart_failures = 0
                self.fsm.transition(HealerEvent.RESTART_SUCCESS, reason="Engine restarted successfully")
                log("Engine restarted, monitoring...")
            else:
                self.consecutive_restart_failures += 1
                if self.consecutive_restart_failures >= MAX_CONSECUTIVE_FAILURES:
                    self.fsm.transition(HealerEvent.ATTEMPTS_EXHAUSTED, reason=f"Restart failed {self.consecutive_restart_failures} times")
                else:
                    self.fsm.transition(HealerEvent.RESTART_FAIL, reason="Restart command failed")
            return

        if self.state.fail_count >= FAIL_THRESHOLD + 4:
            strategy_matched = True
            log("Strategy: Full reset (stop + start)")
            self.fsm.transition(HealerEvent.CHECK_FAIL, reason="DPI persistent failure, full reset")
            run_engine_cmd("stop", config.get("iface", config.get("active_iface", "any")))
            time.sleep(2)
            ok = restart_engine(config)
            if ok:
                self.state.record_restart()
                self.consecutive_restart_failures = 0
                self.fsm.transition(HealerEvent.RESTART_SUCCESS, reason="Full reset completed")
                log("Full reset completed")
            else:
                self.consecutive_restart_failures += 1
                if self.consecutive_restart_failures >= MAX_CONSECUTIVE_FAILURES:
                    self.fsm.transition(HealerEvent.ATTEMPTS_EXHAUSTED, reason=f"Full reset failed {self.consecutive_restart_failures} times")
                else:
                    self.fsm.transition(HealerEvent.RESTART_FAIL, reason="Full reset failed")
            return

        if self.state.fail_count >= FAIL_THRESHOLD + 2:
            strategy_matched = True
            log("Strategy: Switch to next preset")
            self.fsm.transition(HealerEvent.CHECK_FAIL, reason="DPI persistent failure, switching preset")
            new_preset = switch_to_next_preset(config, self.state)
            ok = restart_engine(config)
            if ok:
                self.state.record_restart()
                self.consecutive_restart_failures = 0
                self.fsm.transition(HealerEvent.RESTART_SUCCESS, reason=f"Switched to preset {new_preset} and restarted")
                log(f"Switched to preset '{new_preset}' and restarted")
            else:
                self.consecutive_restart_failures += 1
                if self.consecutive_restart_failures >= MAX_CONSECUTIVE_FAILURES:
                    self.fsm.transition(HealerEvent.ATTEMPTS_EXHAUSTED, reason=f"Preset rotation restart failed {self.consecutive_restart_failures} times")
                else:
                    self.fsm.transition(HealerEvent.RESTART_FAIL, reason="Preset rotation restart failed")
            return

        if not strategy_matched:
            self.fsm.transition(HealerEvent.CHECK_SUCCESS, reason=f"Fail count {self.state.fail_count} waiting for next strategy trigger")

    def _notify_status(self, healthy, message):
        if self.on_status_change:
            try:
                self.on_status_change(healthy, message)
            except Exception:
                pass

    def get_status(self):
        from engine_params import EngineParams
        cfg = load_config()
        params = EngineParams.from_dict(cfg)
        active_preset = params.zapret2_preset if params.engine_mode == "nfqws2" else params.preset
        fsm_state = self.fsm.state.value if hasattr(self, "fsm") else HealerFSMState.IDLE.value
        return {
            "running": self.running,
            "healthy": self.state.is_healthy,
            "fail_count": self.state.fail_count,
            "dns_fail_count": getattr(self.state, "dns_fail_count", 0),
            "last_check": self.state.last_check,
            "last_restart": self.state.last_restart,
            "current_preset": active_preset,
            "fsm_state": fsm_state,
            "consecutive_failures": getattr(self, "consecutive_restart_failures", 0),
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
