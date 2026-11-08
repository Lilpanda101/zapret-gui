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
| **9** | **Тесты и CI (для сделанного)** | 🟢 Готово | `4de2cec..HEAD` | 449 тестов (в Windows-оригинале 689 py тестов): корневые + tests/, статические стражи в tests/test_guards.py, GitHub Actions CI под Xvfb |
| **4** | **Оркестратор (автоподбор стратегий)** | 🟢 Готово | `355d385..HEAD` | Перебор пресетов со скорингом (ok_count, stable_ratio, latency), история JSONL, адаптивное круговое обучение (lock 3 / unlock 2), фильтрация белых доменов РФ, группировка поддоменов, экспорт user learned-пресета без изменения presets/, виджет OrchestraWidget с показом locked/blocked и сбросом обучения |
| **5** | **Диагностика и классификация** | 🟢 Готово | `22cf7ef..HEAD` | DPIClassifier + diagnostics v2: разделение collect/judge, проверка DNS по SAN/issuer/сроку сертификата, пробы с настоящим SNI, example.com, без SNI, recased, max.ru/ya.ru/vk.com, окно 1B vs 1KB (wssize), исходы «через раз», «не до конца», «нет адреса», замер QUIC с ценой отказа и автопроверка после применения в UI |
| **6** | **DNS, hosts и управление списками** | 🟢 Готово | `44400d6` | DoH (RFC 8484) и DoT (RFC 7858) провайдеры (Cloudflare, Google, Quad9, AdGuard и др.) с RTT-пробами и фолбэком, ListManager с семантикой `!домен` |
| **7** | **Обновления, целостность, журнал** | 🟢 Готово | `e82fa9b` | LogAnalyzer, SupportBundle (.tar.gz), install_integrity (fast наличие+размер, full SHA-256 с retry заблокированных файлов) |
| **8** | **Telegram Proxy (сознательно не портировано)** | 🟢 Закрыто | — | Внешний tg-ws-proxy уже установлен и работает на системе, интеграция в GUI не требуется по решению владельца |
| **10** | **Упаковка, релизы, документация** | 🟢 Готово | `530a4cc` | Arch PKGBUILD, FreeDesktop zapret-gui.desktop, systemd unit, install.sh и uninstall.sh (системный / opt и портативный режимы) |
| **11** | **Паритет winws1, каталогов стратегий, профилей и дельта-обновлений** | 🟢 Готово | Текущий спринт | 165 winws1 пресетов (zapret2/presets/winws1_builtin), 876 стратегий (system/strategy_catalogs), шаблоны сервисных профилей (profile_manager.py), bsdiff дельта-апдейтер + rescue откат (updater.py), TLS 1.3 / QUIC Initial генератор фейков с Kyber (fake_generator.py), 479 passed тестов |

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
| **Автоподбор пресетов** | Оркестратор по полному каталогу с circular lock/unlock обучения | Полнофункциональный оркестратор (`orchestra/`, `orchestra_ui.py`) с скорингом 2 из 3, JSONL историей и откатом. Адаптивное круговое обучение: lock после 3 успехов, unlock после 2 сбоев, группировка поддоменов, игнорирование белых доменов РФ (*.ru, *.su, *.рф, vk.com и др.), экспорт в отдельный learned-пресет без изменения built-in пресетов. Виджет с индикацией locked/blocked и кнопкой сброса обучения | 🟢 Есть | `orchestra/`, `orchestra_ui.py`, `main.py`, `tests/test_orchestra_*.py` |
| **Auto-Hostlist (сбор доменов)** | Встроенный перехват nfqws2 | `zapret2_core.py:get_auto_hostlist_domains` | 🟢 Есть | `zapret2_core.py`, `zapret2_ui.py` |
| **Синхронизация и обновления** | Автообновление через GitHub/Forgejo | 4 зеркала (git2/git3/mos/flic), SHA256 | 🟢 Есть | `updater.py` |
| **Health Check и автолечение** | Служба самовосстановления | Строгий FSM демон `healer.py` (IDLE, CHECKING, RESTARTING, BACKOFF, DEGRADED, STOPPED, эксп. backoff, без busy-loop) | 🟢 Есть | `healer.py`, `tests/test_healer_fsm.py` |
| **Реалистичные пробы (TLS fingerprint)** | Браузерные отпечатки | Chrome TLS 1.3 ClientHello генератор и QUIC Initial в `dpi_classifier.py`; Chrome TLS транспорт `curl_cffi` с тихим fallback на urllib реально выбирается через `select_probe()` / `select_http_transport()` в `main.py` (автоподбор и глубокая диагностика ТСПУ) и отображается в UI | 🟢 Есть | `orchestra/targets.py`, `main.py`, `orchestra_ui.py`, `dpi_classifier.py` |
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
  - *Личные/мусорные файлы:* **Подтверждён.** Найдены локальные служебные файлы (`hosts.txt.bak`, `.codebase-memory/` и др.). Изолированы в `.gitignore`.
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
  - Реализован пакет `orchestra/` (`orchestrator.py`, `targets.py`, `history.py`, `learning.py`) для интеллектуального перебора пресетов с проверкой стабильности (2 из 3 успешных попыток) и ранжированием по скорингу `(ok_count, stable_ratio, -latency)`.
  - Безопасный автоматический откат к предыдущему рабочему пресету при тотальном сбое. Сохранение истории в JSONL.
  - Построен модуль `orchestra_ui.py`: виджет `OrchestraWidget` с живым `Gtk.ProgressBar`, таблицей результатов `Gtk.TreeView` (статусы по YouTube, Discord, Rutracker с latency), быстрой выборкой Top-10 и полным каталогом.
  - **Адаптивное круговое обучение (Circular Learning без копирования winws2 Lua):**
    - Изолированное хранилище статистики `LearningStore` (`orchestra_learning.json`) отдельно от настроек приложения.
    - Фиксация (lock) стратегии по целевому сервису после 3 успехов подряд, снятие (unlock) после 2 сбоев.
    - Автоматическая группировка поддоменов (`*.googlevideo.com` -> `googlevideo.com`, `*.discord.gg` -> `discord.com`).
    - Фильтрация белых российских доменов (`*.ru`, `*.su`, `*.рф`, `vk.com`, `ya.ru`, `gosuslugi.ru` и др. не перехватываются).
    - Обработка игнорируемых хостов (`is_ignored_target` для relay Telegram Proxy).
    - Результаты обучения экспортируются в отдельный пользовательский файл `learned_preset.conf`; встроенные пресеты в `presets/` остаются неприкосновенными.
    - В `OrchestraWidget` выведен блок статуса обучения с подсчетом зафиксированных (Locked) и заблокированных (Blocked) стратегий, а также кнопка «Сбросить обучение», сбрасывающая locks/blocks с полным сохранением истории запусков.
  - Оркестратор интегрирован в `main.py:on_auto_preset_clicked` и `main.py:create_orchestra_page`.
  - Мониторинг сети `NetworkManagerMonitor` через D-Bus с отказоустойчивым парсером `/proc/net/route` при отсутствии D-Bus/NM.
  - **Строгий FSM для AutoHealer:** ad-hoc цикл заменён на детерминированный конечный автомат `HealerFSM` (6 состояний: `IDLE`, `CHECKING`, `RESTARTING`, `BACKOFF`, `DEGRADED`, `STOPPED`). Экспоненциальный backoff с потолком (300с) без busy-loop на `threading.Event`, логгирование каждого перехода с причиной, полное сохранение контрактов `EngineParams` и CLI. Покрыт 19 тестами в `tests/test_healer_fsm.py`.
