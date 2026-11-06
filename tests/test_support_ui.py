#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration and unit tests for Log Analyzer and Support Bundle UI integration."""

import json
from pathlib import Path
import tarfile
from unittest.mock import MagicMock, patch

import gi
import pytest

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk

from log_analyzer import AnalysisReport, LogIncident
from main import Zapret2App

pytestmark = [pytest.mark.filterwarnings("ignore::DeprecationWarning")]


@pytest.fixture(autouse=True)
def check_gtk():
    initialized = Gtk.init_check([])[0]
    if not initialized:
        pytest.skip("GTK display unavailable, run under xvfb-run")


@pytest.fixture
def app_instance(tmp_path):
    fake_log = tmp_path / "test-zapret.log"
    fake_log.write_text("2026-11-07 00:00:00 [info] service started\n", encoding="utf-8")

    fake_cfg = tmp_path / "test-config.json"
    fake_cfg.write_text(json.dumps({"mode": "zapret2", "preset": "general"}), encoding="utf-8")

    with patch("main.MirrorHealthMonitor"), patch("main.get_healer") as mock_healer, patch("main.subprocess.run") as mock_subp:
        mock_subp.return_value = MagicMock(returncode=0, stdout="INACTIVE\n", stderr="")
        healer_mock = MagicMock()
        healer_mock.status = "OK"
        mock_healer.return_value = healer_mock

        app = Zapret2App(minimized=True)
        app.custom_log_path = str(fake_log)
        app.custom_config_path = str(fake_cfg)

        yield app

        if hasattr(app, "mirror_monitor"):
            try:
                app.mirror_monitor.stop()
            except Exception:
                pass
        app.destroy()


def _drain_glib(max_iterations: int = 100):
    iters = 0
    ctx = GLib.main_context_default()
    while ctx.pending() and iters < max_iterations:
        ctx.iteration(False)
        iters += 1


def test_logs_page_controls_present(app_instance):
    """Verify that all required diagnostic & support widgets are constructed on logs page."""
    app = app_instance

    assert hasattr(app, "btn_refresh_log"), "Missing btn_refresh_log"
    assert isinstance(app.btn_refresh_log, Gtk.Button)

    assert hasattr(app, "btn_analyze_log"), "Missing btn_analyze_log"
    assert isinstance(app.btn_analyze_log, Gtk.Button)

    assert hasattr(app, "btn_support_bundle"), "Missing btn_support_bundle"
    assert isinstance(app.btn_support_bundle, Gtk.Button)

    assert hasattr(app, "lbl_support_status"), "Missing lbl_support_status"
    assert isinstance(app.lbl_support_status, Gtk.Label)

    assert hasattr(app, "analysis_summary_label"), "Missing analysis_summary_label"
    assert isinstance(app.analysis_summary_label, Gtk.Label)

    assert hasattr(app, "analysis_incidents_box"), "Missing analysis_incidents_box"
    assert isinstance(app.analysis_incidents_box, Gtk.Box)


