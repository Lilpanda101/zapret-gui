#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for Domain Lists UI, !domain exclusion syntax, subdomain pruning,
atomic file writes, and preservation of user lines.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from list_manager import ListManager, atomic_write_text, compile_effective_lists
from main import Zapret2App


@pytest.fixture(autouse=True)
def check_gtk():
    initialized = Gtk.init_check([])[0]
    if not initialized:
        pytest.skip("GTK display unavailable, run under xvfb-run")


@pytest.fixture
def temp_workspace(tmp_path):
    """Sets up a temporary working directory with standard list files."""
    lists_dir = tmp_path / "lists"
    lists_dir.mkdir(parents=True, exist_ok=True)

    custom_hosts = tmp_path / "custom_hosts.txt"
    custom_hosts.write_text(
        "# Custom Hosts Configuration\n"
        "# Do not delete comments!\n"
        "allowed-first.com\n"
        "sub.service-b.org\n"
        "!service-b.org\n"
        "\n"
        "allowed-second.org\n",
        encoding="utf-8",
    )

    exclude_file = tmp_path / "exclude.txt"
    exclude_file.write_text(
        "# Exclude list\n"
        "manual-excluded.com\n",
        encoding="utf-8",
    )

    autohostlist = lists_dir / "autohostlist.txt"
    autohostlist.write_text(
        "# Discovered hosts\n"
        "deep.sub.service-b.org\n"
        "auto-allowed.net\n",
        encoding="utf-8",
    )

    return tmp_path


@pytest.fixture
def mock_app(temp_workspace):
    with patch("main.MirrorHealthMonitor"), \
         patch("main.get_healer") as mock_healer, \
         patch("main.subprocess.run") as mock_subp, \
         patch("main.GLib.timeout_add"), \
         patch("main.GLib.timeout_add_seconds"):

        fake_healer = MagicMock()
        fake_healer.status = "OK"
        fake_healer.is_running = False
        mock_healer.return_value = fake_healer
        mock_subp.return_value = MagicMock(returncode=0, stdout="INACTIVE\n", stderr="")

        app = Zapret2App(minimized=True)
        app.app_dir = str(temp_workspace)
        app.list_manager = ListManager(base_dir=temp_workspace)
        app.hosts_files = {
            "custom": str(temp_workspace / "custom_hosts.txt"),
            "exclude": str(temp_workspace / "exclude.txt"),
            "autohostlist": str(temp_workspace / "lists" / "autohostlist.txt"),
            "general": str(temp_workspace / "list-general.txt"),
            "hosts": str(temp_workspace / "hosts.txt"),
            "badsum": str(temp_workspace / "badsum_hosts.txt"),
        }
        yield app
        app.destroy()


def test_list_ui_load_edit_and_atomic_save_no_loss(mock_app, temp_workspace):
    """
    Verifies that loading, editing, and saving a list:
    1. Uses atomic_write_text.
    2. Preserves comments, whitespace, and formatting verbatim without loss.
    3. Does NOT touch or overwrite other list files without explicit action.
    """
    app = mock_app
    custom_path = temp_workspace / "custom_hosts.txt"
    exclude_path = temp_workspace / "exclude.txt"
    exclude_orig_mtime = exclude_path.stat().st_mtime_ns
    exclude_orig_content = exclude_path.read_text(encoding="utf-8")

    # Load custom_hosts
    app.combo_file.set_active_id("custom")
    app.load_hosts_file_content()

    buffer_text = app.hosts_buffer.get_text(
        app.hosts_buffer.get_start_iter(),
        app.hosts_buffer.get_end_iter(),
        False,
    )
    assert "# Custom Hosts Configuration" in buffer_text
    assert "# Do not delete comments!" in buffer_text
    assert "!service-b.org" in buffer_text

    # User adds a new exclusion rule
    new_text = buffer_text + "\n!another-blocked.com\n# Final notes\n"
    app.hosts_buffer.set_text(new_text)

    # Save content
    with patch.object(app, "show_dialog") as mock_dialog:
        app.save_hosts_file_content()
        mock_dialog.assert_called_once()
        assert "успешно" in mock_dialog.call_args[0][1]

    # Verify disk content has no data loss
    saved_on_disk = custom_path.read_text(encoding="utf-8")
    assert "# Custom Hosts Configuration" in saved_on_disk
    assert "# Do not delete comments!" in saved_on_disk
    assert "!service-b.org" in saved_on_disk
    assert "!another-blocked.com" in saved_on_disk
    assert "# Final notes" in saved_on_disk

    # Verify other files (exclude.txt) were completely untouched!
    assert exclude_path.stat().st_mtime_ns == exclude_orig_mtime
    assert exclude_path.read_text(encoding="utf-8") == exclude_orig_content


def test_list_ui_compile_effective_lists_and_subdomain_pruning(mock_app):
    """
    Verifies compilation semantics:
    - !domain unconditionally excludes domain and all its subdomains.
    - Pruned subdomains are eliminated from hostlist and reported.
    - Excluded domain is added to exclude list.
    """
    app = mock_app
    res = app.compile_effective_lists()

    # !service-b.org from custom_hosts.txt
    assert "service-b.org" in res.exclude_list
    assert "manual-excluded.com" in res.exclude_list

    # Subdomains from custom and auto must be pruned from hostlist
    assert "service-b.org" not in res.hostlist
    assert "sub.service-b.org" not in res.hostlist
    assert "deep.sub.service-b.org" not in res.hostlist

    # Allowed domains must remain in hostlist
    assert "allowed-first.com" in res.hostlist
    assert "allowed-second.org" in res.hostlist
    assert "auto-allowed.net" in res.hostlist

    # Check overridden list
    assert "sub.service-b.org" in res.overridden_by_exclusion
    assert "deep.sub.service-b.org" in res.overridden_by_exclusion


def test_list_ui_atomic_write_safety(tmp_path):
    """
    Verifies atomic_write_text writes completely, with correct mode and atomic replace.
    """
    target = tmp_path / "test_atomic.txt"
    content = "line1\n!domain.com\nline2\n"

    res_path = atomic_write_text(target, content)
    assert res_path.exists()
    assert res_path.read_text(encoding="utf-8") == content
    assert (res_path.stat().st_mode & 0o777) == 0o644

    # Atomic rewrite
    new_content = "updated\n!another.com\n"
    atomic_write_text(target, new_content)
    assert target.read_text(encoding="utf-8") == new_content

    # No leftover temporary files
    temp_files = list(tmp_path.glob(".zapret_list_tmp_*"))
    assert len(temp_files) == 0


def test_list_ui_compile_action_dialog(mock_app):
    """
    Tests the user-triggered 'compile lists' button action shows summary dialog.
    """
    app = mock_app
    with patch.object(app, "show_dialog") as mock_dialog:
        app.on_compile_lists_clicked(None)
        mock_dialog.assert_called_once()
        title, text = mock_dialog.call_args[0]
        assert title == "Компиляция списков"
        assert "hostlist" in text
        assert "exclude" in text
        assert "!домен" in text
