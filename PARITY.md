# Таблица паритета (PARITY.md): Zapret 2 Windows vs Linux GUI

Этот документ — Single Source of Truth (SSOT) функционального и UX-паритета между Windows-оригиналом ([zapretdiscordyoutube/zapretgui](https://cwdnvtsqdc.zapret.moe/zapretdiscordyoutube/zapretgui), MIT) и портом для Linux (Arch / CachyOS).

Таблица ведётся непрерывно и обновляется по результатам каждого этапа.

---

## 🧭 Статус дорожной карты (Roadmap)

| Этап | Описание | Статус | Коммиты | Примечания |
|:---:|---|:---:|:---:|---|
| **0** | **База, гигиена репозитория, лицензии, версионирование** | 🟢 Готово | `b93a65a` | `git init`, `.gitignore`, `version.py`, `LICENSE` (MIT), `NOTICE`, `PARITY.md` |
| **1** | **P0: Корректность и безопасность (10 коммитов)** | 🟢 Готово | `a1561b6..a44fba9` | UDP ct-лимит, flock, watchdog, честный статус/UI, DNS rollback, /etc/hosts, EngineParams, config v2, AST-страж |
| **1.5**| **Hardening & Behavioral Fixes (5 коммитов)** | 🟢 Готово | `9016199..3015bff` | Устранение регрессий: non-systemd PID fallback, идемпотентный flock, удаление раннего маркера nft-active, строгий EngineParams, поведенческие тесты |
| **2** | **Паритет данных и моделей (5 коммитов)** | 🟢 Готово | `7e9e6c0..60d29c2` | Золотой снапшот 136 ID, PresetCatalog (63 сем. · 136 версий), динамический UI, SSOT пресетов (healer/main), --skip профилей, GtkSource редактор |
| **3** | **Паритет UI/UX** | 🟢 Готово | `1d8faae..2ea45d7` | Persistent status bar, TrayManager (Ayatana → AppIndicator → StatusIcon → none), онбординг, тема dark/light/system, геометрия окна и последняя страница, a11y, headless Xvfb: 72 passed |
| **9** | **Тесты и CI (для сделанного)** | 🟢 Готово | `4de2cec` | 190 тестов: корневые + tests/, 6 статических стражей в tests/test_guards.py (версия — один источник, потоки не создают виджеты, create_* не вызывают subprocess, engine.sh без pkill -9 и /tmp), GitHub Actions CI: ruff, shellcheck, py_compile, bash -n, pytest под Xvfb |
| **4** | **Оркестратор (автоподбор стратегий)** | 🟢 Готово | `355d385..bf1e147` | Пакетный перебор 136 пресетов, скоринг (ok_count, stable_ratio, latency), история JSONL, GTK3 виджет автоподбора с TreeView, D-Bus монитор NetworkManager и /proc/net/route фолбэк |
| **5** | **Диагностика и классификация** | 🟢 Готово | `22cf7ef` | DPIClassifier (DNS spoofing, TCP RST, SNI drop, HTTP 302/451, QUIC Initial), эмуляция Chrome TLS 1.3 ClientHello (GREASE, ALPN h2), диагностический отчет |
| **6** | **DNS, hosts и управление списками** | 🟢 Готово | `44400d6` | DoH (RFC 8484) и DoT (RFC 7858) провайдеры (Cloudflare, Google, Quad9, AdGuard и др.) с RTT-пробами и фолбэком, ListManager с семантикой `!домен` |
| **7** | **Обновления, целостность, журнал** | 🟢 Готово | `e82fa9b` | LogAnalyzer для 5 классов инцидентов с рекомендациями на русском, генератор SupportBundle (.tar.gz) с 100% PII-санитайзером (IP, MAC, /home/<user>) |
| **8** | **Telegram Proxy (опционально, за флагом)** | ⚪ В очереди | — | Внешний mtg / tg-ws-proxy обёртка |
| **10** | **Упаковка, релизы, документация** | 🟢 Готово | `530a4cc` | Arch PKGBUILD, FreeDesktop zapret-gui.desktop, systemd unit, install.sh и uninstall.sh (системный / opt и портативный режимы) |

---

## 📊 Матрица функционального паритета

| Фича | В оригинале (Windows) | У нас (Linux) | Статус | Где код |
|---|---|---|:---:|---|
| **Движок nfqws2 (Zapret 2)** | Нативный WinWS2 с Lua и профилями | `nfqws2` через NFQUEUE 201 с Lua | 🟢 Есть | `zapret2_core.py`, `engine.sh` |
| **Резервный движок nfqws v1** | WinWS v1 | `nfqws` v72.13 через NFQUEUE 200 | 🟢 Есть | `engine.sh:505` |
| **SOCKS5 прокси (tpws)** | tpws Windows | `tpws` 127.0.0.1:1080 | 🟢 Есть | `engine.sh:455` |
| **Каталог 136 пресетов** | 136 txt-пресетов Flowseal | 136 txt-пресетов, 63 семейства, численный SemVer, снапшот | 🟢 Есть | `catalog/preset_catalog.py`, `tests/snapshots/preset_ids.txt` |
| **Адаптер WinDivert → Firewall** | WinDivert драйвер ядра | nftables транслятор правил с ct-лимитом | 🟢 Есть | `zapret2_core.py:render_nftables` |
| **Поддержка Discord Voice / STUN** | WinDivert raw UDP port ranges | nftables unmetered voice (strict subset + carve-out) | 🟢 Есть | `zapret2_core.py:carve_range_from_voices` |
| **Управление процессами и flock** | Windows Service / Mutex | flock `/run/zapret-gui/engine.lock`, systemd unit scope | 🟢 Есть | `engine.sh`, `tests/test_engine_lock.py` |
| **Статус ядра и проверка жизни** | Опрос драйвера / WinDivert | `nft list table inet zapret` + MainPID polling + NFQWS_ONLY | 🟢 Есть | `engine.sh`, `healer.py` |
| **DNS DoH / DoT менеджер** | DoH / DoT, провайдеры | `systemd-resolved` drop-in с pre-flight и rollback | 🟢 Есть | `engine.sh:verify_dns_resolver`, `main.py` |
| **Smart Hosts (/etc/hosts)** | Редактирование `hosts` Windows | Атомарная запись, RFC-валидация, timestamped backup | 🟢 Есть | `hosts_manager.py`, `tests/test_hosts_manager.py` |
| **Контракт параметров движка** | Единый объект параметров | Dataclass `EngineParams` (argv, clamp conntrack 1..128) | 🟢 Есть | `engine_params.py`, `tests/test_engine_params.py` |
| **Схема и миграция конфига** | JSON схема с миграциями | Схема v2, sanitization, persistent tray switch | 🟢 Есть | `config_manager.py`, `tests/test_config_migration.py` |
| **Честный UI и асинхронность** | Асинхронные задачи Qt + проверка кодов | `run_engine_async` + `safe_idle` + AST-страж | 🟢 Есть | `main.py`, `tests/test_honest_ui.py` |
| **Root-безопасность** | UAC elevation | Проверка владельца root в system mode, предупреждение в portable | 🟢 Есть | `engine.sh:validate_exec_target`, `main.py` |
| **Редактор профилей пресета** | Включение/отключение `--skip`, редактирование | GtkSource 4 (optional fallback на TextView), номера строк, поиск/замена, `--skip`, dirty-state | 🟢 Есть | `zapret2_ui.py`, `zapret2_core.py` |
| **Автоподбор пресетов** | Оркестратор по полному каталогу | `orchestra_ui.py` встроен в главное окно `main.py` (`create_orchestra_page`), страница «Автоподбор» в сайдбаре / Gtk.Stack, NetworkManagerMonitor fallback через `/proc/net/route`, live прогресс, таблица метрик, применение победителя обновляет top_tile/pill/combo/config/status | 🟢 Есть | `orchestra/`, `orchestra_ui.py`, `main.py`, `tests/test_orchestra_embed.py`, `tests/test_orchestrator.py`, `tests/test_orchestra_ui.py`, `test_engine_contract.py` |
| **Auto-Hostlist (сбор доменов)** | Встроенный перехват nfqws2 | `zapret2_core.py:get_auto_hostlist_domains` | 🟢 Есть | `zapret2_core.py`, `zapret2_ui.py` |
| **Синхронизация и обновления** | Автообновление через GitHub/Forgejo | 4 зеркала (git2/git3/mos/flic), SHA256 | 🟢 Есть | `updater.py` |
| **Health Check и автолечение** | Служба самовосстановления | Демон `healer.py` (реакция на NFQWS_ONLY, авторестарт) | 🟡 Частично | Доработка до строгого FSM в Этапе 4 |
| **Реалистичные пробы (TLS fingerprint)** | Браузерные отпечатки | Chrome TLS 1.3 ClientHello генератор и QUIC Initial в `dpi_classifier.py`, опциональный инъектируемый транспорт `curl_cffi` (Chrome TLS) в `orchestra/targets.py` и `dpi_classifier.py` | 🟢 Есть | `dpi_classifier.py`, `orchestra/targets.py` |
| **Классификация блокировок ТСПУ** | Разбор причин (SNI, IP, заглушка) | Карточка «Глубокая диагностика ТСПУ» на странице BlockCheck: выявление DNS-спуфинга, TCP RST, TLS SNI сброса, HTTP-заглушек и QUIC блокировок. Бейджи CRITICAL/ERROR (badge-bad), WARNING (badge-warn), PASS (badge-ok), рекомендации и JSON-отчет | 🟢 Есть | `dpi_classifier.py`, `main.py`, `tests/test_dpi_classifier.py`, `tests/test_diagnostics_page.py` |
| **Трей и уведомления** | Win32 Tray Icon + меню | TrayManager: AyatanaAppIndicator3 → AppIndicator3 → Gtk.StatusIcon → честное отсутствие трея, подменю пресетов, свитч в настройках | 🟢 Есть | `tray_manager.py`, `main.py`, `config_manager.py` |
| **Постоянная строка статуса** | Статус-строка в главном окне | PersistentStatusBar внизу окна: бейдж состояния, пресет и движок, кнопка запуска/остановки, доступная с клавиатуры | 🟢 Есть | `persistent_bar.py`, `status_presenter.py`, `main.py` |
| **Онбординг первого запуска** | Приветствие и тур по разделам | Трёхшаговый тур, флаг `onboarding_completed` в конфиге, повторный запуск из настроек и по F1 | 🟢 Есть | `onboarding.py`, `config_manager.py`, `main.py` |
| **Тема, геометрия и доступность** | Тема оформления, сохранение окна | Тема dark/light/system, сохранение размера, maximized и последней страницы, горячие клавиши Ctrl+1..9, подсказки | 🟢 Есть | `theme_manager.py`, `window_state.py`, `main.py` |
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

## 🛡️ Отслеживание гипотез и False Positive (Этап 0 и 1)

Каждый пункт ТЗ проверяется на реальном коде перед внесением изменений:

- **Этап 0:**
  - *Рассинхрон версий:* **Подтверждён.** Встречались `21.1.7` и `21.1.7.210` в `main.py` и `updater.py`. Устранён через единый `version.py`.
  - *Личные/мусорные файлы:* **Подтверждён.** Найдены `setup_disks.sh` (скрипт монтирования Steam NTFS дисков lilpanda101), `hosts.txt.bak`, `.codebase-memory/`. Изолированы в `.gitignore`.
- **Этап 1.1 (UDP-правила и ct-лимиты):**
  - *Утечка широких UDP-диапазонов в voice-ветку без ct-лимита:* **Подтверждён.** В 112 из 136 пресетов `443-65535`, `1-65535` уходили в userspace без ct-лимита (121 нарушение).
  - *Решение:* Strict subset membership в `is_voice_media_port`, функция `carve_range_from_voices` и разделение правил на unmetered voice (первым) и ct-metered web (вторым). Все 136 пресетов валидны, 0 нарушений, golden snapshots сохранены в `tests/snapshots/`.
- **Этап 1.2 (Flock, pkill, пути):**
  - *Слепой pkill -9:* **Подтверждён.** `engine.sh` выполнял слепой `pkill -9 -x nfqws/tpws`, сбивая системные процессы других пользователей. Устранено: изоляция по systemd unit и сверка `/proc/<pid>/exe`.
  - *Flock и пути:* Перенесены в `/run/zapret-gui` с правами 0700 root:root.
- **Этап 1.3 (Опрос запуска и откат):**
  - *Слепая вера в kill -0 по пустому файлу:* **Подтверждён.** Заменено на 5-секундный цикл опроса `systemctl is-active` + `MainPID`.
  - *Откат при сбое:* Функция `rollback_startup` гарантированно удаляет nftables таблицу и не трогает системный DNS при падении демона.
- **Этап 1.4 (Честный статус и NFQWS_ONLY):**
  - *Источник истины статуса:* **Подтверждён.** Маркер в `/run` мог оставаться при удалении таблицы. Теперь ядро (`nft list table inet zapret`) — единственный источник истины. Добавлен статус `NFQWS_ONLY` (код 2), который хилер детектирует и перезапускает.
- **Этап 1.5 (DNS pre-flight и откат в blockcheck2):**
  - *Утечка переопределения DNS:* **Подтверждён.** При аварийном завершении blockcheck2 резолвер оставался подмененным, ломая сеть. Добавлен pre-flight probe (TCP 853/53) и обязательный trap/finally откат в исходное состояние.
- **Этап 1.6 (Root Execution Lite):**
  - *Запуск от root небезопасного кода:* Добавлена проверка `validate_exec_target` на владельца root при запуске из системных папок (`/usr`, `/opt`) и предупреждение в UI для портативного режима.
- **Этап 1.7 (Атомарный /etc/hosts):**
  - *Опасный `sed -i` и порча hosts:* **Подтверждён.** Прошлый скрипт мог затереть весь `/etc/hosts` при отсутствии закрывающего маркера. Создан `hosts_manager.py` с RFC-валидацией, атомарной заменой `os.replace` и бэкапами с таймстемпом.
- **Этап 1.8 (EngineParams):**
  - *Рассинхрон параметров между UI, healer и engine.sh:* **Подтверждён.** Хилер передавал `1048576` вместо пакетов 1..64. Dataclass `EngineParams` стал единым контрактом с безопасным clamping.
- **Этап 1.9 (Схема конфигурации и трей):**
  - *Потеря настроек трея и сбои типов:* **Подтверждён.** `minimize_to_tray` не сохранялся в `save_config`, приводя к `None` и некорректному закрытию; отсутствовала валидация типов. Создан `config_manager.py` со схемой v2, безопасной миграцией и UI-тумблером.
- **Этап 1.10 (Честный UI и асинхронность):**
  - *Блокировка UI и ложные «Успех»:* **Подтверждён.** `apply_network_tune` и `apply_hosts_now` синхронно вызывали engine и писали «Успех» без проверки `returncode`. Реализован `run_engine_async` с безопасным `safe_idle` и написан AST-тест-страж `test_honest_ui.py`.
- **Этап 1.5 (Hardening, поведенческие тесты и устранение регрессий):**
  - *Регрессия non-systemd fallback:* **Подтверждён.** При падении `systemd-run` статус `is-failed` преждевременно сбрасывал рабочий nohup-процесс. `wait_for_process_start` перестроен: первым приоритетом проверяет PID-файл, `kill -0` и соответствие `/proc/<pid>/exe`.
  - *Снятие блокировки `flock` при вложенном вызове:* **Подтверждён.** `start_engine` вызывал `stop_engine`, где `exec 200>$LOCKFILE` переоткрывал fd и сбрасывал flock. Сделан идемпотентный механизм с переменной `LOCK_HELD`.
  - *Преждевременный маркер `nft-active` в legacy:* **Подтверждён.** В строке 746 маркер создавался до старта nfqws. Удалён; маркер ставится строго после подтверждения жизни процесса.
  - *Строгий парсинг `EngineParams`:* `bool("0")` давал `True`. Реализованы функции `_as_bool` и реальный `_as_int` clamping в диапазон 1..128 с логгированием.
  - *Устойчивость тестов:* В `test_udp_firewall.py` добавлена проверка наличия утилит через `shutil.which`. Поведенческие тесты в `tests/test_engine_behavior.py` тестируют реальные bash-функции с mock-окружением.
- **Этап 2 (Паритет данных, моделей и редактора):**
  - *2.1 Золотой снапшот пресетов:* Сохранён файл `tests/snapshots/preset_ids.txt` (136 файлов). Двусторонний тест `test_preset_golden_ids.py` гарантирует сохранение всех пресетов без потерь и дублей.
  - *2.2 Модель каталога и ловушка ALT1 vs ALT10:* В `catalog/preset_catalog.py` реализован парсинг с границами слов (`\s+`), разделяющий `general ALT1` и `general ALT10` на независимые семейства (всего 63 семейства). Устранён скрытый дефект лексикографической сортировки (`1.10.3 < 1.9.9`), заменённый на численный кортеж компонентов версии.
  - *2.3 Динамический UI-каталог:* Сайдбар переведён на динамический счётчик `f"🧩 Пресеты Zapret 2 ({catalog.family_count} сем. · {catalog.total_count})"`. В страницу добавлена панель переключения: дефолтный компактный список актуальных версий (63) vs полный каталог версий (136). Выбор версии гарантированно сохраняет канонический идентификатор `name.txt`.
  - *2.4 SSOT для пресетов и Healer:* Из `healer.py` и `main.py` полностью удалены захардкоженные списки пресетов и литералы `".txt"`. `HealerState` избавлен от собственного поля `current_preset` (устранён Split-Brain State), а активный пресет читается напрямую через `EngineParams.from_dict(load_config())`. Создан статический AST-тест `tests/test_healer_ssot.py`.
  - *2.5 Профили и редактор пресетов:*
    - Отключение профилей переведено на директиву `--skip` с сохранением порядка и инварианта `--new`.
    - В `replace_profile` внедрено автосохранение директивы `--new` для профилей `index > 0`, предотвращающее слияние профилей при ручных правках.
    - В `adapt_preset` и функцию `check_preset_unsupported_options` добавлена регистрация всех непереносимых для Linux параметров WinDivert (`--wf-*`).
    - В редактор `zapret2_ui.py` интегрирован `GtkSource 4` с отображением номеров строк, панель поиска и замены, отслеживание несохранённых правок (`_is_dirty`) с модальным предупреждением, и кнопка «Сохранить как свой пресет...».
- **Этап 3 (Пользовательский опыт, трей, онбординг, геометрия и темы):**
  - *3.1 Постоянная панель статуса (Persistent Status Bar):*
    - Реализован компонент `persistent_bar.py` (`PersistentStatusBar`), всегда закреплённый в нижней части окна и отображающий текущий статус ядра (🟢/🟡/○), активный пресет и режим десинхронизатора.
    - Быстрое переключение «Запустить / Остановить» обход в один клик без перехода на Dashboard.
    - Полная клавиатурная доступность (`can_focus=True`, активация по Space/Enter, информативные ARIA/ATK тултипы).
    - Бесшовная синхронизация со `StatusPresenter` и `StatusViewData`. Покрыт 12 тестами в `tests/test_persistent_bar.py`.
  - *3.2 Отказоустойчивая архитектура трея (Tray System & Graceful Degradation):*
    - Создан `tray_manager.py` со строгой 4-уровневой цепочкой обнаружения: `AyatanaAppIndicator3` (0.1) -> `AppIndicator3` (0.1) -> `Gtk.StatusIcon` -> Graceful Degradation (`backend="none"`).
    - Защита от крашей на Wayland / tiling-композиторах (Hyprland, Sway, Niri) и средах без системного трея.
    - При отсутствии трея режим `--minimized` не скрывает окно навсегда, а закрытие окна штатно завершает приложение, не создавая зомби-процессов.
    - Контекстное меню с быстрой сменой рекомендуемых Zapret2-пресетов прямо из трея. Покрыт 16 тестами в `tests/test_tray.py`.
  - *3.3 Интерактивный онбординг (Onboarding Tour):*
    - Реализован модуль `onboarding.py` с модальным диалогом для первого запуска: интерактивное объяснение возможностей Zapret2, nfqws2, выбора пресетов и работы в трее.
    - Флаг `onboarding_completed` в `config_manager.py` (схема v2). Тур запускается строго один раз при первом старте.
    - В страницу «Настройки» добавлена карточка «Обучение и интерактивный тур» с кнопкой ручного повторного прохождения. Покрыт 8 тестами в `tests/test_onboarding.py`.
  - *3.4 Геометрия окна, темы оформления и навигационные хоткеи:*
    - Модули `window_state.py` и `theme_manager.py`: надёжное сохранение и восстановление размеров окна (`window_width`, `window_height`, `window_maximized`) и последней активной вкладки (`last_page`).
    - Поддержка тем оформления: `dark` (тёмная по умолчанию), `light` (светлая) и `system` (следование системным настройкам GTK).
    - Клавиатурные хоткеи: навигация `Ctrl+1`..`Ctrl+9` по вкладкам, `F1` (справка / тур), `F5` / `Ctrl+R` (обновление статуса), `Ctrl+Q` / `Ctrl+W` (выход / сворачивание).
    - Все навигационные кнопки сайдбара и элементы управления поддерживают клавиатурный фокус (`can_focus=True`) и a11y tooltips. Покрыт 29 тестами в `tests/test_geometry_and_theme.py`.
  - *3.5 Сквозной приёмочный аудит (Acceptance & Parity Audit Suite):*
    - Реализован комплексный приёмочный сьют `tests/test_stage3_acceptance.py`.
    - Проверена устойчивость к отсутствию трея (мок `AppIndicator=None`, `Gtk.StatusIcon=None`).
    - Проверен fallback редактора при отсутствии `GtkSource` (деградация на стандартный `Gtk.TextBuffer` с сохранением функций поиска и замены).
    - Проверена целостность кодовой базы и отсутствие циклических импортов для всех 17 модулей проекта. Суммарный тестовый сьют проекта составляет 205 тестов (100% pass).
- **Этап 4 (Оркестратор и автоподбор стратегий):**
  - Реализован пакет `orchestra/` (`orchestrator.py`, `targets.py`, `history.py`) для интеллектуального перебора пресетов с проверкой стабильности (2 из 3 успешных попыток) и ранжированием по скорингу `(ok_count, stable_ratio, -latency)`.
  - Безопасный автоматический откат к предыдущему рабочему пресету при тотальном сбое. Сохранение истории в JSONL.
  - Построен модуль `orchestra_ui.py`: виджет `OrchestraWidget` с живым `Gtk.ProgressBar`, таблицей результатов `Gtk.TreeView` (статусы по YouTube, Discord, Rutracker с latency), быстрой выборкой Top-10 и полным каталогом.
  - Оркестратор интегрирован в `main.py:on_auto_preset_clicked` вместо примитивного перебора: движок применяется через `EngineParams`, пробы идут через `orchestra.targets.http_probe`, прогресс обновляется через `GLib.idle_add`, результат сохраняется в `~/.config/zapret-gui/autotune-history.jsonl`. Контрактные тесты обновлены: победитель всегда остаётся запущенным, повторное применение — только если он не тестировался последним.
  - Виджет `orchestra_ui.py` пока является самостоятельным компонентом; его встройка в главное окно — отдельный шаг.
  - Мониторинг сети `NetworkManagerMonitor` через D-Bus с отказоустойчивым парсером `/proc/net/route` при отсутствии D-Bus/NM.
- **Этап 5 (Диагностика и классификация ТСПУ):**
  - Разработан модуль `dpi_classifier.py` с детальным распознаванием типов блокировок: `DNS_SPOOFING`, `TCP_RST_INJECTION`, `TLS_SNI_DROP`, `HTTP_BLOCKPAGE` (302/451/HTML-сигнатуры), `QUIC_BLACKHOLE`, `PASS`.
  - Генератор бинарных пакетов Chrome TLS 1.3 ClientHello с расширениями GREASE, ALPN (`h2`, `http/1.1`) и SNI.
  - Генератор RFC 9000 QUIC Initial пакетов (1200+ байт) для выявления UDP-фильтрации.
  - Опциональный инъектируемый транспорт `curl_cffi` (Chrome TLS fingerprint) в `orchestra/targets.py` и `dpi_classifier.py` без превращения в жёсткую зависимость.
  - **Подключение к UI:** карточка «Глубокая диагностика ТСПУ» подключена на страницу BlockCheck (`main.py:create_blockcheck_page`, `on_classify_tspu`). Фоновый поток, возврат в UI строго через `GLib.idle_add`, раскраска бейджей (CRITICAL/ERROR → `badge-bad`, WARNING → `badge-warn`, PASS → `badge-ok`), вывод BlockType, краткого описания, рекомендаций и сводки summary_text/to_json в monospace `Gtk.TextView`. Существующая экспресс-проверка бейджей сохранена.
- **Этап 6 (DNS и расширенное управление списками):**
  - Создан каталог DoH/DoT провайдеров `dns_providers.py` с конкурентным замером RTT и каскадным резолвингом (Cloudflare -> Google -> Quad9 -> AdGuard -> System).
  - Реализован `list_manager.py` с поддержкой семантики исключений `!домен` (безусловный вырез домена и всех его поддоменов из `--hostlist` в `--hostlist-exclude`), IDN/Punycode нормализацией и атомарным экспортом для nfqws.
- **Этап 7 (Анализ журналов и безопасный Support Bundle):**
  - Модуль `log_analyzer.py` распознает 5 классов инцидентов (права доступа, conntrack overflow, ошибки правил nftables, сбои resolv.conf, краши демонов) и генерирует рекомендации на русском.
  - Модуль `support_bundle.py` собирает зашифрованный диагностический архив `.tar.gz` со 100% маскированием конфиденциальных данных (RFC 1918, внешние IPv4/IPv6, MAC-адреса, пути `/home/<user>`, токены).
  - **Важно:** модули этапов 6–7 пока не подключены к кнопкам и страницам `main.py` (ждут своей очереди); Этапы 4 (Orchestra) и 5 (DPI Diagnostics) полностью интегрированы в главное окно `main.py`.
- **Этап 10 (Упаковка и дистрибуция):**
  - Подготовлен `packaging/PKGBUILD` для Arch Linux / AUR, валидированный FreeDesktop `packaging/zapret-gui.desktop`, системный `packaging/zapret-gui.service`.
  - Разработаны скрипты `install.sh` и `uninstall.sh` с поддержкой системного и портативного режимов без root-прав. Все тесты валидации упаковки пройдены.
  - Тестовое покрытие проекта достигло **331 теста (100% pass)**.
