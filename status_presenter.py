#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Status Presenter for Zapret GUI.
Centralized translation of engine states (ACTIVE, NFQWS_ONLY, INACTIVE)
into UI presentation: titles, descriptions, buttons, banners, badges.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Optional


@dataclass(frozen=True)
class StatusViewData:
    state: str
    is_running: bool
    title_markup: str
    desc_text: str
    btn_label: str
    btn_danger: bool
    banner_active: bool
    pill_text: str
    pill_badge_cls: str  # "badge-ok", "badge-warn", "badge-bad"


def compute_status_view(state: str, engine_mode: str = "nfqws2") -> StatusViewData:
    mode_title = {"tpws": "TPWS", "nfqws2": "nfqws2 + Lua"}.get(engine_mode, "nfqws v1")
    if state == "ACTIVE":
        return StatusViewData(
            state="ACTIVE",
            is_running=True,
            title_markup=f"<span font='15' weight='bold' color='#34d399'>🟢 Движок запущен ({mode_title})</span>",
            desc_text="Процесс и правила перехвата активны. Доступность сервисов проверяется отдельно в диагностике.",
            btn_label="■ Остановить обход",
            btn_danger=True,
            banner_active=True,
            pill_text="● Обход DPI активен",
            pill_badge_cls="badge-ok",
        )
    elif state == "NFQWS_ONLY":
        return StatusViewData(
            state="NFQWS_ONLY",
            is_running=True,
            title_markup=f"<span font='15' weight='bold' color='#f59e0b'>🟡 Движок запущен • Правила nftables отсутствуют ({mode_title})</span>",
            desc_text="Процесс десинхронизатора активен, но правила перехвата трафика не найдены.",
            btn_label="■ Остановить обход",
            btn_danger=True,
            banner_active=True,
            pill_text="● NFQWS без nftables",
            pill_badge_cls="badge-warn",
        )
    else:
        return StatusViewData(
            state=state or "INACTIVE",
            is_running=False,
            title_markup="<span font='15' weight='bold' color='#f87171'>○ Zapret остановлен • Обход выключен</span>",
            desc_text="Нажмите «Запустить обход», чтобы включить десинхронизацию для YouTube и Discord.",
            btn_label="▶ Запустить обход",
            btn_danger=False,
            banner_active=False,
            pill_text="○ Обход DPI выключен",
            pill_badge_cls="badge-bad",
        )


class StatusPresenter:
    """Presenter updating GTK widgets and app state according to engine status."""

    def __init__(self, app: Any):
        self.app = app

    def apply(self, state: str) -> StatusViewData:
        mode = getattr(self.app, "engine_mode", "nfqws2")
        data = compute_status_view(state, mode)
        self.app.is_running = data.is_running

        if getattr(self.app, "status_title", None) is not None:
            self.app.status_title.set_markup(data.title_markup)
        if getattr(self.app, "status_desc", None) is not None:
            self.app.status_desc.set_text(data.desc_text)

        if getattr(self.app, "btn_toggle", None) is not None:
            self.app.btn_toggle.set_label(data.btn_label)
            ctx = self.app.btn_toggle.get_style_context()
            if data.btn_danger:
                ctx.remove_class("fluent-btn-primary")
                ctx.add_class("fluent-btn-danger")
            else:
                ctx.remove_class("fluent-btn-danger")
                ctx.add_class("fluent-btn-primary")

        if getattr(self.app, "status_banner", None) is not None:
            ctx = self.app.status_banner.get_style_context()
            if data.banner_active:
                ctx.remove_class("status-banner-inactive")
                ctx.add_class("status-banner-active")
            else:
                ctx.remove_class("status-banner-active")
                ctx.add_class("status-banner-inactive")

        if getattr(self.app, "pill_status", None) is not None:
            self.app.pill_status.set_text(data.pill_text)
            ctx = self.app.pill_status.get_style_context()
            ctx.remove_class("badge-ok")
            ctx.remove_class("badge-warn")
            ctx.remove_class("badge-bad")
            ctx.add_class(data.pill_badge_cls)

        if getattr(self.app, "sidebar_status_dot", None) is not None:
            ctx = self.app.sidebar_status_dot.get_style_context()
            ctx.remove_class("badge-ok")
            ctx.remove_class("badge-warn")
            ctx.remove_class("badge-bad")
            ctx.add_class(data.pill_badge_cls)

        if getattr(self.app, "top_card_preset", None) is not None:
            ctx = self.app.top_card_preset.get_style_context()
            if data.banner_active:
                ctx.add_class("hero-card-accent")
            else:
                ctx.remove_class("hero-card-accent")

        if getattr(self.app, "post_status_message", None) is not None:
            if data.state == "ACTIVE":
                self.app.post_status_message("Обход DPI активен: пакеты десинхронизируются")
            elif data.state == "NFQWS_ONLY":
                self.app.post_status_message("NFQWS запущен, правила nftables не найдены")
            else:
                self.app.post_status_message("Обход DPI остановлен")

        if hasattr(self.app, "update_tray"):
            try:
                self.app.update_tray(data.is_running)
            except Exception:
                pass

        if hasattr(self.app, "update_persistent_bar"):
            try:
                self.app.update_persistent_bar(data)
            except Exception:
                pass

        return data
