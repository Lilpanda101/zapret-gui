#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for healer.py explicit Finite State Machine (FSM).
Covers:
- All FSM states (IDLE, CHECKING, RESTARTING, BACKOFF, DEGRADED, STOPPED)
- All valid and invalid transitions with reasons and logging
- Exponential backoff with ceiling and absence of busy-loops
- Immediate interruptible stop via threading.Event
- Preservation of restart_engine and get_status contracts
"""

import time
import threading
from unittest.mock import MagicMock, patch
import pytest

import healer
from healer import (
    HealerFSM,
    HealerFSMState,
    HealerEvent,
    InvalidTransitionError,
    calculate_backoff,
    AutoHealer,
    BACKOFF_BASE,
    BACKOFF_MAX,
    BACKOFF_FACTOR,
)


class TestHealerFSMTransitions:
    """Проверка всех состояний и переходов FSM."""

    def test_initial_state_and_start(self):
        fsm = HealerFSM()
        assert fsm.state == HealerFSMState.STOPPED
        assert fsm.can_transition(HealerEvent.START)
        new_state = fsm.transition(HealerEvent.START, reason="Service startup")
        assert new_state == HealerFSMState.IDLE
        assert fsm.state == HealerFSMState.IDLE

    def test_idle_to_checking_and_success(self):
        fsm = HealerFSM(initial_state=HealerFSMState.IDLE)
        assert fsm.can_transition(HealerEvent.CHECK)
        fsm.transition(HealerEvent.CHECK, reason="Periodic tick")
        assert fsm.state == HealerFSMState.CHECKING

        assert fsm.can_transition(HealerEvent.CHECK_SUCCESS)
        fsm.transition(HealerEvent.CHECK_SUCCESS, reason="All targets OK")
        assert fsm.state == HealerFSMState.IDLE

    def test_checking_to_restarting_and_recovery(self):
        fsm = HealerFSM(initial_state=HealerFSMState.CHECKING)
        assert fsm.can_transition(HealerEvent.CHECK_FAIL)
        fsm.transition(HealerEvent.CHECK_FAIL, reason="DPI failure threshold reached")
        assert fsm.state == HealerFSMState.RESTARTING

        assert fsm.can_transition(HealerEvent.RESTART_SUCCESS)
        fsm.transition(HealerEvent.RESTART_SUCCESS, reason="Engine restarted")
        assert fsm.state == HealerFSMState.IDLE

    def test_restarting_to_backoff_and_expiry(self):
        fsm = HealerFSM(initial_state=HealerFSMState.RESTARTING)
        assert fsm.can_transition(HealerEvent.RESTART_FAIL)
        fsm.transition(HealerEvent.RESTART_FAIL, reason="Engine failed to start")
        assert fsm.state == HealerFSMState.BACKOFF

        assert fsm.can_transition(HealerEvent.BACKOFF_EXPIRED)
        fsm.transition(HealerEvent.BACKOFF_EXPIRED, reason="Backoff cooldown finished")
        assert fsm.state == HealerFSMState.IDLE

    def test_attempts_exhausted_leads_to_degraded(self):
        # Из RESTARTING при исчерпании попыток
        fsm1 = HealerFSM(initial_state=HealerFSMState.RESTARTING)
        assert fsm1.can_transition(HealerEvent.ATTEMPTS_EXHAUSTED)
        fsm1.transition(HealerEvent.ATTEMPTS_EXHAUSTED, reason="Max retries reached")
        assert fsm1.state == HealerFSMState.DEGRADED

        # Из CHECKING при rate limit
        fsm2 = HealerFSM(initial_state=HealerFSMState.CHECKING)
        assert fsm2.can_transition(HealerEvent.ATTEMPTS_EXHAUSTED)
        fsm2.transition(HealerEvent.ATTEMPTS_EXHAUSTED, reason="Hourly limit reached")
        assert fsm2.state == HealerFSMState.DEGRADED

        # Из BACKOFF при исчерпании попыток
        fsm3 = HealerFSM(initial_state=HealerFSMState.BACKOFF)
        assert fsm3.can_transition(HealerEvent.ATTEMPTS_EXHAUSTED)
        fsm3.transition(HealerEvent.ATTEMPTS_EXHAUSTED, reason="Attempts limit reached during backoff")
        assert fsm3.state == HealerFSMState.DEGRADED

    def test_degraded_recovery_lifecycle(self):
        fsm = HealerFSM(initial_state=HealerFSMState.DEGRADED)
        # Из DEGRADED можно проверить статус
        assert fsm.can_transition(HealerEvent.CHECK)
        fsm.transition(HealerEvent.CHECK, reason="Probing degraded service")
        assert fsm.state == HealerFSMState.CHECKING

        # При успехе возвращается в IDLE
        fsm.transition(HealerEvent.CHECK_SUCCESS, reason="Self-healed")
        assert fsm.state == HealerFSMState.IDLE

    def test_stop_transitions_from_all_states(self):
        states = [
            HealerFSMState.STOPPED,
            HealerFSMState.IDLE,
            HealerFSMState.CHECKING,
            HealerFSMState.RESTARTING,
            HealerFSMState.BACKOFF,
            HealerFSMState.DEGRADED,
        ]
        for st in states:
            fsm = HealerFSM(initial_state=st)
            assert fsm.can_transition(HealerEvent.STOP), f"State {st} must accept STOP"
            fsm.transition(HealerEvent.STOP, reason=f"Stopping from {st}")
            assert fsm.state == HealerFSMState.STOPPED

    def test_invalid_transitions_raise_error(self):
        fsm = HealerFSM(initial_state=HealerFSMState.IDLE)
        # В IDLE нельзя сразу сказать RESTART_SUCCESS или BACKOFF_EXPIRED
        with pytest.raises(InvalidTransitionError) as exc_info:
            fsm.transition(HealerEvent.RESTART_SUCCESS, reason="Illegal move")
        assert exc_info.value.from_state == HealerFSMState.IDLE
        assert exc_info.value.event == HealerEvent.RESTART_SUCCESS

        # В STOPPED нельзя сделать CHECK_FAIL
        fsm_stopped = HealerFSM(initial_state=HealerFSMState.STOPPED)
        with pytest.raises(InvalidTransitionError):
            fsm_stopped.transition(HealerEvent.CHECK_FAIL, reason="Illegal move")

    def test_transition_logging_and_callback(self):
        captured_callbacks = []

        def callback(old, new, event, reason):
            captured_callbacks.append((old, new, event, reason))

        fsm = HealerFSM(initial_state=HealerFSMState.IDLE, on_transition=callback)
        fsm.transition(HealerEvent.CHECK, reason="Starting check cycle")
        assert len(captured_callbacks) == 1
        assert captured_callbacks[0] == (
            HealerFSMState.IDLE,
            HealerFSMState.CHECKING,
            HealerEvent.CHECK,
            "Starting check cycle",
        )
        assert len(fsm.history) == 1
        assert fsm.history[0][4] == "Starting check cycle"


class TestHealerBackoff:
    """Проверка математики экспоненциального backoff и потолка."""

    def test_exponential_backoff_values(self):
        assert calculate_backoff(0) == 0.0
        assert calculate_backoff(-1) == 0.0

        # По умолчанию: base=5.0, factor=2.0
        assert calculate_backoff(1) == 5.0
        assert calculate_backoff(2) == 10.0
        assert calculate_backoff(3) == 20.0
        assert calculate_backoff(4) == 40.0
        assert calculate_backoff(5) == 80.0
        assert calculate_backoff(6) == 160.0

    def test_backoff_ceiling_cap(self):
        # При потолке 300.0s:
        # attempt 7: 5 * 2^6 = 320 -> должно быть 300.0
        assert calculate_backoff(7) == 300.0
        assert calculate_backoff(10) == 300.0
        assert calculate_backoff(100) == 300.0

    def test_custom_backoff_parameters(self):
        delay = calculate_backoff(attempt=3, base=1.0, factor=3.0, max_ceiling=50.0)
        # 1.0 * 3^(3-1) = 9.0
        assert delay == 9.0

        capped = calculate_backoff(attempt=10, base=1.0, factor=3.0, max_ceiling=50.0)
        assert capped == 50.0


class TestHealerStopAndNoBusyLoop:
    """Проверка отсутствия busy-loop и немедленной остановки по Event."""

    def test_no_busy_loop_during_backoff_uses_event_wait(self):
        healer_inst = AutoHealer()
        healer_inst.fsm.state = HealerFSMState.BACKOFF
        healer_inst.consecutive_restart_failures = 2  # 10s backoff
        healer_inst.backoff_base = 10.0

        waited_timeouts = []
        original_wait = healer_inst._stop_event.wait

        def spy_wait(timeout=None):
            waited_timeouts.append(timeout)
            # Немедленно сигнализируем остановку, чтобы выйти из одного прогона _loop
            healer_inst._stop_event.set()
            return True

        healer_inst._stop_event.wait = spy_wait
        healer_inst._loop()

        # Должен быть вызван ровно один раз с вычисленным timeout backoff (не в цикле polling)
        assert len(waited_timeouts) == 1
        assert waited_timeouts[0] == 20.0  # 10 * 2^(2-1) = 20.0

    def test_immediate_stop_terminates_thread(self):
        healer_inst = AutoHealer()
        healer_inst.check_interval = 60  # Большой интервал

        t0 = time.time()
        healer_inst.start()
        assert healer_inst.running is True
        assert healer_inst.fsm.state in (HealerFSMState.IDLE, HealerFSMState.CHECKING)

        # Вызов stop() должен разбудить поток через Event и завершиться за долю секунды
        healer_inst.stop()
        duration = time.time() - t0

        assert healer_inst.running is False
        assert healer_inst.fsm.state == HealerFSMState.STOPPED
        assert duration < 1.0  # Не ждал 60 секунд!
        assert not healer_inst.thread.is_alive()


class TestRestartEngineContract:
    """Проверка сохранения контракта вызова restart_engine."""

    def test_restart_engine_contract_with_nfqws2(self, monkeypatch):
        captured_cmds = []

        def fake_run(*args):
            captured_cmds.append(args)
            return True, "ACTIVE", ""

        monkeypatch.setattr(healer, "run_engine_cmd", fake_run)

        config = {
            "preset": "alt_split",
            "iface": "enp3s0",
            "dns": "cloudflare",
            "ai_hosts": True,
            "enable_quic": False,
            "enable_discord_voice": True,
            "conntrack_limit": 16,
            "hostlist_mode": "all_except_exclude",
            "engine_mode": "nfqws2",
            "custom_params": "",
            "zapret2_preset": "Default (circular)",
            "enable_youtube": True,
            "enable_discord_tcp": False,
            "enable_general_https": True,
        }

        ok = healer.restart_engine(config)
        assert ok is True
        assert len(captured_cmds) == 1
        args = captured_cmds[0]

        # Контракт to_argv("start") из EngineParams
        assert args[0] == "start"
        assert args[1] == "alt_split"
        assert args[2] == "enp3s0"
        assert args[3] == "cloudflare"
        assert args[4] == "1"  # ai_hosts
        assert args[5] == "0"  # enable_quic
        assert args[6] == "1"  # enable_discord_voice
        assert args[7] == "16"  # conntrack_limit
        assert args[8] == "all_except_exclude"
        assert args[9] == "nfqws2"
        assert args[11] == "Default (circular)"

    def test_restart_engine_failure_returns_false(self, monkeypatch):
        monkeypatch.setattr(healer, "run_engine_cmd", lambda *args: (False, "", "Permission denied"))
        config = {"engine_mode": "nfqws2"}
        assert healer.restart_engine(config) is False


class TestAutoHealerFSMIntegration:
    """Интеграционные тесты работы FSM внутри AutoHealer."""

    def test_status_reports_fsm_state(self, monkeypatch):
        monkeypatch.setattr(healer, "load_config", lambda: {"engine_mode": "nfqws2", "zapret2_preset": "general ALT"})
        h = AutoHealer()
        status = h.get_status()
        assert status["running"] is False
        assert status["fsm_state"] == HealerFSMState.STOPPED.value
        assert status["consecutive_failures"] == 0

        h.start()
        status_running = h.get_status()
        assert status_running["running"] is True
        assert status_running["fsm_state"] in (HealerFSMState.IDLE.value, HealerFSMState.CHECKING.value)
        h.stop()

    def test_consecutive_failures_lead_to_degraded(self, monkeypatch):
        h = AutoHealer()
        h.fsm.state = HealerFSMState.IDLE

        # Эмулируем сбой движка
        monkeypatch.setattr(healer, "load_config", lambda: {"engine_mode": "nfqws2", "healer_enabled": True})
        monkeypatch.setattr(healer, "get_engine_status", lambda: (False, "NFQWS_ONLY"))
        monkeypatch.setattr(healer, "restart_engine", lambda cfg: False)  # Рестарт всегда падает

        # Запускаем проверку до исчерпания попыток (MAX_CONSECUTIVE_FAILURES = 5)
        for i in range(1, healer.MAX_CONSECUTIVE_FAILURES):
            h._check_and_heal()
            assert h.fsm.state == HealerFSMState.BACKOFF
            assert h.consecutive_restart_failures == i
            # Симулируем истечение backoff
            h.fsm.transition(HealerEvent.BACKOFF_EXPIRED, reason="Cooldown expired")

        # 5-я попытка приводит к DEGRADED
        h._check_and_heal()
        assert h.fsm.state == HealerFSMState.DEGRADED
        assert h.consecutive_restart_failures == healer.MAX_CONSECUTIVE_FAILURES

    def test_rate_limit_leads_to_degraded(self, monkeypatch):
        h = AutoHealer()
        h.fsm.state = HealerFSMState.IDLE

        monkeypatch.setattr(healer, "load_config", lambda: {"engine_mode": "nfqws2", "healer_enabled": True})
        monkeypatch.setattr(healer, "get_engine_status", lambda: (True, "ACTIVE"))
        # Все таргеты падают
        monkeypatch.setattr(healer, "check_all_targets", lambda: (
            False,
            {
                "google": {"ok": False, "error": "HTTP 500"},
                "youtube": {"ok": False, "error": "HTTP 500"},
                "cloudflare": {"ok": True, "error": None},
            }
        ))
        # Эмулируем исчерпание лимита рестартов
        h.state.fail_count = healer.FAIL_THRESHOLD
        monkeypatch.setattr(h.state, "can_restart", lambda: (False, "Rate limit: max restarts per hour reached"))

        h._check_and_heal()
        assert h.fsm.state == HealerFSMState.DEGRADED
