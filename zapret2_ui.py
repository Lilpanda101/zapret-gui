#!/usr/bin/env python3
"""GTK page for native Zapret2 presets, health check, auto-hostlist and profile editing."""

from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GLib", "2.0")
from gi.repository import Gtk, Gdk, GLib

try:
    gi.require_version("GtkSource", "4")
    from gi.repository import GtkSource
    HAVE_GTK_SOURCE = True
except Exception:
    HAVE_GTK_SOURCE = False

import zapret2_core as core
from catalog.preset_catalog import PresetCatalog, parse_preset_id


FILTER_CATEGORIES = [
    ("recommended", "🌟 Топ / Рекомендуемые"),
    ("circular", "🔄 Circular (Адаптивные)"),
    ("game", "🎮 Игровые (Game filter)"),
    ("all", "Все пресеты"),
]

HEALTH_TARGETS = [
    ("YouTube", "https://www.youtube.com/generate_204"),
    ("GoogleVideo Stream", "https://redirector.googlevideo.com/report_mapping"),
    ("Discord Gateway", "https://discord.com/api/v10/gateway"),
    ("Rutracker", "https://rutracker.org"),
]

GAME_WARNING_TEXT = (
    "⚠️ Внимание: в игровых пресетах фильтрация идёт по IP (ipset), а не по доменам. "
    "При смене IP провайдером YouTube/Discord могут отваливаться. "
    "Для стабильности рекомендуется 'general ALT'."
)


def _init_css():
    try:
        screen = Gdk.Screen.get_default()
        if not screen:
            return
        provider = Gtk.CssProvider()
        css = b"""
        .filter-pill {
            background-color: #232334;
            color: #b0b0c8;
            border: 1px solid #36364c;
            border-radius: 16px;
            padding: 5px 12px;
            font-size: 11px;
            font-weight: 600;
            transition: all 120ms ease;
        }
        .filter-pill:hover {
            background-color: #2d2d42;
            border-color: #4a4a68;
            color: #ffffff;
        }
        .filter-pill:checked, .filter-pill:active {
            background-color: #0078d4;
            border-color: #1084d8;
            color: #ffffff;
        }
        .game-warning-banner {
            background: linear-gradient(135deg, rgba(245, 158, 11, 0.16) 0%, rgba(35, 30, 20, 0.95) 100%);
            border: 1px solid rgba(245, 158, 11, 0.55);
            border-radius: 8px;
            padding: 10px 14px;
        }
        .game-warning-banner label {
            color: #fcd34d;
            font-weight: 500;
        }
        .health-grid-tile {
            background-color: #1c1c28;
            border: 1px solid #28283a;
            border-radius: 8px;
            padding: 10px 14px;
        }
        .health-grid-tile:hover {
            border-color: #38384f;
        }
        """
        provider.load_from_data(css)
        Gtk.StyleContext.add_provider_for_screen(screen, provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)
    except Exception:
        pass


def check_url_health(url: str, timeout: float = 3.5) -> tuple[bool, int, str]:
    """Проверяет доступность URL и возвращает (is_ok, latency_ms, status_or_reason)."""
    t0 = time.time()
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0",
            "Accept": "*/*",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            dt = int((time.time() - t0) * 1000)
            if 200 <= response.status < 400:
                return True, dt, "OK"
            return False, dt, f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        dt = int((time.time() - t0) * 1000)
        if exc.code < 500:
            return True, dt, "OK"
        return False, dt, f"HTTP {exc.code}"
    except urllib.error.URLError as exc:
        dt = int((time.time() - t0) * 1000)
        reason = str(exc.reason) if exc.reason else str(exc)
        if "timed out" in reason.lower() or isinstance(exc.reason, (socket.timeout, TimeoutError)):
            return False, dt, "Таймаут"
        elif "reset" in reason.lower() or isinstance(exc.reason, ConnectionResetError):
            return False, dt, "RST"
        return False, dt, "Таймаут/RST"
    except (socket.timeout, TimeoutError):
        dt = int((time.time() - t0) * 1000)
        return False, dt, "Таймаут"
    except ConnectionResetError:
        dt = int((time.time() - t0) * 1000)
        return False, dt, "RST"
    except Exception as exc:
        dt = int((time.time() - t0) * 1000)
        err = str(exc).lower()
        if "timeout" in err or "timed out" in err:
            return False, dt, "Таймаут"
        if "reset" in err:
            return False, dt, "RST"
        return False, dt, "Таймаут/RST"


