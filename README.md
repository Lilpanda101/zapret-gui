# Zapret GUI для Linux

<div align="center">

<img src="icon.svg" width="128" height="128" alt="Zapret GUI Icon" />

### Графическая оболочка и диспетчер обхода DPI для Linux

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![GTK 3](https://img.shields.io/badge/GUI-GTK%203-4E9A06?logo=gnome&logoColor=white)](https://www.gtk.org/)
[![Platform: Linux](https://img.shields.io/badge/Platform-Linux-FCC624?logo=linux&logoColor=black)](https://kernel.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![CI](https://github.com/Lilpanda101/zapret-gui/actions/workflows/ci.yml/badge.svg)](.github/workflows/ci.yml)

</div>

---

**Zapret GUI** — полнофункциональная настольная GTK3-оболочка и система управления сетевым движком обхода DPI (`nfqws2`, `nfqws`, `tpws`) с глубокой интеграцией `nftables`, Polkit и системных служб. 

Разработано специально для Linux-систем (Arch Linux, CachyOS, Debian, Ubuntu, Fedora) с акцентом на надежность, безопасность и паритет со сборками Zapret2 для Windows.

---

## 🚀 Основные возможности

- ⚡ **Движок Zapret 2 (`nfqws2`):**
  - Поддержка Lua-десинхронизации (`circular`, `shadow_probe`, `fake`, `hostfakesplit`, `syndata`, `multidisorder`).
  - 136 штатных проверенных пресетов Windows Zapret2 с авто-трансляцией в нативные правила `nftables`.
  - Автоматическая изоляция DNS (исключение портов 53/853 из всепортовых правил) и строгий conntrack-лимит для UDP-трафика.
  - Встроенный редактор и валидатор профилей с предварительной проверкой через `nfqws2 --dry-run` и `nft -c -f`.
  - Приоритет пользовательских правок пресетов (`~/.config/zapret-gui/presets`) с защитой от затирания при обновлениях.

- 🎼 **Режим Orchestra & Адаптивное обучение:**
  - Интеллектуальный роутинг трафика по доменам и протоколам.
  - Адаптивное авто-обучение эффективным стратегиям десинхронизации на основе живого трафика.
  - Автоматическое обнаружение сбоев и переключение на запасные профили.

- 🩺 **Авто-восстановление (Healer FSM):**
  - Непрерывный контроль состояния сетевого стека и фонового демона.
  - Конечный автомат самодиагностики: мягкий перезапуск, сброс зависших очередей NFQUEUE, восстановление DNS при сбоях.

- 🔒 **Безопасность и интеграция с Polkit:**
  - Никаких опасных `NOPASSWD: ALL` в sudoers. Управление сетевыми правилами осуществляется строго через PolicyKit (`moe.zapret.gui.policy`).
  - Изолированный запуск демонов в защищенных директориях ядра (`/run/zapret-gui`).

- 🌐 **DNS & Smart Proxy:**
  - Встроенное переключение защищенных DNS-провайдеров: Cloudflare (DoH), Quad9, Google, AdGuard, Mullvad.
  - Локальный менеджер `hosts.txt` с готовыми CDN-маршрутами для ускорения GitHub, Spotify, AI-сервисов (Gemini, Claude, OpenAI).

- 🔄 **Криптографически проверенные обновления:**
  - Загрузка баз списков, бинарных фейков и пресетов с зеркал проекта.
  - Валидация манифестов обновлений через цифровую подпись **Ed25519** и пофайловый контроль SHA-256 (атомарная замена).

- 📊 **Диагностика и Blockcheck:**
  - Запуск системного `blockcheck2.sh` в неинтерактивном изолированном режиме с авто-восстановлением сетевого стека.
  - Классификатор типов DPI-блокировок и генератор анонимизированных бандлов технической поддержки.

---

## 📦 Системные требования

### Обязательные компоненты:
- **ОС:** Linux с ядром 5.10+ (поддержка `nftables` и `nfnetlink_queue`).
- **Python:** 3.10 или новее.
- **Системные библиотеки:**
  - `python-gobject`
  - `gtk3`
  - `nftables`
  - `polkit`
  - `curl`
  - `systemd`

### Движки обхода (на выбор):
- `zapret2` (`/usr/bin/nfqws2`) — основной рекомендуемый движок.
- `zapret` (`/usr/bin/nfqws`) — классический режим.
- `tpws` (`/usr/bin/tpws`) — локальный прозрачный SOCKS5 прокси.

### Опционально:
- `gtksourceview4` — подсветка синтаксиса и номера строк во встроенном редакторе пресетов.
- `libayatana-appindicator` / `libappindicator-gtk3` — отображение значка в системном трее.

---

## 🛠️ Установка

### Вариант 1. Arch Linux / CachyOS / Manjaro (PKGBUILD)

Сборка и установка штатного пакета для Arch-подобных дистрибутивов:

```bash
git clone https://github.com/Lilpanda101/zapret-gui.git
cd zapret-gui/packaging
makepkg -si
```

После установки приложение доступно в меню приложений и запускается командой `zapret-gui`.

---

### Вариант 2. Универсальная установка через скрипт

Подходит для Ubuntu, Debian, Fedora, openSUSE и других дистрибутивов:

```bash
git clone https://github.com/Lilpanda101/zapret-gui.git
cd zapret-gui

# Пользовательская установка (в ~/.local/share/zapret-gui)
./install.sh

# Настройка прав Polkit (требует sudo один раз при установке)
sudo ./engine.sh install_polkit
```

Для общесистемной установки в `/opt/zapret-gui`:
```bash
sudo ./install.sh --system
```

---

### Вариант 3. Запуск без установки (Portable / Dev)

```bash
git clone https://github.com/Lilpanda101/zapret-gui.git
cd zapret-gui

# Настройка правил Polkit для текущей директории
sudo ./engine.sh install_polkit

# Запуск интерфейса
python3 main.py
```

---

## 🧪 Тестирование и верификация

В репозитории содержится полный набор автоматизированных тестов (более 460 тестов, включая FSM, сетевые контракты, транслятор правил nftables и криптографию):

```bash
# Запуск полного набора тестов
pytest -q

# Проверка синтаксиса скриптов движка
bash -n engine.sh

# Проверка компиляции всех Python-модулей
python3 -m py_compile $(git ls-files '*.py')

# Проверка версии приложения
python3 main.py --version
```

---

## 📂 Структура проекта

```text
zapret-gui/
├── main.py                 # Главная точка входа GTK3-приложения
├── engine.sh               # Системный демон управления nftables, nfqws2 и DNS
├── zapret2_core.py         # Ядро Zapret 2: трансляция пресетов в nftables, runtime
├── zapret2_ui.py           # GUI-страница управления Zapret2 и редактор пресетов
├── orchestra/              # Подсистема Orchestra: адаптивный роутинг и обучение
├── diagnostics/            # Диагностика, классификатор DPI, раннер blockcheck2
├── healer.py               # Конечный автомат самовосстановления (Healer FSM)
├── updater.py              # Менеджер обновлений с верификацией Ed25519
├── signed_manifest.py      # Проверка цифровых подписей манифестов
├── ed25519.py              # Pure-Python реализация Ed25519
├── packaging/              # Файлы сборки (.desktop, PKGBUILD, systemd unit)
├── zapret2/                # Встроенные пресеты (136 шт.) и Lua-модули
├── lists/                  # Списки доменов (russia-blacklist, exclusions и др.)
├── fake/                   # Эталонные бинарные payload-фейки
└── tests/                  # Тестовый набор pytest
```

---

## 📜 Лицензия и атрибуция

- Исходный код проекта распространяется под лицензией [MIT](LICENSE).
- Поведение, алгоритмы трансляции и пресеты базируются на наработках [zapretdiscordyoutube/zapretgui](https://github.com/zapretdiscordyoutube/zapretgui) (авторы censorliber, bol-van, Flowseal).
- Подробная информация об авторских правах и лицензиях компонентов приведена в файле [NOTICE](NOTICE).
- Детальный статус паритета и архитектурная матрица зафиксированы в [PARITY.md](PARITY.md).
