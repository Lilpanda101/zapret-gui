import os
import pytest
from unittest.mock import MagicMock
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk

from config_manager import (
    DEFAULT_CONFIG,
    should_show_onboarding,
    mark_onboarding_completed,
    load_config_from_file,
)
from onboarding import OnboardingDialog, show_onboarding


@pytest.fixture(autouse=True)
def check_gtk():
    """Ensure GTK display environment is available or skip GUI-reliant tests."""
    initialized = Gtk.init_check([])[0]
    if not initialized:
        pytest.skip("GTK display unavailable, run under xvfb-run or X11/Wayland")


def test_should_show_onboarding_flags():
    """Verify boolean decision logic for showing onboarding tour."""
    # New empty config or default config without completion
    assert should_show_onboarding({}) is True
    assert should_show_onboarding(DEFAULT_CONFIG) is True
    assert should_show_onboarding({"onboarding_completed": False}) is True

    # User already completed onboarding
    assert should_show_onboarding({"onboarding_completed": True}) is False

    # Invalid input fallback safely to showing onboarding
    assert should_show_onboarding(None) is True
    assert should_show_onboarding("invalid") is True


def test_mark_onboarding_completed_file_and_memory(tmp_path):
    """Test updating onboarding completion flag in memory and JSON config file."""
    cfg_file = tmp_path / "test_config.json"
    mem_cfg = {"onboarding_completed": False, "preset": "general"}

    res = mark_onboarding_completed(str(cfg_file), in_memory_config=mem_cfg)
    assert res is True
    assert mem_cfg["onboarding_completed"] is True

    # Verify persisted JSON
    loaded = load_config_from_file(str(cfg_file))
    assert loaded["onboarding_completed"] is True
    assert should_show_onboarding(loaded) is False


def test_dialog_initialization():
    """Verify OnboardingDialog builds UI structure, step stack, and controls."""
    config = {"preset": "general"}
    dialog = OnboardingDialog(parent=None, config=config)

    assert dialog.current_step == 0
    assert dialog.TOTAL_STEPS == 3
    assert dialog.lbl_title is not None
    assert dialog.lbl_step_counter.get_text() == "Шаг 1 из 3"
    assert len(dialog.step_labels) == 3

    # Check child steps exist in stack
    for step_idx in range(3):
        child = dialog.stack.get_child_by_name(f"step_{step_idx}")
        assert child is not None
        assert isinstance(child, Gtk.Widget)

    # Initial button states
    assert dialog.btn_back.get_label() == "Пропустить"
    assert dialog.btn_next.get_label() == "Далее →"

    dialog.destroy()


def test_dialog_step_navigation():
    """Verify step-by-step navigation forward and backward."""
    config = {"preset": "general"}
    dialog = OnboardingDialog(parent=None, config=config)

    # Forward to step 2
    dialog.next_step()
    assert dialog.current_step == 1
    assert dialog.stack.get_visible_child_name() == "step_1"
    assert dialog.btn_back.get_label() == "← Назад"
    assert dialog.lbl_step_counter.get_text() == "Шаг 2 из 3"

    # Forward to step 3 (last step)
    dialog.next_step()
    assert dialog.current_step == 2
    assert dialog.stack.get_visible_child_name() == "step_2"
    assert dialog.btn_next.get_label() == "✨ Начать работу"
    assert dialog.lbl_step_counter.get_text() == "Шаг 3 из 3"

    # Backward to step 2
    dialog.prev_step()
    assert dialog.current_step == 1
    assert dialog.stack.get_visible_child_name() == "step_1"
    assert dialog.btn_next.get_label() == "Далее →"

    dialog.destroy()


def test_dialog_finish_callback(tmp_path):
    """Verify finishing tour triggers callback and marks onboarding complete."""
    cfg_file = tmp_path / "onboard_finish.json"
    config = {"preset": "general"}
    cb_mock = MagicMock()

    dialog = OnboardingDialog(
        parent=None,
        config=config,
        config_file=str(cfg_file),
        on_complete=cb_mock,
    )

    # Navigate to end and finish
    dialog.next_step()
    dialog.next_step()
    dialog.next_step()  # Step 3 -> finish_tour

    assert cb_mock.call_count == 1
    assert config.get("onboarding_completed") is True

    # Check config file
    loaded = load_config_from_file(str(cfg_file))
    assert loaded["onboarding_completed"] is True


def test_dialog_skip_callback(tmp_path):
    """Verify skipping tour triggers callback and saves completed status."""
    cfg_file = tmp_path / "onboard_skip.json"
    config = {"preset": "general"}
    cb_mock = MagicMock()

    dialog = OnboardingDialog(
        parent=None,
        config=config,
        config_file=str(cfg_file),
        on_complete=cb_mock,
    )

    # On step 0, prev_step or skip_tour skips
    dialog.skip_tour()

    assert cb_mock.call_count == 1
    assert config.get("onboarding_completed") is True

    loaded = load_config_from_file(str(cfg_file))
    assert loaded["onboarding_completed"] is True


def test_dialog_keyboard_shortcuts():
    """Verify Escape skips tour and Return advances."""
    config = {"preset": "general"}
    dialog = OnboardingDialog(parent=None, config=config)

    # Simulate Return key press -> step advances from 0 to 1
    event_enter = Gdk.EventKey()
    event_enter.keyval = Gdk.KEY_Return
    res_enter = dialog._on_key_press(dialog, event_enter)
    assert res_enter is True
    assert dialog.current_step == 1

    # Simulate Escape key press -> skips and completes
    cb_mock = MagicMock()
    dialog.on_complete = cb_mock
    event_esc = Gdk.EventKey()
    event_esc.keyval = Gdk.KEY_Escape
    res_esc = dialog._on_key_press(dialog, event_esc)
    assert res_esc is True
    assert cb_mock.call_count == 1


def test_show_onboarding_helper(tmp_path):
    """Verify show_onboarding helper creates, displays, and returns dialog."""
    cfg_file = tmp_path / "helper_cfg.json"
    config = {"preset": "general"}
    cb = MagicMock()

    dialog = show_onboarding(
        parent_window=None,
        config=config,
        config_file=str(cfg_file),
        on_finish=cb,
    )
    assert dialog is not None
    assert isinstance(dialog, OnboardingDialog)
    assert dialog.get_visible() is True

    dialog.finish_tour()
    assert cb.call_count == 1
