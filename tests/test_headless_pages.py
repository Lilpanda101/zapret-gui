import pytest
from unittest.mock import patch, MagicMock
import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from main import Zapret2App


@pytest.fixture(autouse=True)
def check_gtk():
    initialized = Gtk.init_check([])[0]
    if not initialized:
        pytest.skip("GTK display unavailable, run under xvfb-run")


@patch("main.MirrorHealthMonitor")
@patch("main.get_healer")
@patch("main.subprocess.run")
def test_all_pages_instantiation(mock_subp, mock_get_healer, mock_mirror, tmp_path):
    mock_subp.return_value = MagicMock(returncode=0, stdout="INACTIVE\n", stderr="")
    fake_healer = MagicMock()
    fake_healer.status = "OK"
    mock_get_healer.return_value = fake_healer

    app = Zapret2App(minimized=True)

    expected_pages = [
        "dashboard",
        "presets",
        "profiles",
        "zapret2",
        "dpi_mode",
        "monitor",
        "dns",
        "hosts",
        "updates",
        "blockcheck",
        "logs",
        "settings",
    ]

    for page_name in expected_pages:
        child = app.stack.get_child_by_name(page_name)
        assert child is not None, f"Page {page_name} was not created in the stack"
        assert isinstance(child, Gtk.Widget)

    # Clean up mirror monitor & healer
    if hasattr(app, "mirror_monitor"):
        try:
            app.mirror_monitor.stop()
        except Exception:
            pass
    app.destroy()