def test_analyze_log_with_fake_analyzer(app_instance, tmp_path):
    """Verify background execution of analyze_log_file, UI updates, and badge-bad for critical."""
    app = app_instance
    test_log = tmp_path / "sample.log"
    test_log.write_text("conntrack error\n", encoding="utf-8")
    app.custom_log_path = str(test_log)

    fake_report = AnalysisReport(
        source=str(test_log),
        total_lines=84,
        incidents=[
            LogIncident(
                category="conntrack",
                severity="CRITICAL",
                title="Переполнение conntrack",
                description="Таблица nf_conntrack переполнена",
                recommendation="Увеличьте sysctl net.netfilter.nf_conntrack_max",
                count=5,
            ),
            LogIncident(
                category="dns",
                severity="WARNING",
                title="Медленный DNS",
                description="Ответ DNS занял более 1200 ms",
                recommendation="Переключите DoT провайдера на Cloudflare",
                count=2,
            ),
        ],
    )

    with patch("main.analyze_log_file", return_value=fake_report) as mock_analyze:
        app.on_analyze_log_clicked()

        if hasattr(app, "_analyze_thread") and app._analyze_thread:
            app._analyze_thread.join(timeout=2.0)
        _drain_glib()

        mock_analyze.assert_called_once_with(str(test_log))

    assert app.btn_analyze_log.get_sensitive() is True
    assert app.btn_support_bundle.get_sensitive() is True

    summary_text = app.analysis_summary_label.get_text()
    assert str(test_log) in summary_text
    assert "84" in summary_text

    incidents = app.analysis_incidents_box.get_children()
    assert len(incidents) == 2

    # Check first incident: CRITICAL with badge-bad
    row0 = incidents[0]
    # Check that it contains badge-bad, title, description, recommendation, count
    row0_text = []

    def _collect_labels_and_classes(widget):
        classes = widget.get_style_context().list_classes()
        if isinstance(widget, Gtk.Label):
            row0_text.append((widget.get_text(), classes))
        if isinstance(widget, Gtk.Container):
            for ch in widget.get_children():
                _collect_labels_and_classes(ch)

    _collect_labels_and_classes(row0)

    has_critical_badge = any(
        "CRITICAL" in txt and "badge-bad" in cls for txt, cls in row0_text
    )
    assert has_critical_badge, f"CRITICAL incident must be styled with badge-bad: {row0_text}"

    has_title = any("Переполнение conntrack" in txt for txt, _ in row0_text)
    assert has_title

    has_desc = any("Таблица nf_conntrack переполнена" in txt for txt, _ in row0_text)
    assert has_desc

    has_rec = any("net.netfilter.nf_conntrack_max" in txt for txt, _ in row0_text)
    assert has_rec

    has_count = any("5" in txt for txt, _ in row0_text)
    assert has_count


def test_analyze_log_clean_report(app_instance):
    """Verify clean log report displays positive status and OK badge."""
    app = app_instance

    clean_report = AnalysisReport(
        source="/tmp/clean.log",
        total_lines=15,
        incidents=[],
    )

    with patch("main.analyze_log_file", return_value=clean_report):
        app.on_analyze_log_clicked()
        if hasattr(app, "_analyze_thread") and app._analyze_thread:
            app._analyze_thread.join(timeout=2.0)
        _drain_glib()

    children = app.analysis_incidents_box.get_children()
    assert len(children) == 1

    box = children[0]
    labels = []
    classes = []

    def _collect(w):
        classes.extend(w.get_style_context().list_classes())
        if isinstance(w, Gtk.Label):
            labels.append(w.get_text())
        if isinstance(w, Gtk.Container):
            for c in w.get_children():
                _collect(c)

    _collect(box)
    assert "badge-ok" in classes
    assert any("не обнаружено" in lbl for lbl in labels)


def test_analyze_log_error_handling(app_instance):
    """Verify analyzer exceptions are handled gracefully and surfaced to user."""
    app = app_instance

    with patch("main.analyze_log_file", side_effect=PermissionError("Permission denied: log file")):
        app.on_analyze_log_clicked()
        if hasattr(app, "_analyze_thread") and app._analyze_thread:
            app._analyze_thread.join(timeout=2.0)
        _drain_glib()

    assert app.btn_analyze_log.get_sensitive() is True
    summary_text = app.analysis_summary_label.get_text()
    assert "Ошибка анализа" in summary_text
    assert "Permission denied" in summary_text


def test_support_bundle_button_flow_and_args(app_instance, tmp_path):
    """Verify support bundle creation with proper arguments and UI status update."""
    app = app_instance
    out_dir = tmp_path / "export_bundles"
    out_dir.mkdir(parents=True, exist_ok=True)

    expected_archive = out_dir / "support_bundle_20261107_010203.tar.gz"

    with patch.object(app, "confirm_support_bundle_sanitization", return_value=True) as mock_confirm, \
         patch.object(app, "choose_support_bundle_directory", return_value=str(out_dir)) as mock_dir, \
         patch.object(app, "show_dialog") as mock_dialog, \
         patch("main.create_support_bundle", return_value=expected_archive) as mock_create:

        app.on_support_bundle_clicked()

        if hasattr(app, "_bundle_thread") and app._bundle_thread:
            app._bundle_thread.join(timeout=2.0)
        _drain_glib()

        mock_confirm.assert_called_once()
        mock_dir.assert_called_once()
        mock_create.assert_called_once_with(
            output_dir=str(out_dir),
            custom_log_path=app.custom_log_path,
            custom_config_path=app.custom_config_path,
        )

    assert app.btn_support_bundle.get_sensitive() is True
    status_text = app.lbl_support_status.get_text()
    assert str(expected_archive) in status_text
    assert mock_dialog.called
    assert mock_dialog.call_args[0][0] == "Support Bundle создан"


