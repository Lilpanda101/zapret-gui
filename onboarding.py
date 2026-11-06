#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Onboarding tour dialog and welcome flow for Zapret 2 Linux.

Provides an accessible, modern multi-step guided tour introducing:
1. Zapret 2 architecture & nfqws2 vs nfqws v1 benefits (Lua, multi-profile, performance).
2. Preset catalog selection (Flowseal 136+ presets, general, discord, youtube).
3. System tray behavior and background autostart workflow.
"""

from __future__ import annotations

import logging
import os
from typing import Callable, Optional

import gi
gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
from gi.repository import Gtk, Gdk, GLib

from config_manager import (
    should_show_onboarding,
    mark_onboarding_completed,
    load_config_from_file,
    save_config_to_file,
)

logger = logging.getLogger("zapret_gui.onboarding")

AUTOSTART_FILE = os.path.expanduser("~/.config/autostart/zapret-gui.desktop")
AUTOSTART_TEMPLATE = """[Desktop Entry]
Type=Application
Exec=zapret-gui --minimized
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name=Zapret 2 Linux
Comment=Bypass DPI subsystem daemon
Icon=network-vpn
Categories=Network;
"""

ONBOARDING_CSS = b"""
/* Onboarding Dialog Window */
.onboarding-window {
    background-color: #14141c;
    color: #f3f3f3;
}

.onboarding-card {
    background-color: #1b1b26;
    border: 1px solid #2a2a3c;
    border-radius: 10px;
    padding: 16px 18px;
}

.onboarding-card-accent {
    background: linear-gradient(135deg, rgba(0, 120, 212, 0.12) 0%, rgba(27, 27, 38, 0.95) 100%);
    border: 1px solid rgba(96, 205, 255, 0.45);
    border-radius: 10px;
    padding: 16px 18px;
}

.onboarding-step-pill {
    font-size: 11px;
    font-weight: 600;
    padding: 4px 10px;
    border-radius: 12px;
    background-color: #262636;
    color: #8f8fa4;
}

.onboarding-step-pill-active {
    background-color: #0078d4;
    color: #ffffff;
}

.badge-tag-v2 {
    font-size: 11px;
    font-weight: 700;
    color: #60cdff;
    background-color: rgba(96, 205, 255, 0.15);
    padding: 2px 8px;
    border-radius: 4px;
}

.badge-tag-legacy {
    font-size: 11px;
    font-weight: 600;
    color: #8e8ea4;
    background-color: rgba(255, 255, 255, 0.08);
    padding: 2px 8px;
    border-radius: 4px;
}

