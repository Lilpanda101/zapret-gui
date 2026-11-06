#!/usr/bin/env bash
# ==============================================================================
# Zapret GUI Linux - Installation Script
# Supports:
#   1. System-wide installation (default /opt/zapret-gui or /usr/local)
#   2. Portable / User-level integration (~/.local/share/applications)
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MODE=""
PREFIX="/opt/zapret-gui"
BIN_DIR=""
SKIP_DEP_CHECK=0

print_usage() {
    cat <<EOF
Использование: $0 [ПАРАМЕТРЫ]

Параметры:
  -s, --system            Системная установка (по умолчанию в /opt/zapret-gui, требуются root-права)
  -p, --portable          Портативный режим (интеграция в пользовательский сеанс без root)
      --prefix=КАТАЛОГ    Путь для системной установки (по умолчанию: /opt/zapret-gui)
      --bin-dir=КАТАЛОГ   Каталог для исполняемого файла (по умолчанию /usr/local/bin для system, ~/.local/bin для portable)
      --skip-deps         Пропустить проверку зависимостей
  -h, --help              Показать это справочное сообщение

Примеры:
  sudo ./install.sh --system
  ./install.sh --portable
  sudo ./install.sh --system --prefix=/usr/local/share/zapret-gui --bin-dir=/usr/local/bin
EOF
}

# Parse command line options
while [ $# -gt 0 ]; do
    case "$1" in
        -s|--system)
            MODE="system"
            shift
            ;;
        -p|--portable)
            MODE="portable"
            shift
            ;;
        --prefix=*)
            PREFIX="${1#*=}"
            shift
            ;;
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --bin-dir=*)
            BIN_DIR="${1#*=}"
            shift
            ;;
        --bin-dir)
            BIN_DIR="$2"
            shift 2
            ;;
        --skip-deps)
            SKIP_DEP_CHECK=1
            shift
            ;;
        -h|--help)
            print_usage
            exit 0
            ;;
        *)
            echo "Неизвестный параметр: $1" >&2
            print_usage >&2
            exit 1
            ;;
    esac
done

# Auto-detect mode if not explicitly specified
if [ -z "$MODE" ]; then
    if [ "${EUID}" -eq 0 ]; then
        MODE="system"
    else
        MODE="portable"
    fi
fi