- **Этап 5 (Диагностика и классификация ТСПУ):**
  - Разработан модуль `dpi_classifier.py` с детальным распознаванием типов блокировок: `DNS_SPOOFING`, `TCP_RST_INJECTION`, `TLS_SNI_DROP`, `HTTP_BLOCKPAGE` (302/451/HTML-сигнатуры), `QUIC_BLACKHOLE`, `PASS`.
  - Генератор бинарных пакетов Chrome TLS 1.3 ClientHello с расширениями GREASE, ALPN (`h2`, `http/1.1`) и SNI.
  - Генератор RFC 9000 QUIC Initial пакетов (1200+ байт) для выявления UDP-фильтрации.
  - Реалистичный транспорт `curl_cffi` (полноценный Chrome 124 TLS fingerprint и User-Agent) с автоматическим выбором через `select_probe()` / `select_http_transport()` и тихим fallback на urllib в `orchestra/targets.py`, `main.py` (страница Orchestra и глубокая диагностика BlockCheck) и `orchestra_ui.py`.
  - **Этапы 5.2–5.7 (Глубокая диагностика с доказательством):**
    - `diagnostics/words.py`: единственный источник правды (SSOT) для текстов, статусов и рекомендаций BlockCheck без дублирования.
    - `diagnostics/collector.py` & `diagnostics/block_cause.py`: полное разделение сбора сетевых фактов (`NetworkFactCollector`, stagger 0.25с, пробы SNI, example.com, nameless, recased, allowed max.ru/ya.ru/vk.com, HTTP 80 451/stub, окно 1B x2 vs 1KB) и чистого судейства причин (`judge_cause`).
    - `diagnostics/verdict.py`: чистые функции судейства DNS (`judge_dns`: подмена решается по сертификату на системном IP, Anycast/CDN с разными IP не считаются подменой) и доступности сервиса (`judge_service`).
    - `diagnostics/domain_inspector.py`: аудит домена (сравнение DNS UDP/TCP/DoT/DoH, ICMP ping, TCP 443, TLS handshake с извлечением SAN/issuer/срока сертификата, судейство через `judge_dns` и `judge_service`, ASN и владелец сети).
    - `diagnostics/quic_analyzer.py`: замер задержек и доступности с QUIC и без QUIC с расчетом «цены отказа от QUIC», встроен в UI по кнопке «Замерить QUIC» (`main.py:on_quic_test_clicked`).
    - `diagnostics/apply_checker.py`: автоматическая автопроверка целевого ресурса после применения стратегии (`main.py:verify_connectivity_after_apply`) с модальным диалогом переключения стратегии в 1 клик при провале.
    - `diagnostics/blockcheck2_runner.py`: защищенный запуск `/opt/zapret2/blockcheck2.sh` с контролем returncode (без `|| true`), разбором стратегий из вывода, частичным логом при таймауте (код 124), статусом «Тест не завершен» и гарантированным восстановлением движка и системного DNS в блоке `finally`.
  - **Подключение к UI (`main.py`):**
    - На страницу BlockCheck в `on_classify_tspu` подключен пайплайн v2: DNS resolution -> реальный TLS handshake на системном IP (`extract_real_tls_cert`) -> `judge_dns` -> сбор сетевых фактов `NetworkFactCollector` -> `judge_cause` -> `judge_service`.
    - Интеграция `install_integrity`: `verify_fast()` вызывается перед запуском движка (`start_engine`), блокируя старт только при повреждении критических компонентов; `verify_full()` вызывается в фоне после синхронизации баз и по кнопке «Проверить целостность» на странице обновлений с детальным модальным отчетом.
    - Покрытие расширено до **449 тестов (100% pass)**, включая headless UI-тесты замера QUIC и автопроверки после применения (`tests/test_quic_apply_ui.py`), циклический lock/unlock обучения (`tests/test_orchestra_learning.py`), статический тест-страж по `engine.sh` (`tests/test_guards.py`).
