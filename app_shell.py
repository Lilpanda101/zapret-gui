#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
App Shell layout components for Zapret GUI.
Provides page containers, setting rows, navigation sidebar structure,
and persistent status elements.
"""

from __future__ import annotations
from typing import Optional, Tuple
import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk, GLib

from persistent_bar import PersistentStatusBar, create_persistent_bar


def create_page_container(title_text: str, subtitle_text: Optional[str] = None) -> Tuple[Gtk.ScrolledWindow, Gtk.Box]:
    """Creates a scrolled page with a constrained, centered content width for ultrawide displays."""
    scrolled = Gtk.ScrolledWindow()
    scrolled.set_policy(Gtk.PolicyType.AUTOMATIC, Gtk.PolicyType.AUTOMATIC)

    outer_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    outer_box.set_halign(Gtk.Align.CENTER)
    outer_box.set_hexpand(True)
    outer_box.set_size_request(920, -1)
    outer_box.set_margin_top(22)
    outer_box.set_margin_bottom(24)
    outer_box.set_margin_start(32)
    outer_box.set_margin_end(32)
    outer_box.get_style_context().add_class("content-wrapper")

    t_lbl = Gtk.Label(label=title_text)
    t_lbl.get_style_context().add_class("page-title")
    t_lbl.set_xalign(0)
    outer_box.pack_start(t_lbl, False, False, 0)

    if subtitle_text:
        s_lbl = Gtk.Label(label=subtitle_text)
        s_lbl.get_style_context().add_class("page-subtitle")
        s_lbl.set_xalign(0)
        outer_box.pack_start(s_lbl, False, False, 0)

    scrolled.add(outer_box)
    return scrolled, outer_box


def create_setting_row(icon_str: Optional[str], title_text: str, desc_text: Optional[str], control_widget: Gtk.Widget) -> Gtk.Box:
    """Creates a modern Windows 11 style setting row."""
    row_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
    row_box.get_style_context().add_class("fluent-setting-row")

    # Icon
    icon_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
    icon_box.get_style_context().add_class("setting-icon-box")
    lbl_icon = Gtk.Label()
    lbl_icon.set_markup(f"<span font='14'>{icon_str}</span>")
    icon_box.pack_start(lbl_icon, True, True, 0)
    row_box.pack_start(icon_box, False, False, 0)

    # Title & Description
    txt_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
    lbl_title = Gtk.Label(label=f"<b>{GLib.markup_escape_text(title_text)}</b>", use_markup=True, xalign=0)
    lbl_desc = Gtk.Label(label=desc_text, xalign=0)
    lbl_desc.get_style_context().add_class("page-subtitle")
    txt_box.pack_start(lbl_title, False, False, 0)
    txt_box.pack_start(lbl_desc, False, False, 0)
    row_box.pack_start(txt_box, True, True, 0)

    # Control widget (Switch, Combo, etc.) aligned to end
    control_widget.set_halign(Gtk.Align.END)
    control_widget.set_valign(Gtk.Align.CENTER)
    row_box.pack_end(control_widget, False, False, 0)

    return row_box