check_dependencies() {
    echo "==> Проверка зависимостей системы..."
    local missing=()

    if ! command -v python3 >/dev/null 2>&1; then
        missing+=("python3")
    fi

    if ! python3 -c "import gi; gi.require_version('Gtk', '3.0')" >/dev/null 2>&1; then
        missing+=("python-gobject / gtk3")
    fi

    if ! command -v nft >/dev/null 2>&1; then
        missing+=("nftables (nft)")
    fi

    if ! command -v curl >/dev/null 2>&1; then
        missing+=("curl")
    fi

    if [ ${#missing[@]} -gt 0 ]; then
        echo "ВНИМАНИЕ: Не найдены следующие зависимости:" >&2
        for dep in "${missing[@]}"; do
            echo "  - $dep" >&2
        done
        echo "Установите их через pacman:" >&2
        echo "  sudo pacman -S python-gobject gtk3 nftables curl" >&2
        if [ "$SKIP_DEP_CHECK" -eq 0 ]; then
            echo "Для продолжения без проверки запустите с --skip-deps" >&2
            exit 1
        fi
    else
        echo "Все обязательные зависимости найдены (python3, gobject/gtk3, nftables, curl)."
    fi
}

install_system() {
    if [ "${EUID}" -ne 0 ]; then
        echo "ОШИБКА: Системная установка требует прав суперпользователя (root)!" >&2
        echo "Пожалуйста, запустите: sudo $0 --system" >&2
        exit 1
    fi

    local target_bin="${BIN_DIR:-/usr/local/bin}"
    echo "==> Начинаем системную установку Zapret GUI..."
    echo "    Каталог установки: $PREFIX"
    echo "    Каталог бинарников: $target_bin"

    # 1. Create target directories
    mkdir -p "$PREFIX"
    mkdir -p "$target_bin"
    mkdir -p /usr/share/applications
    mkdir -p /usr/share/icons/hicolor/scalable/apps
    mkdir -p /usr/share/polkit-1/actions
    mkdir -p /etc/systemd/system

    # 2. Copy application files
    echo "==> Копирование файлов программы..."
    cp -a "$SCRIPT_DIR"/*.py "$PREFIX/" 2>/dev/null || true
    cp -a "$SCRIPT_DIR"/*.txt "$PREFIX/" 2>/dev/null || true
    cp -a "$SCRIPT_DIR"/engine.sh "$PREFIX/"
    cp -a "$SCRIPT_DIR"/icon.svg "$PREFIX/"
    cp -a "$SCRIPT_DIR"/moe.zapret.gui.policy "$PREFIX/"
    cp -a "$SCRIPT_DIR"/bin "$PREFIX/"
    cp -a "$SCRIPT_DIR"/fake "$PREFIX/"
    cp -a "$SCRIPT_DIR"/lists "$PREFIX/"
    [ -d "$SCRIPT_DIR/catalog" ] && cp -a "$SCRIPT_DIR"/catalog "$PREFIX/"
    [ -d "$SCRIPT_DIR/zapret2" ] && cp -a "$SCRIPT_DIR"/zapret2 "$PREFIX/"
    [ -d "$SCRIPT_DIR/orchestra" ] && cp -a "$SCRIPT_DIR"/orchestra "$PREFIX/"

    # 3. Set file permissions (executable bits)
    chmod 755 "$PREFIX/engine.sh" "$PREFIX/main.py"
    chmod -R 755 "$PREFIX/bin"
    chmod 644 "$PREFIX"/*.py "$PREFIX"/*.txt "$PREFIX/icon.svg"

    # 4. Create launcher wrapper script
    echo "==> Создание лаунчера $target_bin/zapret-gui..."
    cat <<EOF > "$target_bin/zapret-gui"
#!/usr/bin/env bash
exec python3 "$PREFIX/main.py" "\$@"
EOF
    chmod 755 "$target_bin/zapret-gui"

    # 5. Install desktop entry
    echo "==> Установка .desktop ярлыка..."
    local desktop_src="$SCRIPT_DIR/packaging/zapret-gui.desktop"
    if [ -f "$desktop_src" ]; then
        cp "$desktop_src" /usr/share/applications/zapret-gui.desktop
        chmod 644 /usr/share/applications/zapret-gui.desktop
    fi

    # 6. Install application icon
    echo "==> Установка иконки приложения..."
    if [ -f "$SCRIPT_DIR/icon.svg" ]; then
        cp "$SCRIPT_DIR/icon.svg" /usr/share/icons/hicolor/scalable/apps/zapret-gui.svg
        chmod 644 /usr/share/icons/hicolor/scalable/apps/zapret-gui.svg
        if command -v gtk-update-icon-cache >/dev/null 2>&1; then
            gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
        fi
    fi

    # 7. Install and configure Polkit policy
    echo "==> Настройка Polkit для беспарольного запуска..."
    local polkit_src="$SCRIPT_DIR/moe.zapret.gui.policy"
    if [ -f "$polkit_src" ]; then
        sed "s|<annotate key=\"org.freedesktop.policykit.exec.path\">.*engine.sh</annotate>|<annotate key=\"org.freedesktop.policykit.exec.path\">$PREFIX/engine.sh</annotate>|g" \
            "$polkit_src" > /usr/share/polkit-1/actions/moe.zapret.gui.policy
        chmod 644 /usr/share/polkit-1/actions/moe.zapret.gui.policy
    fi

    # 8. Install systemd service unit
    echo "==> Установка системной службы systemd..."
    local service_src="$SCRIPT_DIR/packaging/zapret-gui.service"
    if [ -f "$service_src" ]; then
        sed "s|/opt/zapret-gui/engine.sh|$PREFIX/engine.sh|g" "$service_src" > /etc/systemd/system/zapret-gui.service
        chmod 644 /etc/systemd/system/zapret-gui.service
        if command -v systemctl >/dev/null 2>&1; then
            systemctl daemon-reload 2>/dev/null || true
        fi
    fi

    echo ""
    echo "✨ Системная установка Zapret GUI успешно завершена!"
    echo "Запуск: zapret-gui (или через меню приложений)"
    echo "Служба systemd: systemctl enable --now zapret-gui.service"
}

install_portable() {
    local target_bin="${BIN_DIR:-${HOME}/.local/bin}"
    local user_apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"

    echo "==> Начинаем портативную установку Zapret GUI..."
    echo "    Исходный каталог: $SCRIPT_DIR"
    echo "    Каталог бинарников: $target_bin"
    echo "    Каталог ярлыков: $user_apps"

    mkdir -p "$target_bin"
    mkdir -p "$user_apps"

    # 1. Create launcher wrapper script in user bin
    echo "==> Создание лаунчера $target_bin/zapret-gui..."
    cat <<EOF > "$target_bin/zapret-gui"
#!/usr/bin/env bash
exec python3 "$SCRIPT_DIR/main.py" "\$@"
EOF
    chmod 755 "$target_bin/zapret-gui"

    # 2. Install desktop entry in ~/.local/share/applications
    echo "==> Создание ярлыка в $user_apps/zapret-gui.desktop..."
    local desktop_src="$SCRIPT_DIR/packaging/zapret-gui.desktop"
    if [ -f "$desktop_src" ]; then
        sed -e "s|^Exec=.*|Exec=python3 $SCRIPT_DIR/main.py|g" \
            -e "s|^Icon=.*|Icon=$SCRIPT_DIR/icon.svg|g" \
            "$desktop_src" > "$user_apps/zapret-gui.desktop"
        chmod 644 "$user_apps/zapret-gui.desktop"
    fi

    echo ""
    echo "✨ Портативная интеграция Zapret GUI успешно завершена!"
    echo "Приложение доступно в меню и через: $target_bin/zapret-gui"
    if [[ ":$PATH:" != *":$target_bin:"* ]]; then
        echo "Примечание: добавьте $target_bin в ваш PATH (например, в ~/.bashrc или ~/.zshrc)."
    fi
    echo "Для настройки прав Polkit выполните: sudo $SCRIPT_DIR/engine.sh install_polkit"
}

# Main execution
if [ "$SKIP_DEP_CHECK" -eq 0 ]; then
    check_dependencies
fi

if [ "$MODE" = "system" ]; then
    install_system
else
    install_portable
fi
