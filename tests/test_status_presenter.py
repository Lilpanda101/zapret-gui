#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from unittest.mock import MagicMock
import pytest

from status_presenter import StatusPresenter, compute_status_view, StatusViewData


def test_compute_status_view_active():
    data = compute_status_view("ACTIVE", "nfqws2")
    assert isinstance(data, StatusViewData)
    assert data.is_running is True
    assert "🟢" in data.title_markup
    assert "nfqws2 + Lua" in data.title_markup
    assert "■ Остановить обход" in data.btn_label
    assert data.btn_danger is True
    assert data.banner_active is True
    assert "● Обход DPI активен" in data.pill_text
    assert data.pill_badge_cls == "badge-ok"


def test_compute_status_view_nfqws_only():
    data = compute_status_view("NFQWS_ONLY", "tpws")
    assert data.is_running is True
    assert "🟡" in data.title_markup
    assert "TPWS" in data.title_markup
    assert "■ Остановить обход" in data.btn_label
    assert data.btn_danger is True
    assert data.banner_active is True
    assert "● NFQWS без nftables" in data.pill_text
    assert data.pill_badge_cls == "badge-warn"


def test_compute_status_view_inactive():
    data = compute_status_view("INACTIVE", "nfqws2")
    assert data.is_running is False
    assert "○" in data.title_markup
    assert "▶ Запустить обход" in data.btn_label
    assert data.btn_danger is False
    assert data.banner_active is False
    assert "○ Обход DPI выключен" in data.pill_text
    assert data.pill_badge_cls == "badge-bad"


def test_status_presenter_apply():
    app = MagicMock()
    app.engine_mode = "nfqws2"
    app.status_title = MagicMock()
    app.status_desc = MagicMock()
    app.btn_toggle = MagicMock()
    app.status_banner = MagicMock()
    app.pill_status = MagicMock()
    app.update_tray = MagicMock()

    btn_ctx = MagicMock()
    app.btn_toggle.get_style_context.return_value = btn_ctx
    banner_ctx = MagicMock()
    app.status_banner.get_style_context.return_value = banner_ctx
    pill_ctx = MagicMock()
    app.pill_status.get_style_context.return_value = pill_ctx

    presenter = StatusPresenter(app)

    # Apply ACTIVE
    res = presenter.apply("ACTIVE")
    assert res.is_running is True
    assert app.is_running is True
    app.status_title.set_markup.assert_called_once_with(res.title_markup)
    app.status_desc.set_text.assert_called_once_with(res.desc_text)
    app.btn_toggle.set_label.assert_called_once_with("■ Остановить обход")
    btn_ctx.remove_class.assert_called_with("fluent-btn-primary")
    btn_ctx.add_class.assert_called_with("fluent-btn-danger")
    banner_ctx.remove_class.assert_called_with("status-banner-inactive")
    banner_ctx.add_class.assert_called_with("status-banner-active")
    pill_ctx.add_class.assert_called_with("badge-ok")
    app.update_tray.assert_called_once_with(True)

    # Apply INACTIVE
    presenter.apply("INACTIVE")
    assert app.is_running is False
    app.btn_toggle.set_label.assert_called_with("▶ Запустить обход")
    btn_ctx.remove_class.assert_called_with("fluent-btn-danger")
    btn_ctx.add_class.assert_called_with("fluent-btn-primary")
    banner_ctx.remove_class.assert_called_with("status-banner-active")
    banner_ctx.add_class.assert_called_with("status-banner-inactive")
    pill_ctx.add_class.assert_called_with("badge-bad")
    app.update_tray.assert_called_with(False)
