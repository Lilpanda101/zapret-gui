#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import gi
gi.require_version("Gtk", "3.0")
from gi.repository import Gtk

from app_shell import create_page_container, create_setting_row


def test_create_page_container():
    scrolled, vbox = create_page_container("Тестовый заголовок", "Тестовое описание")
    assert isinstance(scrolled, Gtk.ScrolledWindow)
    assert isinstance(vbox, Gtk.Box)
    child = scrolled.get_child()
    if isinstance(child, Gtk.Viewport):
        assert child.get_child() == vbox
    else:
        assert child == vbox

    children = vbox.get_children()
    assert len(children) >= 2
    assert children[0].get_text() == "Тестовый заголовок"
    assert children[1].get_text() == "Тестовое описание"


def test_create_setting_row():
    switch = Gtk.Switch()
    row = create_setting_row("⚡", "Тестовая настройка", "Подробное пояснение", switch)
    assert isinstance(row, Gtk.Box)
    children = row.get_children()
    assert len(children) == 3  # icon box, text box, control switch
    assert children[-1] == switch