- **Этап 6 (DNS и расширенное управление списками):**
  - Подключен каталог DoH/DoT провайдеров `dns_providers.py` к UI `main.py` (страница 6): динамический выбор провайдеров, фоновый замер RTT по кнопке «Замерить задержки», обновление результатов через `GLib.idle_add` и автоматическая сортировка карточек по RTT.
  - Строгая валидация провайдеров для `engine.sh` (`ENGINE_SUPPORTED_DNS = cloudflare, google, quad9, adguard, dns_ai, geohide, system`): провайдеры `mullvad`, `comss`, `nextdns` помечены как «не поддерживается движком» и отключены в радио-кнопках; `EngineParams` защищает от передачи неподдерживаемых id в `engine.sh` с fallback на `cloudflare`.
  - Подключен `ListManager` и компиляция списков к редактору хостов `main.py` (страница 7): поддержка путей `custom_hosts.txt`, `exclude.txt`, `lists/autohostlist.txt`, атомарное сохранение через `atomic_write_text` без нежелательной перезаписи файлов и без потери комментариев/строк.
  - Добавлено визуальное пояснение синтаксиса `!домен` (безусловное исключение домена и всех его поддоменов из hostlist с переносом в exclude) и кнопка ручной проверки компиляции списков.
  - Разработаны UI-тесты `tests/test_dns_ui.py` и `tests/test_list_ui.py` (8 тестов: mock probe_all_rtt, сортировка по задержке, блокировка неподдерживаемых провайдеров, сохранение active_dns, семантика !домен и поддоменов, атомарная запись).
