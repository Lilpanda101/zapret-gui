#!/usr/bin/env bash
# ==============================================================================
# Zapret GUI Linux - Uninstallation Script
# Supports:
#   1. System-wide cleanup (service, launcher, icons, polkit, /opt/zapret-gui)
#   2. Portable user-level cleanup (~/.local/share/applications, ~/.local/bin)
# ==============================================================================

set -euo pipefail

MODE=""
PREFIX="/opt/zapret-gui"
BIN_DIR=""

print_usage() {
    cat <<EOF
Использование: $0 [ПАРАМЕТРЫ]

Параметры:
  -s, --system            Удаление системной установки (требуются root-права)
  -p, --portable          Удаление портативной интеграции из сеанса пользователя
      --prefix=КАТАЛОГ    Путь установленного каталога (по умолчанию: /opt/zapret-gui)
      --bin-dir=КАТАЛОГ   Каталог исполняемого файла (по умолчанию /usr/local/bin для system, ~/.local/bin для portable)
  -h, --help              Показать это справочное сообщение

Примеры:
  sudo ./uninstall.sh --system
  ./uninstall.sh --portable
  sudo ./uninstall.sh --system --prefix=/usr/local/share/zapret-gui
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

uninstall_system() {
    if [ "${EUID}" -ne 0 ]; then
        echo "ОШИБКА: Удаление системной установки требует прав суперпользователя (root)!" >&2
        echo "Пожалуйста, запустите: sudo $0 --system" >&2
        exit 1
    fi

    local target_bin="${BIN_DIR:-/usr/local/bin}"
    echo "==> Начинаем удаление системной установки Zapret GUI..."

    # 1. Stop and disable systemd service
    if command -v systemctl >/dev/null 2>&1; then
        echo "==> Остановка и отключение службы systemd..."
        systemctl stop zapret-gui.service 2>/dev/null || true
        systemctl disable zapret-gui.service 2>/dev/null || true
    fi

    # 2. Stop running engine instances if script is available
    if [ -f "$PREFIX/engine.sh" ]; then
        echo "==> Остановка сетевого движка Zapret..."
        "$PREFIX/engine.sh" stop 2>/dev/null || true
    fi

    # 3. Remove systemd service unit
    echo "==> Удаление файлов службы..."
    rm -f /etc/systemd/system/zapret-gui.service /usr/lib/systemd/system/zapret-gui.service
    if command -v systemctl >/dev/null 2>&1; then
        systemctl daemon-reload 2>/dev/null || true
    fi

    # 4. Remove launcher wrapper
    echo "==> Удаление лаунчера..."
    rm -f "$target_bin/zapret-gui"
    [ "$target_bin" != "/usr/bin" ] && rm -f /usr/bin/zapret-gui

    # 5. Remove desktop files
    echo "==> Удаление .desktop файлов..."
    rm -f /usr/share/applications/zapret-gui.desktop
    rm -f /usr/local/share/applications/zapret-gui.desktop

    # 6. Remove application icon
    echo "==> Удаление иконки..."
    rm -f /usr/share/icons/hicolor/scalable/apps/zapret-gui.svg
    if command -v gtk-update-icon-cache >/dev/null 2>&1; then
        gtk-update-icon-cache -q -t -f /usr/share/icons/hicolor 2>/dev/null || true
    fi

    # 7. Remove Polkit policy
    echo "==> Удаление правил Polkit..."
    rm -f /usr/share/polkit-1/actions/moe.zapret.gui.policy

    # 8. Safe directory removal
    case "$PREFIX" in
        ""|"/"|"/usr"|"/usr/local"|"/opt"|"/etc"|"/var"|"/home"|"/root"|"/tmp")
            echo "ПРЕДУПРЕЖДЕНИЕ: Защита от случайного удаления — путь $PREFIX не может быть удален рекурсивно!" >&2
            ;;
        *)
            if [ -d "$PREFIX" ]; then
                echo "==> Удаление каталога установки: $PREFIX..."
                rm -rf "$PREFIX"
            fi
            ;;
    esac

    # 9. Clean up runtime state directory
    rm -rf /run/zapret-gui 2>/dev/null || true

    echo ""
    echo "✨ Системная установка Zapret GUI успешно удалена!"
}

uninstall_portable() {
    local target_bin="${BIN_DIR:-${HOME}/.local/bin}"
    local user_apps="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
    local autostart="${XDG_CONFIG_HOME:-$HOME/.config}/autostart"

    echo "==> Начинаем удаление портативной интеграции Zapret GUI..."

    # 1. Remove user launcher
    if [ -f "$target_bin/zapret-gui" ]; then
        echo "==> Удаление пользовательского лаунчера $target_bin/zapret-gui..."
        rm -f "$target_bin/zapret-gui"
    fi

    # 2. Remove user desktop shortcut
    if [ -f "$user_apps/zapret-gui.desktop" ]; then
        echo "==> Удаление $user_apps/zapret-gui.desktop..."
        rm -f "$user_apps/zapret-gui.desktop"
    fi

    # 3. Remove autostart entry if present
    if [ -f "$autostart/zapret-gui.desktop" ]; then
        echo "==> Удаление автозапуска $autostart/zapret-gui.desktop..."
        rm -f "$autostart/zapret-gui.desktop"
    fi

    echo ""
    echo "✨ Портативная интеграция Zapret GUI успешно удалена!"
}

# Main execution
if [ "$MODE" = "system" ]; then
    uninstall_system
else
    uninstall_portable
fi