def preset_matches_category(item: dict, selected_category: str) -> bool:
    """Проверяет соответствие пресета выбранной категории."""
    if selected_category == "all":
        return True
    cat = item.get("category") or core.categorize_preset(item.get("id", item.get("title", "")))
    title_lower = item.get("title", "").casefold()
    if selected_category in ("recommended", "top"):
        return cat in ("recommended", "top") or core.is_top_preset(item.get("title", ""))
    if selected_category == "circular":
        return cat == "circular" or item.get("circular", False) or "(circular)" in title_lower
    if selected_category == "game":
        return cat == "game" or "game filter" in title_lower or "game" in title_lower
    return cat == selected_category


class Zapret2Page:
    def __init__(self, app):
        self.app = app
        self.catalog = PresetCatalog.load_from_directory(
            core.APP_DIR / "zapret2" / "presets" / "winws2_builtin",
            core.USER_PRESETS,
        )
        self.document = None
        self.preset_id = None
        self.profile_index = 0
        self._loading = False
        self.selected_category = "all"
        self.category_buttons = {}
        self.chk_all_versions = None
        self.lbl_catalog_stats = None
        self._is_dirty = False
        self.game_banner = None
        self.health_badges = {}
        self.health_verdict = None
        self.health_verdict_badge = None
        self.btn_health_test = None
        self._health_testing = False
        self.sw_auto_hostlist = None
        self.lbl_autohost_count = None
        self.btn_clear_autohost = None

    def create(self):
        self._loading = True
        _init_css()
        page, box = self.app.create_page_container(
            "Zapret2: Lua и профили",
            "Нативный nfqws2, пресеты Windows Zapret2 и Linux nftables. Изменения сохраняются отдельно от базы.",
        )
        self.container = page
        self.box = box

        # ================= 1. КАРТОЧКА ВЫБОРА ПРЕСЕТОВ И ФИЛЬТРОВ =================
        selector = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        selector.get_style_context().add_class("fluent-card")

        # Панель кнопок-фильтров в стиле fluent-pills
        filter_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        first_radio = None
        for cat_id, label in FILTER_CATEGORIES:
            if first_radio is None:
                btn = Gtk.RadioButton.new_with_label(None, label)
                first_radio = btn
            else:
                btn = Gtk.RadioButton.new_with_label_from_widget(first_radio, label)
            btn.set_mode(False)
            btn.get_style_context().add_class("filter-pill")
            btn.connect("toggled", self.on_category_toggled, cat_id)
            self.category_buttons[cat_id] = btn
            filter_box.pack_start(btn, False, False, 0)

        # По умолчанию активен фильтр "Все пресеты"
        if "all" in self.category_buttons:
            self.category_buttons["all"].set_active(True)
        selector.pack_start(filter_box, False, False, 0)

        # Поиск и выпадающий список пресетов
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.search = Gtk.SearchEntry()
        self.search.set_placeholder_text("Найти пресет...")
        self.search.connect("search-changed", self.refresh_catalog)
        row.pack_start(self.search, False, False, 0)
        self.preset_combo = Gtk.ComboBoxText()
        self.preset_combo.connect("changed", self.on_preset_selected)
        row.pack_start(self.preset_combo, True, True, 0)
        selector.pack_start(row, False, False, 0)

        # Переключатель показа всех версий и статистика каталога
        ver_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        self.chk_all_versions = Gtk.CheckButton(label="Показать все версии пресетов")
        self.chk_all_versions.set_active(False)
        self.chk_all_versions.connect("toggled", self.refresh_catalog)
        ver_row.pack_start(self.chk_all_versions, False, False, 0)

        self.lbl_catalog_stats = Gtk.Label(
            label=f"Каталог: {self.catalog.family_count} семейств · {self.catalog.total_count} версий",
            xalign=0,
        )
        self.lbl_catalog_stats.get_style_context().add_class("page-subtitle")
        ver_row.pack_start(self.lbl_catalog_stats, False, False, 0)
        selector.pack_start(ver_row, False, False, 0)

        # Заметный информационный баннер для игровых пресетов (game filter)
        self.game_banner = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.game_banner.get_style_context().add_class("game-warning-banner")
        lbl_warning = Gtk.Label(label=GAME_WARNING_TEXT, xalign=0)
        lbl_warning.set_line_wrap(True)
        self.game_banner.pack_start(lbl_warning, True, True, 0)
        self.game_banner.set_no_show_all(True)
        self.game_banner.set_visible(False)
        selector.pack_start(self.game_banner, False, False, 0)

        self.summary = Gtk.Label(xalign=0)
        self.summary.get_style_context().add_class("page-subtitle")
        selector.pack_start(self.summary, False, False, 0)

        actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._button(actions, "▶ Применить Zapret2", self.apply, True)
        self._button(actions, "✓ Проверить", self.validate)
        self._button(actions, "Импорт", self.import_preset)
        self._button(actions, "Экспорт", self.export_preset)
        selector.pack_start(actions, False, False, 0)
        box.pack_start(selector, False, False, 0)

        # ================= 2. КАРТОЧКА HEALTH CHECK (БЫСТРЫЙ ТЕСТ) =================
        health_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        health_card.get_style_context().add_class("fluent-card")

        h_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        h_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        lbl_h_title = Gtk.Label(label="⚡ Быстрый тест пресета (Health Check)", xalign=0)
        lbl_h_title.get_style_context().add_class("tile-value")
        lbl_h_sub = Gtk.Label(
            label="Экспресс-проверка доступности YouTube, GoogleVideo Stream, Discord и Rutracker",
            xalign=0,
        )
        lbl_h_sub.get_style_context().add_class("tile-title")
        h_info.pack_start(lbl_h_title, False, False, 0)
        h_info.pack_start(lbl_h_sub, False, False, 0)
        h_header.pack_start(h_info, True, True, 0)

        self.btn_health_test = Gtk.Button(label="Запустить экспресс-тест")
        self.btn_health_test.get_style_context().add_class("fluent-btn-primary")
        self.btn_health_test.set_valign(Gtk.Align.CENTER)
        self.btn_health_test.connect("clicked", self.run_health_check)
        h_header.pack_end(self.btn_health_test, False, False, 0)
        health_card.pack_start(h_header, False, False, 0)

        # Сетка сервисов
        grid = Gtk.Grid()
        grid.set_column_spacing(10)
        grid.set_row_spacing(8)
        grid.set_column_homogeneous(True)

        for idx, (name, _) in enumerate(HEALTH_TARGETS):
            tile = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
            tile.get_style_context().add_class("health-grid-tile")
            lbl_name = Gtk.Label(label=name, xalign=0)
            lbl_name.get_style_context().add_class("tile-title")
            badge = Gtk.Label(label="⚪ Ожидание теста", xalign=0)
            badge.get_style_context().add_class("badge-neutral")
            tile.pack_start(lbl_name, False, False, 0)
            tile.pack_start(badge, False, False, 0)
            self.health_badges[name] = badge
            col = idx % 2
            row_idx = idx // 2
            grid.attach(tile, col, row_idx, 1, 1)

        health_card.pack_start(grid, False, False, 0)

        v_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.health_verdict = Gtk.Label(label="Общий вердикт: тест не запускался", xalign=0)
        self.health_verdict.get_style_context().add_class("page-subtitle")
        v_row.pack_start(self.health_verdict, True, True, 0)
        self.health_verdict_badge = Gtk.Label(label="—")
        self.health_verdict_badge.get_style_context().add_class("badge-neutral")
        v_row.pack_end(self.health_verdict_badge, False, False, 0)
        health_card.pack_start(v_row, False, False, 0)

        box.pack_start(health_card, False, False, 0)

        # ================= 3. КАРТОЧКА AUTO-HOSTLIST =================
        autohost_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        autohost_card.get_style_context().add_class("fluent-card")

        ah_header = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        ah_info = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        lbl_ah_title = Gtk.Label(label="📋 Auto-Hostlist (Автоматический сбор доменов)", xalign=0)
        lbl_ah_title.get_style_context().add_class("tile-value")
        lbl_ah_sub = Gtk.Label(
            label="Автоматическое обнаружение блокировок ТСПУ и сбор доменов в runtime",
            xalign=0,
        )
        lbl_ah_sub.get_style_context().add_class("tile-title")
        ah_info.pack_start(lbl_ah_title, False, False, 0)
        ah_info.pack_start(lbl_ah_sub, False, False, 0)
        ah_header.pack_start(ah_info, True, True, 0)
        autohost_card.pack_start(ah_header, False, False, 0)

        sw_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        sw_label = Gtk.Label(label="Включить автодобавление заблокированных доменов (Auto-Hostlist)", xalign=0)
        sw_row.pack_start(sw_label, True, True, 0)
        self.sw_auto_hostlist = Gtk.Switch()
        self.sw_auto_hostlist.set_active(getattr(self.app, "enable_auto_hostlist", False))
        self.sw_auto_hostlist.connect("notify::active", self.on_auto_hostlist_toggled)
        self.sw_auto_hostlist.set_valign(Gtk.Align.CENTER)
        sw_row.pack_end(self.sw_auto_hostlist, False, False, 0)
        autohost_card.pack_start(sw_row, False, False, 0)

        ah_action_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.lbl_autohost_count = Gtk.Label(label="Захвачено доменов: 0", xalign=0)
        self.lbl_autohost_count.get_style_context().add_class("page-subtitle")
        ah_action_row.pack_start(self.lbl_autohost_count, True, True, 0)

        self.btn_clear_autohost = Gtk.Button(label="Очистить список автохостов")
        self.btn_clear_autohost.get_style_context().add_class("fluent-btn-danger")
        self.btn_clear_autohost.connect("clicked", self.on_clear_autohost_clicked)
        ah_action_row.pack_end(self.btn_clear_autohost, False, False, 0)
        autohost_card.pack_start(ah_action_row, False, False, 0)

        box.pack_start(autohost_card, False, False, 0)

        # ================= 4. КАРТОЧКА РЕДАКТОРА ПРОФИЛЕЙ =================
        profile_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        profile_card.get_style_context().add_class("fluent-card")
        profile_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self.profile_combo = Gtk.ComboBoxText()
        self.profile_combo.connect("changed", self.on_profile_selected)
        profile_row.pack_start(self.profile_combo, True, True, 0)
        self.enabled_switch = Gtk.Switch()
        self.enabled_switch.connect("notify::active", self.on_enabled)
        profile_row.pack_end(self.enabled_switch, False, False, 0)
        profile_row.pack_end(Gtk.Label(label="Включён"), False, False, 0)
        profile_card.pack_start(profile_row, False, False, 0)

        # Панель поиска и замены в тексте профиля
        search_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.ed_search_entry = Gtk.SearchEntry()
        self.ed_search_entry.set_placeholder_text("Поиск в профиле...")
        self.ed_search_entry.connect("search-changed", self._on_ed_search_changed)
        search_bar.pack_start(self.ed_search_entry, True, True, 0)

        btn_find = Gtk.Button(label="Найти")
        btn_find.connect("clicked", self._find_next)
        search_bar.pack_start(btn_find, False, False, 0)

        self.ed_replace_entry = Gtk.Entry()
        self.ed_replace_entry.set_placeholder_text("Заменить на...")
        search_bar.pack_start(self.ed_replace_entry, True, True, 0)

        btn_replace = Gtk.Button(label="Заменить")
        btn_replace.connect("clicked", self._replace_current)
        search_bar.pack_start(btn_replace, False, False, 0)

        btn_replace_all = Gtk.Button(label="Все")
        btn_replace_all.connect("clicked", self._replace_all)
        search_bar.pack_start(btn_replace_all, False, False, 0)
        profile_card.pack_start(search_bar, False, False, 0)

        scroller = Gtk.ScrolledWindow()
        scroller.set_size_request(-1, 260)
        if HAVE_GTK_SOURCE:
            self.buffer = GtkSource.Buffer()
            view = GtkSource.View.new_with_buffer(self.buffer)
            view.set_show_line_numbers(True)
            view.set_highlight_current_line(True)
        else:
            self.buffer = Gtk.TextBuffer()
            view = Gtk.TextView(buffer=self.buffer)
        view.set_monospace(True)
        view.get_style_context().add_class("log-view")
        self.buffer.connect("changed", self._on_buffer_changed)
        scroller.add(view)
        profile_card.pack_start(scroller, True, True, 0)

        edit_actions = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        self._button(edit_actions, "Сохранить профиль", self.save_profile, True)
        self._button(edit_actions, "Сохранить как свой пресет...", self.save_as_user_preset)
        self._button(edit_actions, "Перечитать", self.reload)
        self._button(edit_actions, "Сбросить мои правки", self.reset)
        profile_card.pack_start(edit_actions, False, False, 0)
        box.pack_start(profile_card, False, False, 0)

        # ================= 5. КАРТОЧКА АНАЛИЗА ЖУРНАЛА =================
        log_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        log_card.get_style_context().add_class("fluent-card")
        self._button(log_card, "Анализировать журнал nfqws2", self.analyze)
        self.analysis = Gtk.Label(xalign=0, selectable=True)
        self.analysis.set_line_wrap(True)
        log_card.pack_start(self.analysis, False, False, 0)
        box.pack_start(log_card, False, False, 0)

        self.update_autohost_count()
        self._loading = False
        self.refresh_catalog()
        return page

    @staticmethod
    def _button(box, label, callback, primary=False):
        button = Gtk.Button(label=label)
        if primary:
            button.get_style_context().add_class("fluent-btn-primary")
        else:
            button.get_style_context().add_class("fluent-btn-secondary")
        button.connect("clicked", callback)
        box.pack_start(button, False, False, 0)
        return button

    def on_category_toggled(self, btn, cat_id):
        if self._loading:
            return
        if btn.get_active() and self.selected_category != cat_id:
            self.selected_category = cat_id
            self.refresh_catalog()

    def refresh_catalog(self, *_):
        selected = Path(self.preset_id or getattr(self.app, "zapret2_preset", "Default (circular)")).name
        if not selected.endswith(".txt"):
            selected += ".txt"
        query = self.search.get_text().casefold().strip() if hasattr(self, "search") else ""
        only_latest = not (self.chk_all_versions and self.chk_all_versions.get_active())

        # Перезагружаем каталог с учетом возможных пользовательских пресетов
        self.catalog = PresetCatalog.load_from_directory(
            core.APP_DIR / "zapret2" / "presets" / "winws2_builtin",
            core.USER_PRESETS,
        )
        if hasattr(self, "lbl_catalog_stats") and self.lbl_catalog_stats:
            self.lbl_catalog_stats.set_text(
                f"Каталог: {self.catalog.family_count} семейств · {self.catalog.total_count} версий"
            )

        entries = self.catalog.filter(
            query=query,
            only_latest_per_family=only_latest,
        )

        items = []
        for entry in entries:
            is_custom = (core.USER_PRESETS / entry.id).is_file()
            match = False
            if self.selected_category == "all":
                match = True
            elif self.selected_category in ("recommended", "top") and "recommended" in entry.tags:
                match = True
            elif self.selected_category == "circular" and ("circular" in entry.tags or "circular" in entry.id.casefold()):
                match = True
            elif self.selected_category == "game" and (entry.game_filter or "game" in entry.tags):
                match = True
            elif self.selected_category == "custom" and is_custom:
                match = True

            if match:
                items.append(entry)

        self._loading = True
        self.preset_combo.remove_all()
        active_index = 0
        for index, entry in enumerate(items):
            display_title = entry.display_name
            if not only_latest and entry.version:
                display_title = f"{entry.family} — {entry.version}{' 🎮' if entry.game_filter else ''}"

            suffix = ""
            if "circular" in entry.tags and "circular" not in display_title.casefold():
                suffix += " [circular]"
            if (core.USER_PRESETS / entry.id).is_file():
                suffix += " [мой]"

            self.preset_combo.append(entry.id, display_title + suffix)
            if selected == entry.id:
                active_index = index

        if items:
            self.preset_combo.set_active(active_index)
        self._loading = False
        if items:
            self.load_preset(self.preset_combo.get_active_id())
        else:
            self.preset_id = None
            self.document = None
            if hasattr(self, "buffer"):
                self.buffer.set_text("")
            if hasattr(self, "summary"):
                self.summary.set_text("Пресеты не найдены по заданному фильтру.")
            if hasattr(self, "game_banner") and self.game_banner:
                self.game_banner.set_visible(False)

    def load_preset(self, preset_id):
        if not preset_id:
            return
        try:
            self.preset_id = preset_id
            self.document = core.PresetDocument.parse(core.load_preset(preset_id))
            self.refresh_profiles(0)
            custom = (core.USER_PRESETS / Path(preset_id).name).is_file()
            self.summary.set_text(
                f"Профилей: {len(self.document.profiles)}. "
                + ("Пользовательская копия." if custom else "Встроенный пресет, правки создадут копию.")
            )
            # Отображение баннера для игровых пресетов
            is_game = (
                "(game filter)" in preset_id.casefold()
                or "game" in preset_id.casefold()
                or core.categorize_preset(preset_id) == "game"
            )
            if hasattr(self, "game_banner") and self.game_banner:
                self.game_banner.set_visible(is_game)
        except Exception as exc:
            self.app.show_dialog("Ошибка пресета", str(exc))

    def refresh_profiles(self, selected=0):
        self._loading = True
        self.profile_combo.remove_all()
        for profile in self.document.profiles:
            state = "" if profile.enabled else " [выключен]"
            self.profile_combo.append(str(profile.index), f"{profile.index + 1}. {profile.name}{state}")
        if self.document.profiles:
            self.profile_combo.set_active(min(selected, len(self.document.profiles) - 1))
        self._loading = False
        self.show_profile(min(selected, max(0, len(self.document.profiles) - 1)))

    def show_profile(self, index):
        if not self.document or not self.document.profiles:
            self.buffer.set_text("")
            self._is_dirty = False
            return
        self.profile_index = index
        profile = self.document.profiles[index]
        self._loading = True
        self.enabled_switch.set_active(profile.enabled)
        self.buffer.set_text(self.document.profile_text(index))
        self._is_dirty = False
        self._loading = False

    def _on_buffer_changed(self, _):
        if not self._loading:
            self._is_dirty = True

    def _confirm_discard_dirty(self) -> bool:
        if not self._is_dirty:
            return True
        dialog = Gtk.MessageDialog(
            transient_for=getattr(self.app, "window", None),
            flags=0,
            message_type=Gtk.MessageType.WARNING,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Имеются несохранённые изменения!",
        )
        dialog.format_secondary_text(
            "В текущем профиле есть несохранённые правки. Отменить их и переключиться?"
        )
        resp = dialog.run()
        dialog.destroy()
        if resp == Gtk.ResponseType.YES:
            self._is_dirty = False
            return True
        return False

    def on_preset_selected(self, combo):
        if not self._loading:
            if not self._confirm_discard_dirty():
                self._loading = True
                combo.set_active_id(self.preset_id)
                self._loading = False
                return
            self.load_preset(combo.get_active_id())

    def on_profile_selected(self, combo):
        if not self._loading and combo.get_active_id() is not None:
            if not self._confirm_discard_dirty():
                self._loading = True
                combo.set_active_id(str(self.profile_index))
                self._loading = False
                return
            self.show_profile(int(combo.get_active_id()))

    def _save_document(self):
        core.save_user_preset(self.preset_id, self.document.text())
        self.document = core.PresetDocument.parse(core.load_preset(self.preset_id))

    def on_enabled(self, switch, _):
        if self._loading or not self.document:
            return
        try:
            enabled = switch.get_active()
            if not enabled and sum(p.enabled for p in self.document.profiles) == 1:
                raise core.PresetError("Нельзя выключить последний активный профиль")
            self.document.set_profile_enabled(self.profile_index, enabled)
            self._save_document()
            self._is_dirty = False
            self.refresh_profiles(self.profile_index)
        except Exception as exc:
            self._loading = True
            switch.set_active(not switch.get_active())
            self._loading = False
            self.app.show_dialog("Не удалось изменить профиль", str(exc))

    def save_profile(self, _):
        try:
            start = self.buffer.get_start_iter()
            text = self.buffer.get_text(start, self.buffer.get_end_iter(), False)
            self.document.replace_profile(self.profile_index, text)
            self._save_document()
            self._is_dirty = False
            self.refresh_profiles(self.profile_index)
            self.summary.set_text("Профиль сохранён в пользовательской копии. Нажми «Проверить» или «Применить».")
        except Exception as exc:
            self.app.show_dialog("Не удалось сохранить профиль", str(exc))

    def save_as_user_preset(self, _):
        dialog = Gtk.Dialog(
            title="Сохранить как свой пресет",
            transient_for=getattr(self.app, "window", None),
            flags=0,
        )
        dialog.add_buttons(
            Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
            Gtk.STOCK_SAVE, Gtk.ResponseType.OK,
        )
        box = dialog.get_content_area()
        box.set_spacing(8)
        box.set_margin_start(16)
        box.set_margin_end(16)
        box.set_margin_top(16)
        box.set_margin_bottom(16)

        lbl = Gtk.Label(label="Введите имя для нового пресета:", xalign=0)
        box.pack_start(lbl, False, False, 0)
        entry = Gtk.Entry()
        current_stem = Path(self.preset_id or "custom_preset").stem
        entry.set_text(f"{current_stem}_custom")
        box.pack_start(entry, False, False, 0)
        dialog.show_all()

        resp = dialog.run()
        name = entry.get_text().strip()
        dialog.destroy()

        if resp == Gtk.ResponseType.OK and name:
            try:
                start = self.buffer.get_start_iter()
                text = self.buffer.get_text(start, self.buffer.get_end_iter(), False)
                self.document.replace_profile(self.profile_index, text)

                doc_text = self.document.text()
                saved_path = core.save_user_preset(name, doc_text)
                self._is_dirty = False
                unsupported = core.check_preset_unsupported_options(doc_text)
                self.preset_id = saved_path.name
                self.refresh_catalog()
                self.preset_combo.set_active_id(saved_path.name)
                msg = f"Пресет успешно сохранён как '{saved_path.name}'."
                if unsupported:
                    msg += f"\nВнимание: параметры WinDivert игнорируются на Linux:\n" + "\n".join(unsupported[:5])
                self.summary.set_text(msg)
            except Exception as exc:
                self.app.show_dialog("Ошибка сохранения", str(exc))

    def _on_ed_search_changed(self, entry):
        pass

    def _find_next(self, _=None):
        query = self.ed_search_entry.get_text()
        if not query:
            return
        cursor = self.buffer.get_iter_at_mark(self.buffer.get_insert())
        found = cursor.forward_search(query, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
        if not found:
            start = self.buffer.get_start_iter()
            found = start.forward_search(query, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
        if found:
            match_start, match_end = found
            self.buffer.select_range(match_start, match_end)

    def _replace_current(self, _=None):
        if not self.buffer.get_has_selection():
            self._find_next()
            return
        start, end = self.buffer.get_selection_bounds()
        rep = self.ed_replace_entry.get_text()
        self.buffer.begin_user_action()
        self.buffer.delete(start, end)
        self.buffer.insert(start, rep)
        self.buffer.end_user_action()
        self._find_next()

    def _replace_all(self, _=None):
        query = self.ed_search_entry.get_text()
        rep = self.ed_replace_entry.get_text()
        if not query:
            return
        start = self.buffer.get_start_iter()
        self.buffer.begin_user_action()
        count = 0
        while True:
            found = start.forward_search(query, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
            if not found:
                break
            m_start, m_end = found
            self.buffer.delete(m_start, m_end)
            self.buffer.insert(m_start, rep)
            start = m_start
            start.forward_chars(len(rep))
            count += 1
        self.buffer.end_user_action()
        self.summary.set_text(f"Заменено вхождений: {count}")

    def apply(self, _):
        if not self.preset_id:
            return
        self.app.zapret2_preset = self.preset_id
        self.app.engine_mode = "nfqws2"
        self.app.save_config()
        if hasattr(self.app, "combo_engine_mode"):
            self.app.combo_engine_mode.set_active_id("nfqws2")
        self.app.update_top_tile_mode()
        self.app.start_engine()

    def validate(self, _):
        if not self.preset_id:
            return
        self.summary.set_text("Проверка nfqws2 --dry-run...")
        preset_id = self.preset_id
        iface = self.app.active_iface

        def worker():
            try:
                with tempfile.TemporaryDirectory(prefix="zapret2-gui-check-") as directory:
                    metadata = core.prepare_runtime(preset_id, Path(directory), self._real_iface(iface))
                warnings = "\n".join(metadata["warnings"])
                message = f"Пресет принят nfqws2. Профилей: {metadata['profiles']}."
                if warnings:
                    message += "\n" + warnings
            except Exception as exc:
                message = str(exc)
            GLib.idle_add(self.summary.set_text, message)

        threading.Thread(target=worker, daemon=True).start()

    @staticmethod
    def _real_iface(iface):
        if iface and iface != "any":
            return iface
        result = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True)
        fields = result.stdout.split()
        if "dev" not in fields:
            raise core.PresetError("Не найден интерфейс default-маршрута")
        return fields[fields.index("dev") + 1]

    def reload(self, _):
        self.load_preset(self.preset_id)

    def reset(self, _):
        core.reset_user_preset(self.preset_id)
        self.load_preset(self.preset_id)

    def import_preset(self, _):
        dialog = Gtk.FileChooserDialog(
            title="Импорт пресета Zapret2", parent=self.app if isinstance(self.app, Gtk.Window) else None, action=Gtk.FileChooserAction.OPEN,
        )
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Импорт", Gtk.ResponseType.ACCEPT)
        file_filter = Gtk.FileFilter()
        file_filter.set_name("Пресеты Zapret2 (*.txt)")
        file_filter.add_pattern("*.txt")
        dialog.add_filter(file_filter)
        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()
        if response != Gtk.ResponseType.ACCEPT or not filename:
            return
        try:
            path = core.import_preset(Path(filename))
            self.preset_id = path.name
            self.search.set_text("")
            self.refresh_catalog()
        except Exception as exc:
            self.app.show_dialog("Ошибка импорта", str(exc))

    def export_preset(self, _):
        if not self.preset_id:
            return
        dialog = Gtk.FileChooserDialog(
            title="Экспорт пресета Zapret2", parent=self.app if isinstance(self.app, Gtk.Window) else None, action=Gtk.FileChooserAction.SAVE,
        )
        dialog.add_buttons("Отмена", Gtk.ResponseType.CANCEL, "Сохранить", Gtk.ResponseType.ACCEPT)
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_name(Path(self.preset_id).name)
        response = dialog.run()
        filename = dialog.get_filename()
        dialog.destroy()
        if response == Gtk.ResponseType.ACCEPT and filename:
            try:
                Path(filename).write_text(self.document.text(), encoding="utf-8")
            except OSError as exc:
                self.app.show_dialog("Ошибка экспорта", str(exc))

    def analyze(self, _):
        report = core.analyze_log(Path("/tmp/zapret-gui.log"))
        sections = [report["summary"]]
        if report["strategies"]:
            strategies = ", ".join(f"{key}: {value}" for key, value in report["strategies"].items())
            sections.append("Выбор стратегий: " + strategies)
        if report["errors"]:
            sections.append("Последние ошибки:\n" + "\n".join(report["errors"][-8:]))
        elif report["tail"]:
            sections.append("Ошибок в последнем фрагменте не найдено.")
        self.analysis.set_text("\n\n".join(sections))

    # ================= HEALTH CHECK METHODS =================
    def run_health_check(self, _=None):
        if self._health_testing:
            return
        self._health_testing = True
        self.btn_health_test.set_sensitive(False)
        self.btn_health_test.set_label("⏳ Тестирование...")
        for badge in self.health_badges.values():
            badge.set_text("⏳ Проверка...")
            for cls in ("badge-ok", "badge-bad", "badge-warn"):
                badge.get_style_context().remove_class(cls)
            badge.get_style_context().add_class("badge-neutral")
        self.health_verdict.set_text("Общий вердикт: выполняется экспресс-тест...")
        self.health_verdict_badge.set_text("⏳ Тест")
        for cls in ("badge-ok", "badge-bad", "badge-warn"):
            self.health_verdict_badge.get_style_context().remove_class(cls)
        self.health_verdict_badge.get_style_context().add_class("badge-neutral")

        def worker():
            results = []
            for name, url in HEALTH_TARGETS:
                is_ok, dt, reason = check_url_health(url)
                results.append((name, is_ok, dt, reason))
                GLib.idle_add(self._update_health_badge, name, is_ok, dt, reason)
            GLib.idle_add(self._finish_health_test, results)

        threading.Thread(target=worker, daemon=True).start()

    def _update_health_badge(self, name, is_ok, dt, reason):
        badge = self.health_badges.get(name)
        if not badge:
            return
        for cls in ("badge-neutral", "badge-ok", "badge-bad", "badge-warn"):
            badge.get_style_context().remove_class(cls)
        if is_ok:
            badge.set_text(f"🟢 OK ({dt} ms)")
            badge.get_style_context().add_class("badge-ok")
        else:
            badge.set_text(f"🔴 Ошибка ({reason})")
            badge.get_style_context().add_class("badge-bad")

    def _finish_health_test(self, results):
        self._health_testing = False
        self.btn_health_test.set_sensitive(True)
        self.btn_health_test.set_label("⚡ Запустить экспресс-тест")
        ok_count = sum(1 for _, is_ok, _, _ in results if is_ok)
        total = len(results)
        if ok_count == total:
            verdict = "Пресет работает отлично"
            badge_text = "🟢 Пресет работает отлично"
            cls = "badge-ok"
        elif ok_count > 0:
            verdict = f"Частичный доступ ({ok_count}/{total})"
            badge_text = "🟡 Частичный доступ"
            cls = "badge-warn"
        else:
            verdict = "Блокируется ТСПУ"
            badge_text = "🔴 Блокируется ТСПУ"
            cls = "badge-bad"

        self.health_verdict.set_text(f"Общий вердикт: «{verdict}»")
        self.health_verdict_badge.set_text(badge_text)
        for c in ("badge-neutral", "badge-ok", "badge-bad", "badge-warn"):
            self.health_verdict_badge.get_style_context().remove_class(c)
        self.health_verdict_badge.get_style_context().add_class(cls)

    # ================= AUTO-HOSTLIST METHODS =================
    def update_autohost_count(self):
        stats = core.get_auto_hostlist_stats()
        count = stats.get("count", 0)
        if hasattr(self, "lbl_autohost_count") and self.lbl_autohost_count:
            self.lbl_autohost_count.set_text(f"Захвачено доменов: {count}")

    def on_auto_hostlist_toggled(self, switch, _):
        if self._loading:
            return
        active = switch.get_active()
        self.app.enable_auto_hostlist = active
        if hasattr(self.app, "save_config"):
            self.app.save_config()
        if getattr(self.app, "is_running", False) and hasattr(self.app, "restart_engine"):
            self.app.restart_engine()

    def on_clear_autohost_clicked(self, _):
        parent_window = self.app if isinstance(self.app, Gtk.Window) else None
        dialog = Gtk.MessageDialog(
            transient_for=parent_window,
            flags=0,
            message_type=Gtk.MessageType.QUESTION,
            buttons=Gtk.ButtonsType.YES_NO,
            text="Очистить список автохостов?",
        )
        dialog.format_secondary_text(
            "Вы действительно хотите удалить все автоматически собранные домены из Auto-Hostlist?"
        )
        response = dialog.run()
        dialog.destroy()
        if response == Gtk.ResponseType.YES:
            self.clear_autohostlist()

    def clear_autohostlist(self):
        core.clear_auto_hostlist()
        self.update_autohost_count()