- **Этап 7 (Анализ журналов и безопасный Support Bundle):**
  - Модуль `log_analyzer.py` распознает 5 классов инцидентов (права доступа, conntrack overflow, ошибки правил nftables, сбои resolv.conf, краши демонов) и генерирует рекомендации на русском.
  - Модуль `support_bundle.py` собирает диагностический архив `.tar.gz` со 100% маскированием конфиденциальных данных (RFC 1918, внешние IPv4/IPv6, MAC-адреса, пути `/home/<user>`, токены).
  - **Интеграция в UI (`main.py:create_logs_page`):**
    - Кнопка «Анализировать журнал»: запускает `analyze_log_file(LOG_FILE)` в фоновом потоке, отображает источник, число строк и список найденных инцидентов (критические выделяются бейджем `badge-bad`, ошибки и предупреждения — `badge-warn`, с указанием счетчика повторов, описания и рекомендаций).
    - Кнопка «Собрать support bundle»: перед сборкой выводит предупреждение о санитизации и необходимости ручного просмотра архива, запрашивает папку назначения через `Gtk.FileChooserDialog`, а затем асинхронно вызывает `create_support_bundle(output_dir=..., custom_log_path=..., custom_config_path=...)` с выводом полного пути к созданному архиву.
    - Потокобезопасность: фоновые потоки не создают Gtk-виджеты (строго через `GLib.idle_add`), кнопки блокируются на время выполнения, ошибки чтения и записи отображаются честно без ложных «Успех».
    - Интеграция и защита от утечек покрыты в `tests/test_support_ui.py` (9 тестов, гарантировано отсутствие создания файлов в домашней директории).
- **Этап 10 (Упаковка и дистрибуция):**
  - Подготовлен `packaging/PKGBUILD` для Arch Linux / AUR, валидированный FreeDesktop `packaging/zapret-gui.desktop`, системный `packaging/zapret-gui.service`.
  - Разработаны скрипты `install.sh` и `uninstall.sh` с поддержкой системного и портативного режимов без root-прав. Все тесты валидации упаковки пройдены.
  - Тестовое покрытие проекта достигло **449 тестов (100% pass)**.

---

## 🏁 Финальный аудит Definition of Done (Этап 4.5)

Таблица приёмочных критериев DoD по исходному ТЗ. Статус 🟢 выставляется строго при наличии подтверждённого кода и зелёного теста.

