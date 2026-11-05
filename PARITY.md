# Таблица паритета (PARITY.md): Zapret 2 Windows vs Linux GUI

Этот документ — Single Source of Truth (SSOT) функционального и UX-паритета между Windows-оригиналом ([zapretdiscordyoutube/zapretgui](https://cwdnvtsqdc.zapret.moe/zapretdiscordyoutube/zapretgui), MIT) и портом для Linux (Arch / CachyOS).

Таблица ведётся непрерывно и обновляется по результатам каждого этапа.

---

## 🧭 Статус дорожной карты (Roadmap)

| Этап | Описание | Статус | Коммит | Примечания |
|:---:|---|:---:|:---:|---|
| **0** | **База, гигиена репозитория, лицензии, версионирование** | 🟢 Готово | chore(stage0): ... | `git init`, `.gitignore`, `version.py`, `LICENSE` (MIT), `NOTICE`, `PARITY.md` |
| **1** | **P0: Корректность и безопасность** | 🟡 Следующий | — | UDP ct-лимит, flock, watchdog, честный статус/UI, DNS rollback, /etc/hosts |
| **2** | **Паритет данных и моделей** | ⚪ В очереди | — | Нормализация каталога (семейства), единый источник пресетов, редактор |
| **3** | **Паритет UI/UX** | ⚪ В очереди | — | Fluent-структура GTK3, карточки, трей, онбординг, доступность |
| **9** | **Тесты и CI (для сделанного)** | ⚪ В очереди | — | Пирамида тестов, AST-стражи, GitHub Actions / Forgejo CI |
| **4** | **Оркестратор (автоподбор стратегий)** | ⚪ В очереди | — | Пакетный перебор 136 пресетов, скоринг, NetworkManager D-Bus |
| **5** | **Диагностика и классификация** | ⚪ В очереди | — | Chrome-отпечаток (curl_cffi), классификация ТСПУ, QUIC-тест |
| **6** | **DNS, hosts и управление списками** | ⚪ В очереди | — | DoH/DoT провайдеры, карточки хостов сервисов, семантика `!домен` |
| **7** | **Обновления, целостность, журнал** | ⚪ В очереди | — | Manifest signature, atomic swap, support bundle, разбор логов |
| **8** | **Telegram Proxy (опционально, за флагом)** | ⚪ В очереди | — | Внешний mtg / tg-ws-proxy обёртка |
| **10** | **Упаковка, релизы, документация** | ⚪ В очереди | — | PKGBUILD, .desktop, system-wide vs portable, docs |

---

## 📊 Матрица функционального паритета

| Фича | В оригинале (Windows) | У нас (Linux) | Статус | Где код |
|---|---|---|:---:|---|
| **Движок nfqws2 (Zapret 2)** | Нативный WinWS2 с Lua и профилями | `nfqws2` через NFQUEUE 201 с Lua | 🟢 Есть | `zapret2_core.py`, `engine.sh` |
| **Резервный движок nfqws v1** | WinWS v1 | `nfqws` v72.13 через NFQUEUE 200 | 🟢 Есть | `engine.sh:505` |
| **SOCKS5 прокси (tpws)** | tpws Windows | `tpws` 127.0.0.1:1080 | 🟢 Есть | `engine.sh:455` |
| **Каталог 136 пресетов** | 136 txt-пресетов Flowseal | 136 txt-пресетов | 🟡 Частично | `zapret2/presets/winws2_builtin/`, требуется нормализация в каталоге |
| **Адаптер WinDivert → Firewall** | WinDivert драйвер ядра | nftables транслятор правил | 🟡 Частично | `zapret2_core.py:render_nftables` (исправляется UDP в Этапе 1) |
| **Поддержка Discord Voice / STUN** | WinDivert raw UDP port ranges | nftables unmetered voice | 🟡 Частично | Баг широких портов `443-65535` исправляется в 1.1 |
| **Редактор профилей пресета** | Включение/отключение `--skip`, редактирование | Базовый Gtk.TextView, `--skip` | 🟡 Частично | `zapret2_ui.py`, расширение в Этапе 2 |
| **Автоподбор пресетов** | Оркестратор по полному каталогу | Примитивный перебор 4 пресетов | 🟡 Частично | Будет заменён на полноценный `orchestra/` (Этап 4) |
| **Auto-Hostlist (сбор доменов)** | Встроенный перехват nfqws2 | `zapret2_core.py:get_auto_hostlist_domains` | 🟢 Есть | `zapret2_core.py`, `zapret2_ui.py` |
| **Синхронизация и обновления** | Автообновление через GitHub/Forgejo | 4 зеркала (git2/git3/mos/flic), SHA256 | 🟢 Есть | `updater.py` |
| **Health Check и автолечение** | Служба самовосстановления | Демон `healer.py` | 🟡 Частично | Доработка до строгого FSM в Этапе 1 и 4 |
| **Реалистичные пробы (TLS fingerprint)** | Браузерные отпечатки | urllib (Python fingerprint) | 🟡 Частично | Миграция на `curl_cffi` (Chrome TLS) в Этапе 5 |
| **Классификация блокировок ТСПУ** | Разбор причин (SNI, IP, заглушка) | Базовый HTTP-код/ошибка | 🟡 Частично | Модуль `diagnostics/classify.py` в Этапе 5 |
| **DNS DoH / DoT менеджер** | DoH / DoT, провайдеры | `systemd-resolved` drop-in | 🟡 Частично | Баг отката после blockcheck2 исправляется в 1.5 |
| **Smart Hosts (/etc/hosts)** | Редактирование `hosts` Windows | `/etc/hosts` через `engine.sh` | 🟡 Частично | Замена опасного sed на безопасную атомарную запись в 1.7 |
| **Трей и уведомления** | Win32 Tray Icon + меню | AyatanaAppIndicator3 / GTK Tray | 🟡 Частично | Доведение до полного паритета меню в Этапе 3 |
| **Управление привилегиями** | Windows UAC | Polkit `moe.zapret.gui.policy` + pkexec | 🟢 Есть | `moe.zapret.gui.policy`, `engine.sh` |
| **Флаг `--version` / CLI** | CLI флаги версии и режима | `--version`, `-v`, `--minimized` | 🟢 Есть | `version.py`, `main.py` |
| **WinDivert raw packet injection** | Поддерживается ядром Windows | Неприменимо на Linux | ⚪ Неприменимо | Заменено на Linux `nftables` + `NFQUEUE` (архитектурный аналог) |
| **Windows Registry / Defender bypass** | Запись в реестр, исключения Defender | Неприменимо на Linux | ⚪ Неприменимо | На Linux используются polkit и systemd |

---

## 📜 Лицензии компонентов и upstream-ассетов

| Компонент / Директория | Лицензия | Правообладатель | Роль в проекте |
|---|:---:|---|---|
| **Код Linux GUI (корень)** | **MIT** | 2026 Zapret GUI Linux Contributors | Основное приложение, GTK3 интерфейс, адаптеры |
| **Поведение и алгоритмы** | **MIT** | 2025-2026 censorliber, bol-van, Flowseal | Заимствованные алгоритмы из `zapretgui` (см. `NOTICE`) |
| **`zapret2/presets/`** | **MIT** | Flowseal, censorliber | Набор из 136 пресетов Zapret2 |
| **`zapret2/lua/`** | **MIT** | bol-van, censorliber | Скрипты десинхронизации Zapret2 Lua |
| **`fake/`** | **MIT / Public Domain** | bol-van, censorliber | Бинарные пакеты ClientHello, QUIC, STUN |
| **`lists/`** | **Public Domain / CC0** | Сообщество Zapret | Списки заблокированных доменов и IP |
| **`zapret` / `nfqws` бинарники** | **MIT** | bol-van (https://github.com/bol-van/zapret) | Базовый DPI десинхронизатор |
| **`zapret2/windivert.filter`** | **LGPL-3.0 / GPL-2.0** | Basil (WinDivert) | Документация и эталонные фильтры для адаптера |

---

## 🛡️ Отслеживание гипотез и False Positive

Каждый пункт ТЗ проверяется на реальном коде перед внесением изменений:

- **Этап 0:**
  - *Рассинхрон версий:* **Подтверждён.** Встречались `21.1.7` и `21.1.7.210` в `main.py` и `updater.py`. Устранён через единый `version.py`.
  - *Личные/мусорные файлы:* **Подтверждён.** Найдены `setup_disks.sh` (скрипт монтирования Steam NTFS дисков lilpanda101), `hosts.txt.bak`, `.codebase-memory/`. Изолированы в `.gitignore`.
