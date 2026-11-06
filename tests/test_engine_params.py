import logging
import pytest
from engine_params import EngineParams, _as_bool, _as_int


def test_as_bool_strict():
    assert _as_bool("0") is False
    assert _as_bool("false") is False
    assert _as_bool("False") is False
    assert _as_bool("no") is False
    assert _as_bool("off") is False
    assert _as_bool(0) is False
    assert _as_bool(False) is False

    assert _as_bool("1") is True
    assert _as_bool("true") is True
    assert _as_bool("True") is True
    assert _as_bool("yes") is True
    assert _as_bool(1) is True
    assert _as_bool(True) is True

    # Fallback to default
    assert _as_bool(None, default=True) is True
    assert _as_bool(None, default=False) is False
    assert _as_bool("gibberish", default=True) is True
    assert _as_bool("gibberish", default=False) is False


def test_as_int_clamping(caplog):
    with caplog.at_level(logging.WARNING):
        # Value exceeds max 128 -> clamp to 128 (not reset to 12!)
        assert _as_int(256, default=12, min_val=1, max_val=128) == 128
        assert "clamping to 128" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        # Value below min 1 -> clamp to 1
        assert _as_int(-5, default=12, min_val=1, max_val=128) == 1
        assert "clamping to 1" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        # Invalid string -> fallback to default
        assert _as_int("not_a_number", default=12, min_val=1, max_val=128) == 12
        assert "Invalid int parameter" in caplog.text


def test_engine_params_from_dict_strict_bool_and_clamping():
    dirty_dict = {
        "enable_quic": "0",
        "enable_discord_voice": "false",
        "enable_youtube": 0,
        "enable_ai_hosts": "no",
        "conntrack_limit": "256",
    }
    p = EngineParams.from_dict(dirty_dict)
    assert p.enable_quic is False
    assert p.enable_discord_voice is False
    assert p.enable_youtube is False
    assert p.enable_ai_hosts is False
    assert p.conntrack_limit == 128  # Clamped, not reset to 12


def test_engine_params_direct_instantiation_clamping():
    p = EngineParams(conntrack_limit=500)
    assert p.conntrack_limit == 128

    p_low = EngineParams(conntrack_limit=0)
    assert p_low.conntrack_limit == 1