| Критерий DoD | Доказательство в коде | Доказательство тестом | Статус |
|---|---|---|:---:|
| **0. Единый источник версии и лицензия** | `version.py:__version__`, `LICENSE`, `NOTICE` | `tests/test_guards.py::test_version_single_source`, `test_no_hardcoded_version_literal_in_code` | 🟢 Готово |
| **1.1. Безопасность UDP firewall и ct-лимиты** | `zapret2_core.py:is_voice_media_port`, `carve_range_from_voices`, `render_nftables` | `test_udp_firewall.py::test_all_136_presets_udp_rules_strict_ct_or_voice` | 🟢 Готово |
| **1.2. Изоляция flock, безопасный PID и пути** | `engine.sh:acquire_lock` (fd 200), нет blind `pkill -9` | `tests/test_guards.py::test_engine_sh_keeps_stage1_hardening`, `tests/test_engine_behavior.py::test_acquire_lock_idempotency_keeps_flock_locked` | 🟢 Готово |
| **1.3. Контроль запуска ядра и откат при сбое** | `engine.sh:wait_for_process_start`, `rollback_startup` | `test_engine_lifecycle.py::test_wait_for_process_start_and_rollback_defined` | 🟢 Готово |
| **1.4. Честный статус ядра и исцеление NFQWS_ONLY** | `engine.sh:status_engine`, `healer.py:HealerFSM` | `tests/test_healer_fsm.py`, `test_engine_lifecycle.py::test_status_engine_inspects_nft_list_table` | 🟢 Готово |
| **1.5. Pre-flight DNS резолвера и trap rollback** | `engine.sh:verify_dns_resolver`, `engine.sh:run_blockcheck2` trap EXIT | `test_engine_lifecycle.py::test_dns_resolver_preflight_in_engine_sh` | 🟢 Готово |
| **1.6. Root privilege isolation и валидация путей** | `engine.sh:validate_exec_target` (проверка владельца root в системных путях) | `test_engine_lifecycle.py::test_validate_exec_target_security_in_engine_sh` | 🟢 Готово |
| **1.7. Атомарный /etc/hosts менеджер** | `hosts_manager.py:atomic_write_hosts`, RFC-валидация, timestamped backup | `test_hosts_manager.py::test_atomic_write_simulation_of_failure` | 🟢 Готово |
| **1.8. EngineParams dataclass и строгий clamping** | `engine_params.py:EngineParams`, `_as_int` (1..128), `_as_bool` | `tests/test_engine_params.py::test_as_int_clamping` | 🟢 Готово |
| **1.9. Config v2 со схемой, валидацией и треем** | `config_manager.py:load_config`, `save_config`, `validate_config_v2` | `tests/test_config_migration.py::test_migration_from_v1_legacy` | 🟢 Готово |
| **1.10. Честный асинхронный UI без зависаний** | `main.py:run_engine_async`, `safe_idle`, UI не вызывает `subprocess` | `tests/test_guards.py::test_thread_workers_do_not_create_widgets`, `tests/test_honest_ui.py` | 🟢 Готово |
| **2.1. Золотой снапшот 136 пресетов Flowseal** | `tests/snapshots/preset_ids.txt`, `zapret2/presets/` | `tests/test_preset_golden_ids.py::test_preset_catalog_ids_immutable` | 🟢 Готово |
| **2.2. Модель каталога пресетов (63 сем. / 136 версий)** | `catalog/preset_catalog.py:PresetCatalog`, численный SemVer | `tests/test_preset_catalog.py::test_parse_alt1_vs_alt10_different_families` | 🟢 Готово |
| **2.3. Двухуровневый выбор пресетов в UI** | `main.py:create_presets_page`, компактные vs все версии | `tests/test_ui_catalog.py::test_zapret2_ui_has_all_versions_toggle` | 🟢 Готово |
| **2.4. SSOT пресетов для Healer и главного окна** | Отсутствие захардкоженных списков, загрузка через `PresetCatalog` | `tests/test_healer_ssot.py::test_healer_no_hardcoded_preset_lists` | 🟢 Готово |
| **2.5. Редактор пресетов GtkSource с --skip профилями** | `zapret2_ui.py:PresetEditorDialog`, `replace_profile` `--skip` | `tests/test_preset_editor.py::test_profile_skip_toggle_preserves_structure` | 🟢 Готово |
| **3.1. Постоянная строка статуса (PersistentStatusBar)** | `persistent_bar.py:PersistentStatusBar`, a11y фокус и тултипы | `tests/test_persistent_bar.py::test_update_status_active` | 🟢 Готово |
| **3.2. 4-уровневый TrayManager с fallback** | `tray_manager.py:TrayManager` (Ayatana → AppIndicator → StatusIcon → none) | `tests/test_tray.py::TestTrayDetectionChain` | 🟢 Готово |
| **3.3. Интерактивный онбординг первого запуска** | `onboarding.py:OnboardingTourDialog`, повтор по F1 и из настроек | `tests/test_onboarding.py::test_should_show_onboarding_flags` | 🟢 Готово |
| **3.4. Темы оформления, геометрия окна, Ctrl+1..9** | `theme_manager.py:ThemeManager`, `window_state.py:WindowStateManager` | `tests/test_geometry_and_theme.py` | 🟢 Готово |
| **4.1. Автоподбор пресетов (Orchestrator)** | `orchestra/orchestrator.py:Orchestrator`, стабильность 2 из 3, откат | `tests/test_orchestrator.py::test_stability_requires_two_of_three` | 🟢 Готово |
| **4.2. Адаптивное circular обучение (lock 3 / unlock 2)** | `orchestra/learning.py:LearningStore`, lock после 3 успехов, unlock после 2 сбоев | `tests/test_orchestra_learning.py::test_strategy_lock_after_three_successes`, `test_strategy_unlock_after_two_failures` | 🟢 Готово |
| **4.3. Фильтрация белых доменов РФ и группировка поддоменов** | `orchestra/learning.py:is_russian_white_domain`, `group_subdomains`, `is_ignored_target` | `tests/test_orchestra_learning.py::test_russian_white_domains_filter`, `test_subdomain_grouping` | 🟢 Готово |
| **4.4. Экспорт карты обучения без изменения presets/** | `orchestra/learning.py:export_learned_rules` (пишет в learned_rules.conf) | `tests/test_orchestra_learning.py::test_learned_preset_does_not_touch_builtin_presets` | 🟢 Готово |
| **4.5. UI-индикация locked/blocked и сброс обучения** | `orchestra_ui.py:OrchestraWidget` (`lbl_locked_strategies`, `btn_reset_learning`) | `tests/test_orchestra_learning.py::test_orchestra_widget_learning_ui`, `test_reset_learning_preserves_history_store` | 🟢 Готово |
| **5.1. DPI классификатор с Chrome TLS 1.3 и QUIC** | `dpi_classifier.py:DPIClassifier`, `curl_cffi` / `urllib` селектор транспорта | `tests/test_dpi_classifier.py`, `tests/test_transport_selection.py` | 🟢 Готово |
| **5.2. Архитектура collect / judge без сети в судьях** | `diagnostics/collector.py:NetworkFactCollector`, `diagnostics/block_cause.py:judge_cause` | `tests/test_diagnostics_v2_and_integrity.py::test_judge_cause_reply_window_wssize` | 🟢 Готово |
| **5.3. DNS-судейство по сертификату и SAN на системном IP** | `diagnostics/collector.py:extract_real_tls_cert`, `diagnostics/verdict.py:judge_dns` | `tests/test_diagnostics_v2_ui.py::test_extract_real_tls_cert_mocked` | 🟢 Готово |
| **5.4. Замер QUIC и расчет цены отказа в UI** | `diagnostics/quic_analyzer.py:QuicAnalyzer`, `main.py:on_quic_test_clicked` | `tests/test_quic_apply_ui.py::test_on_quic_test_clicked_headless` | 🟢 Готово |
| **5.5. Автопроверка после «Применить» и переключение в 1 клик** | `diagnostics/apply_checker.py:ApplyChecker`, `main.py:verify_connectivity_after_apply` | `tests/test_quic_apply_ui.py::test_apply_checker_failure_shows_dialog_and_switches_preset` | 🟢 Готово |
| **5.6. BlockCheck2 без || true и с захватом returncode** | `engine.sh:run_blockcheck2` (`|| RC=$?`, `return $RC`), `blockcheck2_runner.py` | `tests/test_guards.py::test_engine_sh_run_blockcheck2_propagates_returncode_without_swallowing`, `tests/test_diagnostics_v2_ui.py::test_blockcheck2_runner_timeout_and_finally_restoration` | 🟢 Готово |
| **5.7. SSOT words.py без дублирования вердиктов** | `diagnostics/words.py:VERDICTS`, `dpi_classifier.get_block_verdict` делегирует в words | `tests/test_diagnostics_v2_ui.py::test_words_no_duplicates_and_ssot` | 🟢 Готово |
| **6.1. DoH/DoT провайдеры с замером RTT в UI** | `dns_providers.py:DNSProviderCatalog`, `main.py:create_dns_page` | `tests/test_dns_ui.py::test_dns_ui_probe_all_rtt_and_sorting` | 🟢 Готово |
| **6.2. ListManager с семантикой !домен и компиляцией** | `list_manager.py:ListManager`, `main.py:create_hosts_page` | `tests/test_list_ui.py::test_list_ui_compile_effective_lists_and_subdomain_pruning` | 🟢 Готово |
| **7.1. LogAnalyzer с 5 классами инцидентов** | `log_analyzer.py:LogAnalyzer`, `main.py:create_logs_page` | `tests/test_support_ui.py::test_analyze_log_clean_report` | 🟢 Готово |
| **7.2. Санитизированный SupportBundle без утечек** | `support_bundle.py:create_support_bundle`, `main.py:on_create_support_bundle` | `tests/test_support_ui.py::test_support_bundle_button_flow_and_args` | 🟢 Готово |
| **7.3. Install Integrity (fast pre-flight и full SHA-256)** | `install_integrity/verify.py`, `main.py:start_engine`, `on_verify_integrity` | `tests/test_diagnostics_v2_ui.py::test_install_integrity_fast_blocks_launch`, `test_on_verify_integrity_dialog` | 🟢 Готово |
| **8.1. Telegram Proxy (встроенный WSS)** | Не портирован в GUI (сознательное архитектурное решение: используется внешний tg-ws-proxy) | Решение владельца: внешний tg-ws-proxy уже установлен и работает | 🟢 Закрыто (сознательно не портировано) |
| **9.1. Статические AST-стражи и CI пайплайн** | `tests/test_guards.py`, `.github/workflows/ci.yml` | `tests/test_guards.py` | 🟢 Готово |
| **10.1. Пакеты, systemd unit, инсталляторы** | `packaging/PKGBUILD`, `install.sh`, `uninstall.sh`, `packaging/zapret-gui.desktop` | `tests/test_packaging.py` | 🟢 Готово |
| **11.1. Набор пресетов winws1_builtin (165 шт.)** | `zapret2/presets/winws1_builtin/`, `tests/snapshots/winws1_preset_ids.txt` | `tests/test_preset_golden_ids.py::test_winws1_preset_catalog_ids_immutable`, `tests/test_preset_catalog.py::test_catalog_winws1_presets_loaded_without_loss` | 🟢 Готово |
| **11.2. Каталоги стратегий winws1/winws2 с метаданными** | `system/strategy_catalogs/`, `catalog/preset_catalog.py:PresetEntry` (author, stability, description, source) | `tests/test_preset_catalog.py::test_preset_metadata_enrichment` | 🟢 Готово |
| **11.3. Слой сервисных профилей поверх пресетов** | `profile_manager.py:ProfileManager`, `system/templates/all_profiles.txt`, `zapret2_ui.py` | `tests/test_profile_manager.py` | 🟢 Готово |
| **11.4. Дельта-апдейтер bsdiff + rescue откат** | `updater.py:ZapretUpdater`, `signed_manifest.py:apply_bsdiff`, plan.json (Linux `keep_running`: engine.sh, nfqws, nfqws2, tpws, zapret2_core, zapret-watchdog; `preserve`: ~/.config/zapret-gui, config.json, presets, autohostlist.txt, custom_hosts.txt, hosts.txt, badsum_hosts.txt, exclude.txt), `RESCUE_DIR` | `test_updater.py::test_bsdiff_delta_apply_and_fallback`, `test_update_failure_with_rescue_rollback`, `test_build_update_plan_properties` | 🟢 Готово |
| **11.5. Генератор TLS 1.3 и QUIC Initial фейков (Kyber)** | `fake_generator.py`, `fake/chrome_template.hex`, `fake/quic_chrome_template.hex` | `tests/test_fake_generator.py` | 🟢 Готово |