.feature-bullet {
    font-size: 12px;
    color: #d1d1e0;
}
"""


class OnboardingDialog(Gtk.Dialog):
    """Multi-step onboarding tour dialog for first-time or replay users."""

    TOTAL_STEPS = 3

    def __init__(
        self,
        parent: Optional[Gtk.Window] = None,
        config: Optional[dict] = None,
        config_file: Optional[str] = None,
        on_complete: Optional[Callable[[], None]] = None,
    ):
        super().__init__(
            title="Добро пожаловать в Zapret 2 Linux",
            transient_for=parent,
            flags=Gtk.DialogFlags.MODAL if parent else 0,
        )
        self.set_default_size(720, 560)
        self.set_position(Gtk.WindowPosition.CENTER_ON_PARENT if parent else Gtk.WindowPosition.CENTER)
        self.set_icon_name("network-vpn")
        self.get_style_context().add_class("onboarding-window")

        self.parent_window = parent
        self.config = config if config is not None else {}
        self.config_file = config_file
        self.on_complete = on_complete

        self.current_step = 0
        self.selected_preset = self.config.get("preset", "general")

        self._load_css()
        self._build_ui()
        self.connect("key-press-event", self._on_key_press)

    def _load_css(self):
        try:
            provider = Gtk.CssProvider()
            provider.load_from_data(ONBOARDING_CSS)
            context = self.get_style_context()
            context.add_provider(provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
        except Exception as e:
            logger.debug("Failed to apply onboarding custom CSS: %s", e)

    def _build_ui(self):
        content_area = self.get_content_area()
        content_area.set_spacing(0)

        main_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        main_box.set_margin_start(24)
        main_box.set_margin_end(24)
        main_box.set_margin_top(20)
        main_box.set_margin_bottom(16)
        content_area.pack_start(main_box, True, True, 0)

        # 1. Top Header & Step Progress Badges
        header_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        
        title_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.lbl_title = Gtk.Label(xalign=0)
        self.lbl_title.set_markup("<span font='16' weight='bold' color='#60cdff'>Добро пожаловать в Zapret 2</span>")
        self.lbl_subtitle = Gtk.Label(xalign=0)
        self.lbl_subtitle.get_style_context().add_class("page-subtitle")
        self.lbl_subtitle.set_text("Интерактивный тур первого запуска: возможности, пресеты и трей")
        title_box.pack_start(self.lbl_title, False, False, 0)
        title_box.pack_start(self.lbl_subtitle, False, False, 0)
        header_box.pack_start(title_box, True, True, 0)

        # Step indicator pills
        self.pills_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.pills_box.set_valign(Gtk.Align.CENTER)
        self.step_labels = []
        for i in range(self.TOTAL_STEPS):
            lbl = Gtk.Label(label=f"Шаг {i + 1}")
            lbl.get_style_context().add_class("onboarding-step-pill")
            self.step_labels.append(lbl)
            self.pills_box.pack_start(lbl, False, False, 0)
        header_box.pack_end(self.pills_box, False, False, 0)

        main_box.pack_start(header_box, False, False, 0)

        # Separator line
        sep = Gtk.Separator(orientation=Gtk.Orientation.HORIZONTAL)
        main_box.pack_start(sep, False, False, 4)

        # 2. Central Content Stack
        self.stack = Gtk.Stack()
        self.stack.set_transition_type(Gtk.StackTransitionType.SLIDE_LEFT_RIGHT)
        self.stack.set_transition_duration(200)

        self.stack.add_named(self._build_step_1_architecture(), "step_0")
        self.stack.add_named(self._build_step_2_presets(), "step_1")
        self.stack.add_named(self._build_step_3_tray_autostart(), "step_2")

        main_box.pack_start(self.stack, True, True, 0)

        # 3. Footer Navigation Bar
        footer_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        footer_box.set_margin_top(8)

        # Skip / Back button
        self.btn_back = Gtk.Button(label="Пропустить")
        self.btn_back.get_style_context().add_class("fluent-btn-secondary")
        self.btn_back.set_tooltip_text("Пропустить тур и перейти к работе (Esc)")
        self.btn_back.set_can_focus(True)
        self.btn_back.connect("clicked", self._on_back_clicked)
        footer_box.pack_start(self.btn_back, False, False, 0)

        # Step counter text
        self.lbl_step_counter = Gtk.Label(label="1 из 3", xalign=0.5)
        self.lbl_step_counter.get_style_context().add_class("page-subtitle")
        footer_box.pack_start(self.lbl_step_counter, True, True, 0)

        # Next / Finish button
        self.btn_next = Gtk.Button(label="Далее →")
        self.btn_next.get_style_context().add_class("fluent-btn-primary")
        self.btn_next.set_tooltip_text("Следующий шаг тура (Enter / Space)")
        self.btn_next.set_can_focus(True)
        self.btn_next.connect("clicked", self._on_next_clicked)
        footer_box.pack_end(self.btn_next, False, False, 0)

        main_box.pack_start(footer_box, False, False, 0)

        self.stack.show_all()
        self._update_step_state()

    @property
    def current_step_name(self) -> str:
        """Returns name identifier of the current active step."""
        return f"step_{self.current_step}"

    def _build_step_1_architecture(self) -> Gtk.Widget:
        """Step 1: Introduction and nfqws v1 vs nfqws2 comparison."""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        lead_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        lead_card.get_style_context().add_class("onboarding-card-accent")
        
        icon_lbl = Gtk.Label()
        icon_lbl.set_markup("<span font='28'>🚀</span>")
        lead_card.pack_start(icon_lbl, False, False, 0)

        desc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        h_lbl = Gtk.Label(label="<b>Революция архитектуры Zapret 2</b>", use_markup=True, xalign=0)
        p_lbl = Gtk.Label(
            label="Новая версия перешла на современный движок nfqws2 со скриптами Lua, "
                  "точечными профилями для отдельных сервисов и аппаратным ускорением в ядре Linux.",
            xalign=0
        )
        p_lbl.set_line_wrap(True)
        p_lbl.get_style_context().add_class("feature-bullet")
        desc_box.pack_start(h_lbl, False, False, 0)
        desc_box.pack_start(p_lbl, False, False, 0)
        lead_card.pack_start(desc_box, True, True, 0)
        vbox.pack_start(lead_card, False, False, 0)

        # Comparison cards in 2 columns
        grid = Gtk.Grid()
        grid.set_column_spacing(12)
        grid.set_row_spacing(8)
        grid.set_column_homogeneous(True)

        # Left Column: Legacy v1
        card_v1 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card_v1.get_style_context().add_class("onboarding-card")

        tag_v1 = Gtk.Label()
        tag_v1.set_markup("<span weight='bold' color='#8e8ea4'>nfqws v1 (Legacy)</span>")
        tag_v1.get_style_context().add_class("badge-tag-legacy")
        tag_v1.set_xalign(0)
        card_v1.pack_start(tag_v1, False, False, 0)

        bullets_v1 = [
            "• Статичные аргументы командной строки на все домены",
            "• Один тяжелый процесс без тонкого деления на сервисы",
            "• Выше риск блокировки легитимного трафика",
            "• Сложная адаптация под новые блокировки ТСПУ",
        ]
        for b in bullets_v1:
            lbl = Gtk.Label(label=b, xalign=0)
            lbl.set_line_wrap(True)
            lbl.get_style_context().add_class("feature-bullet")
            card_v1.pack_start(lbl, False, False, 0)

        grid.attach(card_v1, 0, 0, 1, 1)

        # Right Column: Modern v2
        card_v2 = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card_v2.get_style_context().add_class("onboarding-card-accent")

        tag_v2 = Gtk.Label()
        tag_v2.set_markup("<span weight='bold' color='#60cdff'>⚡ nfqws2 + Lua (Zapret 2 Linux)</span>")
        tag_v2.get_style_context().add_class("badge-tag-v2")
        tag_v2.set_xalign(0)
        card_v2.pack_start(tag_v2, False, False, 0)

        bullets_v2 = [
            "• Модульные профили (Discord, YouTube, WebRTC, General)",
            "• Скриптовый движок Lua для динамических стратегий обхода",
            "• Zero-copy маршрутизация через nftables и минимальный пинг",
            "• Фоновый Auto-Healer с автоматической починкой сессий",
        ]
        for b in bullets_v2:
            lbl = Gtk.Label(label=b, xalign=0)
            lbl.set_line_wrap(True)
            lbl.get_style_context().add_class("feature-bullet")
            card_v2.pack_start(lbl, False, False, 0)

        grid.attach(card_v2, 1, 0, 1, 1)
        vbox.pack_start(grid, True, True, 0)

        return vbox

    def _build_step_2_presets(self) -> Gtk.Widget:
        """Step 2: Flowseal 136+ preset catalog and quick selection."""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        lead_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        lead_card.get_style_context().add_class("onboarding-card")

        icon_lbl = Gtk.Label()
        icon_lbl.set_markup("<span font='28'>📦</span>")
        lead_card.pack_start(icon_lbl, False, False, 0)

        desc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        h_lbl = Gtk.Label(label="<b>Каталог из 136 проверенных пресетов Flowseal</b>", use_markup=True, xalign=0)
        p_lbl = Gtk.Label(
            label="Все популярные стратегии обхода для ТСПУ, проводных провайдеров и мобильных сетей "
                  "рассортированы по семействам и готовы к активации.",
            xalign=0
        )
        p_lbl.set_line_wrap(True)
        p_lbl.get_style_context().add_class("feature-bullet")
        desc_box.pack_start(h_lbl, False, False, 0)
        desc_box.pack_start(p_lbl, False, False, 0)
        lead_card.pack_start(desc_box, True, True, 0)
        vbox.pack_start(lead_card, False, False, 0)

        # Preset families grid
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(8)
        grid.set_column_homogeneous(True)

        families = [
            ("🌐 General / Универсальный", "Базовый обход веб-сайтов, соцсетей и новостных порталов.", 0, 0),
            ("🎮 Discord Fix", "Раздельный обход шлюзов WebRTC, войс-серверов и медиа CDN.", 1, 0),
            ("🎬 YouTube 4K", "Устранение троттлинга потоков Googlevideo без падения скорости.", 0, 1),
            ("🛡️ Aggressive Disorder", "Усиленные fake-сегменты для жестких фильтров и мобильных сетей.", 1, 1),
        ]

        for title, desc, col, row in families:
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            box.get_style_context().add_class("onboarding-card")
            lbl_t = Gtk.Label(label=f"<b>{title}</b>", use_markup=True, xalign=0)
            lbl_d = Gtk.Label(label=desc, xalign=0)
            lbl_d.set_line_wrap(True)
            lbl_d.get_style_context().add_class("feature-bullet")
            box.pack_start(lbl_t, False, False, 0)
            box.pack_start(lbl_d, False, False, 0)
            grid.attach(box, col, row, 1, 1)

        vbox.pack_start(grid, True, True, 0)

        # Preset selector combo
        select_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        select_box.get_style_context().add_class("onboarding-card-accent")

        lbl_choice = Gtk.Label(label="<b>Стартовый пресет обхода:</b>", use_markup=True, xalign=0)
        select_box.pack_start(lbl_choice, False, False, 0)

        self.combo_preset = Gtk.ComboBoxText()
        presets_list = [
            ("general", "🌐 General (Default circular) — Рекомендуется"),
            ("general_fake", "🛡️ General Fake-Disorder (Для жестких ТСПУ)"),
            ("discord", "🎮 Discord WebRTC & Voice"),
            ("youtube", "🎬 YouTube 4K Streaming"),
        ]
        for key, name in presets_list:
            self.combo_preset.append(key, name)

        if self.selected_preset in [k for k, _ in presets_list]:
            self.combo_preset.set_active_id(self.selected_preset)
        else:
            self.combo_preset.set_active(0)

        self.combo_preset.connect("changed", self._on_preset_changed)
        select_box.pack_start(self.combo_preset, True, True, 0)
        vbox.pack_start(select_box, False, False, 0)

        return vbox

    def _build_step_3_tray_autostart(self) -> Gtk.Widget:
        """Step 3: System tray integration, autostart, and silent background mode."""
        vbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)

        lead_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=14)
        lead_card.get_style_context().add_class("onboarding-card-accent")

        icon_lbl = Gtk.Label()
        icon_lbl.set_markup("<span font='28'>🔕</span>")
        lead_card.pack_start(icon_lbl, False, False, 0)

        desc_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        h_lbl = Gtk.Label(label="<b>Фоновая работа и системный трей</b>", use_markup=True, xalign=0)
        p_lbl = Gtk.Label(
            label="Zapret 2 оптимизирован для тихой работы в фоне — управляйте обходом "
                  "без лишних открытых окон.",
            xalign=0
        )
        p_lbl.set_line_wrap(True)
        p_lbl.get_style_context().add_class("feature-bullet")
        desc_box.pack_start(h_lbl, False, False, 0)
        desc_box.pack_start(p_lbl, False, False, 0)
        lead_card.pack_start(desc_box, True, True, 0)
        vbox.pack_start(lead_card, False, False, 0)

        # Feature rows
        features = [
            ("📌", "Сворачивание в системный трей",
             "При нажатии на крестик окно сворачивается в трей, а сервис продолжает работать незаметно."),
            ("⚡", "Быстрое меню в один клик",
             "Кликните правой кнопкой мыши по иконке в трее, чтобы мгновенно включить/выключить обход или сменить пресет."),
            ("🩹", "Auto-Healing защита",
             "Фоновый демон автоматически следит за доступностью зеркал и лечит сетевые сбои."),
        ]

        for icon_str, title, desc in features:
            f_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
            f_box.get_style_context().add_class("onboarding-card")

            lbl_i = Gtk.Label()
            lbl_i.set_markup(f"<span font='18'>{icon_str}</span>")
            f_box.pack_start(lbl_i, False, False, 0)

            t_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
            lbl_t = Gtk.Label(label=f"<b>{title}</b>", use_markup=True, xalign=0)
            lbl_d = Gtk.Label(label=desc, xalign=0)
            lbl_d.set_line_wrap(True)
            lbl_d.get_style_context().add_class("feature-bullet")
            t_box.pack_start(lbl_t, False, False, 0)
            t_box.pack_start(lbl_d, False, False, 0)
            f_box.pack_start(t_box, True, True, 0)

            vbox.pack_start(f_box, False, False, 0)

        # Autostart interactive switch
        auto_card = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        auto_card.get_style_context().add_class("onboarding-card")

        auto_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        auto_info.pack_start(Gtk.Label(label="<b>Автозапуск при входе в сессию Linux</b>", use_markup=True, xalign=0), False, False, 0)
        auto_desc = Gtk.Label(label="Создает ярлык ~/.config/autostart для запуска в свернутом виде", xalign=0)
        auto_desc.get_style_context().add_class("feature-bullet")
        auto_info.pack_start(auto_desc, False, False, 0)
        auto_card.pack_start(auto_info, True, True, 0)

        self.sw_autostart = Gtk.Switch()
        self.sw_autostart.set_active(os.path.exists(AUTOSTART_FILE))
        self.sw_autostart.set_valign(Gtk.Align.CENTER)
        self.sw_autostart.connect("notify::active", self._on_autostart_toggled)
        auto_card.pack_end(self.sw_autostart, False, False, 0)
        vbox.pack_start(auto_card, False, False, 0)

        return vbox

    def _update_step_state(self):
        """Update buttons, pills, and current page based on current_step."""
        self.stack.set_visible_child_name(f"step_{self.current_step}")
        self.lbl_step_counter.set_text(f"Шаг {self.current_step + 1} из {self.TOTAL_STEPS}")

        # Update pills highlighting
        for i, lbl in enumerate(self.step_labels):
            ctx = lbl.get_style_context()
            if i == self.current_step:
                ctx.add_class("onboarding-step-pill-active")
            else:
                ctx.remove_class("onboarding-step-pill-active")

        # Update back / skip button
        if self.current_step == 0:
            self.btn_back.set_label("Пропустить")
            self.btn_back.set_tooltip_text("Пропустить тур и перейти к работе (Esc)")
        else:
            self.btn_back.set_label("← Назад")
            self.btn_back.set_tooltip_text("Вернуться к предыдущему шагу")

        # Update next / finish button
        if self.current_step == self.TOTAL_STEPS - 1:
            self.btn_next.set_label("✨ Начать работу")
            self.btn_next.set_tooltip_text("Завершить обучение и открыть главное окно (Enter)")
        else:
            self.btn_next.set_label("Далее →")
            self.btn_next.set_tooltip_text("Следующий шаг тура (Enter / Space)")

    def next_step(self):
        """Advance to next step or complete the tour."""
        if self.current_step < self.TOTAL_STEPS - 1:
            self.current_step += 1
            self._update_step_state()
        else:
            self.finish_tour()

    def prev_step(self):
        """Go back to previous step or skip if on first step."""
        if self.current_step > 0:
            self.current_step -= 1
            self._update_step_state()
        else:
            self.skip_tour()

    def _on_next_clicked(self, _widget):
        self.next_step()

    def _on_back_clicked(self, _widget):
        self.prev_step()

    def _on_preset_changed(self, combo):
        active_id = combo.get_active_id()
        if active_id:
            self.selected_preset = active_id
            self.config["preset"] = active_id

    def _on_autostart_toggled(self, switch, _param):
        is_active = switch.get_active()
        try:
            if is_active:
                os.makedirs(os.path.dirname(AUTOSTART_FILE), exist_ok=True)
                with open(AUTOSTART_FILE, "w", encoding="utf-8") as f:
                    f.write(AUTOSTART_TEMPLATE)
            else:
                if os.path.exists(AUTOSTART_FILE):
                    os.remove(AUTOSTART_FILE)
        except Exception as e:
            logger.warning("Failed to toggle autostart in onboarding: %s", e)

    def _on_key_press(self, _widget, event: Gdk.EventKey) -> bool:
        """Handle keyboard accessibility shortcuts (Escape, Enter, Space)."""
        keyval = event.keyval
        if keyval in (Gdk.KEY_Escape,):
            self.skip_tour()
            return True
        elif keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            # If focus is currently on back button, let it trigger clicked; otherwise advance
            focus = self.get_focus()
            if focus == self.btn_back:
                self.prev_step()
            else:
                self.next_step()
            return True
        return False

    def finish_tour(self):
        """Mark onboarding complete, apply selected preset and close dialog."""
        logger.info("Finishing onboarding tour")
        if self.selected_preset:
            self.config["preset"] = self.selected_preset

        if self.config_file:
            mark_onboarding_completed(self.config_file, self.config)
        else:
            self.config["onboarding_completed"] = True

        if callable(self.on_complete):
            try:
                self.on_complete()
            except Exception as e:
                logger.error("Error invoking on_complete callback: %s", e)

        self.destroy()

    def skip_tour(self):
        """Skip tour, mark complete so it does not bother the user again, and close."""
        logger.info("Skipping onboarding tour")
        if self.config_file:
            mark_onboarding_completed(self.config_file, self.config)
        else:
            self.config["onboarding_completed"] = True

        if callable(self.on_complete):
            try:
                self.on_complete()
            except Exception as e:
                logger.error("Error invoking on_complete callback: %s", e)

        self.destroy()


def show_onboarding(
    parent_window: Optional[Gtk.Window] = None,
    config: Optional[dict] = None,
    config_file: Optional[str] = None,
    on_finish: Optional[Callable[[], None]] = None,
) -> Optional[OnboardingDialog]:
    """
    Convenience helper to display the onboarding dialog.
    Returns the created dialog instance, or None if GTK display is unavailable.
    """
    initialized = Gtk.init_check([])[0]
    if not initialized:
        logger.warning("GTK display unavailable; cannot show onboarding dialog")
        return None

    dialog = OnboardingDialog(
        parent=parent_window,
        config=config,
        config_file=config_file,
        on_complete=on_finish,
    )
    dialog.show_all()
    return dialog