def test_support_bundle_user_cancel_warning(app_instance):
    """Verify that canceling the pre-flight sanitization warning aborts bundle creation."""
    app = app_instance

    with patch.object(app, "confirm_support_bundle_sanitization", return_value=False), \
         patch("main.create_support_bundle") as mock_create:

        app.on_support_bundle_clicked()
        _drain_glib()

        mock_create.assert_not_called()


def test_support_bundle_user_cancel_folder(app_instance):
    """Verify that canceling directory selection aborts bundle creation."""
    app = app_instance

    with patch.object(app, "confirm_support_bundle_sanitization", return_value=True), \
         patch.object(app, "choose_support_bundle_directory", return_value=None), \
         patch("main.create_support_bundle") as mock_create:

        app.on_support_bundle_clicked()
        _drain_glib()

        mock_create.assert_not_called()


def test_support_bundle_error_handling(app_instance, tmp_path):
    """Verify support bundle creation errors are presented cleanly."""
    app = app_instance
    out_dir = tmp_path / "failing_dir"

    with patch.object(app, "confirm_support_bundle_sanitization", return_value=True), \
         patch.object(app, "choose_support_bundle_directory", return_value=str(out_dir)), \
         patch.object(app, "show_dialog") as mock_dialog, \
         patch("main.create_support_bundle", side_effect=OSError("Disk quota exceeded")):

        app.on_support_bundle_clicked()
        if hasattr(app, "_bundle_thread") and app._bundle_thread:
            app._bundle_thread.join(timeout=2.0)
        _drain_glib()

        assert app.btn_support_bundle.get_sensitive() is True
        status_text = app.lbl_support_status.get_text()
        assert "Ошибка сборки" in status_text
        assert "Disk quota exceeded" in status_text
        assert mock_dialog.called
        assert mock_dialog.call_args[0][0] == "Ошибка"


def test_real_support_bundle_does_not_create_file_in_home_dir(app_instance, tmp_path):
    """Strictly verify that real bundle generation does NOT create archives in home dir."""
    app = app_instance
    target_dir = tmp_path / "actual_bundles"
    target_dir.mkdir(parents=True, exist_ok=True)

    home_dir = Path.home()
    home_before = set(home_dir.glob("support_bundle_*.tar.gz"))

    with patch.object(app, "confirm_support_bundle_sanitization", return_value=True), \
         patch.object(app, "choose_support_bundle_directory", return_value=str(target_dir)), \
         patch.object(app, "show_dialog"):

        app.on_support_bundle_clicked()
        if hasattr(app, "_bundle_thread") and app._bundle_thread:
            app._bundle_thread.join(timeout=4.0)
        _drain_glib()

    home_after = set(home_dir.glob("support_bundle_*.tar.gz"))
    assert home_after == home_before, (
        f"Support bundle leaked into home directory! New files: {home_after - home_before}"
    )

    created_archives = list(target_dir.glob("support_bundle_*.tar.gz"))
    assert len(created_archives) == 1, f"Expected 1 archive in {target_dir}, got: {created_archives}"

    # Verify tar.gz integrity
    with tarfile.open(created_archives[0], "r:gz") as tar:
        names = tar.getnames()
        assert any("system_info.json" in n for n in names)
        assert any("manifest.json" in n for n in names)
        assert any("zapret_logs.txt" in n for n in names)
        assert any("analysis_report.json" in n for n in names)
