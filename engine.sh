#!/bin/bash

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BIN="$DIR/bin/nfqws"
FAKE="$DIR/fake"
STATE_DIR="/run/zapret-gui"
PIDFILE="$STATE_DIR/zapret-gui.pid"
LOGFILE="$STATE_DIR/zapret-gui.log"
LOCKFILE="$STATE_DIR/engine.lock"
WATCHDOG_SCRIPT="$STATE_DIR/zapret-watchdog.sh"
NFT_TABLE="zapret_gui"
EXCLUDE_FILE="$DIR/exclude.txt"
BADSUM_FILE="$DIR/badsum_hosts.txt"
CUSTOM_HOSTS_FILE="$DIR/custom_hosts.txt"
SYS_LIST_GENERAL="/etc/zapret/list-general.txt"
SYS_CUSTOM_HOSTS="/etc/zapret/custom_hosts.txt"
SYS_EFFECTIVE_LIST="/etc/zapret/list-general.effective.txt"
QNUM=200
NFQWS2_RUNTIME="/etc/zapret/zapret2-runtime"
NFQWS2_STATE_DIR="/run/zapret-gui"

# Ensure /run exists and initialize state directory with 0755 root:root (accessible for unprivileged status checks)
init_state_dir() {
    if [ ! -d "/run" ]; then
        echo "ERROR: /run directory is not available. Non-systemd or broken environment detected." >&2
        exit 1
    fi
    if [ "${EFFECTIVE_UID:-$EUID}" -eq 0 ]; then
        mkdir -p "$STATE_DIR"
        chmod 0755 "$STATE_DIR" 2>/dev/null || true
        chown root:root "$STATE_DIR" 2>/dev/null || true
    fi
}

LOCK_HELD=0

acquire_lock() {
    init_state_dir
    if [ "$EUID" -eq 0 ] || [ "${FORCE_LOCK:-0}" = "1" ]; then
        [ "$LOCK_HELD" = "1" ] && return 0
        exec 200>"$LOCKFILE"
        if ! flock -w 10 200; then
            echo "ERROR: Engine lock ($LOCKFILE) is busy. Another operation is in progress." >&2
            exit 1
        fi
        LOCK_HELD=1
    fi
}

release_lock() {
    if [ "$LOCK_HELD" = "1" ]; then
        flock -u 200 2>/dev/null || true
        exec 200>&- 2>/dev/null || true
        LOCK_HELD=0
    fi
}

wait_for_process_start() {
    local unit="$1"
    local pid_file="$2"
    local max_wait_sec="${3:-5}"
    local expected_pattern="${4:-}"
    local step_ms=200
    local elapsed_ms=0
    local max_ms=$((max_wait_sec * 1000))

    if [ -z "$expected_pattern" ]; then
        case "$unit" in
            *tpws*) expected_pattern="tpws" ;;
            *nfqws2*|*zapret2*) expected_pattern="zapret2_core|nfqws2|nfqws" ;;
            *nfqws*) expected_pattern="nfqws" ;;
            *) expected_pattern=".*" ;;
        esac
    fi

    while [ "$elapsed_ms" -lt "$max_ms" ]; do
        # 1. First priority: Check pidfile if present and process is alive
        if [ -s "$pid_file" ]; then
            local fpid
            fpid=$(cat "$pid_file" 2>/dev/null || true)
            if [ -n "$fpid" ] && kill -0 "$fpid" 2>/dev/null; then
                local fexe
                fexe=$(readlink -f "/proc/$fpid/exe" 2>/dev/null || true)
                local fcomm
                fcomm=$(cat "/proc/$fpid/comm" 2>/dev/null || true)
                local fcmd
                fcmd=$(tr '\0' ' ' < "/proc/$fpid/cmdline" 2>/dev/null || true)
                if [ -z "$fexe" ] \
                   || [[ "$fexe" =~ ($expected_pattern) ]] \
                   || [[ "$fcomm" =~ ($expected_pattern) ]] \
                   || [[ "$fcmd"  =~ ($expected_pattern) ]]; then
                    return 0
                fi
            fi
        fi

        # 2. Second priority: Query systemd unit
        if systemctl is-active --quiet "$unit" 2>/dev/null; then
            local mpid
            mpid=$(systemctl show -p MainPID --value "$unit" 2>/dev/null || true)
            if [ -n "$mpid" ] && [ "$mpid" != "0" ] && kill -0 "$mpid" 2>/dev/null; then
                echo "$mpid" > "$pid_file"
                return 0
            fi
        fi

        # Abort only if unit is explicitly failed AND no valid pidfile is present
        if systemctl is-failed --quiet "$unit" 2>/dev/null && [ ! -s "$pid_file" ]; then
            return 1
        fi

        sleep 0.2
        elapsed_ms=$((elapsed_ms + step_ms))
    done
    return 1
}

rollback_startup() {
    local iface="$1"
    echo "ERROR: Engine startup failed, performing clean rollback..." >&2
    tail -n 20 "$LOGFILE" >&2 2>/dev/null || true
    systemctl stop zapret-watchdog zapret-nfqws zapret2-nfqws zapret-tpws 2>/dev/null || true
    systemctl reset-failed zapret-watchdog zapret-nfqws zapret2-nfqws zapret-tpws 2>/dev/null || true
    if [ -f "$PIDFILE" ]; then
        local PID
        PID=$(cat "$PIDFILE" 2>/dev/null || true)
        [ -n "$PID" ] && kill -9 "$PID" 2>/dev/null || true
        rm -f "$PIDFILE"
    fi
    nft delete table inet "$NFT_TABLE" 2>/dev/null || true
    rm -f "$STATE_DIR/nft-active"
    return 1
}

# Function to check root
check_root() {
    if [ "$EUID" -ne 0 ]; then
        echo "ERROR: This command must be run as root (e.g. via sudo/pkexec)" >&2
        exit 1
    fi
}

validate_exec_target() {
    local target="$1"
    if [ "$EUID" -ne 0 ]; then
        return 0
    fi

    local REAL_PATH
    REAL_PATH=$(readlink -f "$target" 2>/dev/null || echo "$target")
    local REAL_DIR
    REAL_DIR=$(dirname "$REAL_PATH")

    if [[ "$REAL_PATH" =~ ^(/usr/|/opt/) ]]; then
        local OWNER_UID
        OWNER_UID=$(stat -c '%u' "$REAL_PATH" 2>/dev/null || echo "1000")
        if [ "$OWNER_UID" -ne 0 ]; then
            echo "SECURITY ERROR: System-wide file $REAL_PATH is not owned by root (UID: $OWNER_UID). Aborting." >&2
            exit 1
        fi
        if [ -w "$REAL_DIR" ] && [ "$OWNER_UID" -ne 0 ]; then
            echo "SECURITY ERROR: System directory $REAL_DIR is writable by non-root. Aborting." >&2
            exit 1
        fi
    else
        echo "WARNING: Portable Mode: executing $REAL_PATH from user directory. For full isolation install to /usr/libexec/zapret-gui" >&2
    fi
}

get_active_iface() {
    local iface="$1"
    if [ "$iface" = "any" ] || [ -z "$iface" ]; then
        ip route show default 2>/dev/null | awk '{print $5}' | head -n1
    else
        echo "$iface"
    fi
}

tune_network() {
    echo "Applying high-performance network tuning (BBR, conntrack liberal, buffer expansion, IPv6 hygiene)..."
    modprobe tcp_bbr 2>/dev/null || true

    cat << 'EOF' > /etc/sysctl.d/99-network-performance.conf
# Google BBR congestion control + FQ queueing
net.core.default_qdisc = fq
net.ipv4.tcp_congestion_control = bbr

# TCP protocol optimizations
net.ipv4.tcp_fastopen = 3
net.ipv4.tcp_mtu_probing = 1
net.ipv4.tcp_slow_start_after_idle = 0
net.ipv4.tcp_window_scaling = 1
net.ipv4.tcp_timestamps = 1
net.ipv4.tcp_sack = 1

# Prevent Linux kernel from dropping modified DPI desync packets as INVALID
net.netfilter.nf_conntrack_tcp_be_liberal = 1

# Maximum buffer sizing for Gigabit / line-speed downloads
net.core.rmem_max = 67108864
net.core.wmem_max = 67108864
net.core.rmem_default = 1048576
net.core.wmem_default = 1048576
net.ipv4.tcp_rmem = 4096 1048576 67108864
net.ipv4.tcp_wmem = 4096 1048576 67108864
net.core.netdev_max_backlog = 16384
net.core.somaxconn = 8192

EOF
    sysctl --system >/dev/null 2>&1 || true
    sysctl -w net.netfilter.nf_conntrack_tcp_be_liberal=1 2>/dev/null || true

    # Ensure /etc/gai.conf prioritizes IPv4 over IPv6
    if [ ! -f /etc/gai.conf ] || ! grep -q "::ffff:0:0/96" /etc/gai.conf; then
        echo "precedence ::ffff:0:0/96  100" >> /etc/gai.conf
    fi

    echo "Network tuning applied successfully."
}

verify_dns_resolver() {
    local ip="$1"
    # Fast TCP probe for DoT (853) or DNS (53)
    timeout 1.5 bash -c "</dev/tcp/$ip/853" 2>/dev/null && return 0
    timeout 1.5 bash -c "</dev/tcp/$ip/53" 2>/dev/null && return 0
    return 1
}

apply_dns() {
    local iface="$1"
    local provider="$2"
    local dev=$(get_active_iface "$iface")
    [ -z "$dev" ] && return 0

    if [ "$provider" != "system" ] && [ "$provider" != "none" ]; then
        local TEST_IP=""
        case "$provider" in
            cloudflare) TEST_IP="1.1.1.1" ;;
            yandex) TEST_IP="77.88.8.8" ;;
            google) TEST_IP="8.8.8.8" ;;
            adguard) TEST_IP="94.140.14.14" ;;
            quad9) TEST_IP="9.9.9.9" ;;
            dns_ai) TEST_IP="194.87.196.13" ;;
            geohide) TEST_IP="193.233.155.105" ;;
            shecan) TEST_IP="178.22.122.100" ;;
        esac

        if [ -n "$TEST_IP" ]; then
            if ! verify_dns_resolver "$TEST_IP"; then
                echo "WARNING: DNS resolver $TEST_IP ($provider) unreachable. Checking fallback..." >&2
                if verify_dns_resolver "1.1.1.1"; then
                    echo "Falling back to Cloudflare DNS..." >&2
                    provider="cloudflare"
                else
                    echo "ERROR: Fallback DNS unreachable. Reverting to system defaults..." >&2
                    revert_dns "$iface"
                    return 1
                fi
            fi
        fi
    fi

    echo "Configuring DNS ($provider) on interface $dev..."
    resolvectl default-route "$dev" yes 2>/dev/null || true

    mkdir -p /etc/systemd/resolved.conf.d 2>/dev/null || true
    local CONF_FILE="/etc/systemd/resolved.conf.d/zapret_dns.conf"

    case "$provider" in
        cloudflare)
            cat << 'EOF' > "$CONF_FILE"
[Resolve]
DNS=1.1.1.1#cloudflare-dns.com 1.0.0.1#cloudflare-dns.com
FallbackDNS=1.1.1.1 8.8.8.8 9.9.9.9
DNSOverTLS=opportunistic
DNSSEC=no
Domains=~.
EOF
            resolvectl dns "$dev" 1.1.1.1#cloudflare-dns.com 1.0.0.1#cloudflare-dns.com 2>/dev/null || true
            resolvectl dnsovertls "$dev" opportunistic 2>/dev/null || true
            ;;
        yandex)
            cat << 'EOF' > "$CONF_FILE"
[Resolve]
DNS=77.88.8.8#common.dot.dns.yandex.net 77.88.8.1#common.dot.dns.yandex.net
FallbackDNS=1.1.1.1 8.8.8.8
DNSOverTLS=opportunistic
DNSSEC=no
Domains=~.
EOF
            resolvectl dns "$dev" 77.88.8.8#common.dot.dns.yandex.net 77.88.8.1#common.dot.dns.yandex.net 2>/dev/null || true
            resolvectl dnsovertls "$dev" opportunistic 2>/dev/null || true
            ;;
        google)
            cat << 'EOF' > "$CONF_FILE"
[Resolve]
DNS=8.8.8.8#dns.google 8.8.4.4#dns.google
FallbackDNS=1.1.1.1 9.9.9.9
DNSOverTLS=opportunistic
DNSSEC=no
Domains=~.
EOF
            resolvectl dns "$dev" 8.8.8.8#dns.google 8.8.4.4#dns.google 2>/dev/null || true
            resolvectl dnsovertls "$dev" opportunistic 2>/dev/null || true
            ;;
        adguard)
            cat << 'EOF' > "$CONF_FILE"
[Resolve]
DNS=94.140.14.14#dns.adguard-dns.com 94.140.15.15#dns.adguard-dns.com
FallbackDNS=1.1.1.1 8.8.8.8
DNSOverTLS=opportunistic
DNSSEC=no
Domains=~.
EOF
            resolvectl dns "$dev" 94.140.14.14#dns.adguard-dns.com 94.140.15.15#dns.adguard-dns.com 2>/dev/null || true
            resolvectl dnsovertls "$dev" opportunistic 2>/dev/null || true
            ;;
        quad9)
            cat << 'EOF' > "$CONF_FILE"
[Resolve]
DNS=9.9.9.9#dns.quad9.net 149.112.112.112#dns.quad9.net
FallbackDNS=1.1.1.1 8.8.8.8
DNSOverTLS=opportunistic
DNSSEC=no
Domains=~.
EOF
            resolvectl dns "$dev" 9.9.9.9#dns.quad9.net 149.112.112.112#dns.quad9.net 2>/dev/null || true
            resolvectl dnsovertls "$dev" opportunistic 2>/dev/null || true
            ;;
        dns_ai)
            cat << 'EOF' > "$CONF_FILE"
[Resolve]
DNS=194.87.196.13#dns-ai.ru 45.151.102.219#dns-ai.ru
FallbackDNS=1.1.1.1#cloudflare-dns.com 8.8.8.8
DNSOverTLS=opportunistic
DNSSEC=no
Domains=~.
EOF
            resolvectl dns "$dev" 194.87.196.13#dns-ai.ru 45.151.102.219#dns-ai.ru 2>/dev/null || true
            resolvectl dnsovertls "$dev" opportunistic 2>/dev/null || true
            ;;
        geohide)
            cat << 'EOF' > "$CONF_FILE"
[Resolve]
DNS=37.230.192.51#geohide.ru
FallbackDNS=1.1.1.1#cloudflare-dns.com 8.8.8.8
DNSOverTLS=opportunistic
DNSSEC=no
Domains=~.
EOF
            resolvectl dns "$dev" 37.230.192.51#geohide.ru 2>/dev/null || true
            resolvectl dnsovertls "$dev" opportunistic 2>/dev/null || true
            ;;
        xbox)
            cat << 'EOF' > "$CONF_FILE"
[Resolve]
DNS=178.22.122.100#free.shecan.ir 194.87.196.13#dns-ai.ru
FallbackDNS=1.1.1.1#cloudflare-dns.com 8.8.8.8
DNSOverTLS=opportunistic
DNSSEC=no
Domains=~.
EOF
            resolvectl dns "$dev" 178.22.122.100#free.shecan.ir 194.87.196.13#dns-ai.ru 2>/dev/null || true
            resolvectl dnsovertls "$dev" opportunistic 2>/dev/null || true
            ;;
        system|none)
            rm -f "$CONF_FILE"
            resolvectl revert "$dev" 2>/dev/null || true
            ;;
        *)
            cat << 'EOF' > "$CONF_FILE"
[Resolve]
DNS=1.1.1.1#cloudflare-dns.com 1.0.0.1#cloudflare-dns.com
FallbackDNS=1.1.1.1 8.8.8.8 9.9.9.9
DNSOverTLS=opportunistic
DNSSEC=no
Domains=~.
EOF
            resolvectl dns "$dev" 1.1.1.1#cloudflare-dns.com 1.0.0.1#cloudflare-dns.com 2>/dev/null || true
            resolvectl dnsovertls "$dev" opportunistic 2>/dev/null || true
            ;;
    esac

    if [ "$provider" != "system" ] && [ "$provider" != "none" ]; then
        resolvectl default-route "$dev" yes 2>/dev/null || true
        resolvectl domain "$dev" "~." 2>/dev/null || true
    fi
    systemctl reset-failed systemd-resolved 2>/dev/null || true
    systemctl reload-or-try-restart systemd-resolved 2>/dev/null || true
    resolvectl flush-caches 2>/dev/null || true
}

revert_dns() {
    local iface="$1"
    local dev=$(get_active_iface "$iface")
    [ -z "$dev" ] && return 0

    echo "Restoring DNS on interface $dev to NetworkManager defaults..."
    rm -f /etc/systemd/resolved.conf.d/zapret_dns.conf 2>/dev/null || true
    systemctl reset-failed systemd-resolved 2>/dev/null || true
    systemctl reload-or-try-restart systemd-resolved 2>/dev/null || true
    resolvectl revert "$dev" 2>/dev/null || true
    resolvectl flush-caches 2>/dev/null || true
}

apply_ai_hosts() {
    local enable="$1"
    clean_ai_hosts

    if [ "$enable" = "1" ] || [ "$enable" = "true" ]; then
        echo "Injecting validated Zapret AI & unblocked services into /etc/hosts..."
        local HOSTS_SRC="$DIR/hosts.txt"
        if [ ! -f "$HOSTS_SRC" ] && [ -n "$SUDO_USER" ]; then
            HOSTS_SRC="/home/$SUDO_USER/.local/share/zapret-gui/hosts.txt"
        fi

        if [ -f "$HOSTS_SRC" ]; then
            python3 "$DIR/hosts_manager.py" apply "$HOSTS_SRC" "/etc/hosts"
            resolvectl flush-caches 2>/dev/null || true
            echo "AI hosts successfully applied."
        fi
    fi
}

clean_ai_hosts() {
    if [ -f /etc/hosts ] && grep -q "ZAPRET_GUI_AI_HOSTS" /etc/hosts; then
        echo "Safely cleaning Zapret AI entries from /etc/hosts..."
        python3 "$DIR/hosts_manager.py" clean "/etc/hosts"
        resolvectl flush-caches 2>/dev/null || true
    fi
}

stop_engine() {
    local iface="$1"
    acquire_lock
    echo "Stopping Zapret engine..."
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Stopping Zapret engine..." >> "$LOGFILE" 2>/dev/null || true

    systemctl stop zapret-watchdog 2>/dev/null || true
    systemctl stop zapret-nfqws 2>/dev/null || true
    systemctl reset-failed zapret-nfqws 2>/dev/null || true
    systemctl stop zapret2-nfqws 2>/dev/null || true
    systemctl reset-failed zapret2-nfqws 2>/dev/null || true
    systemctl stop zapret-tpws 2>/dev/null || true
    systemctl reset-failed zapret-tpws 2>/dev/null || true
    rm -f "$WATCHDOG_SCRIPT"

    if [ -f "$PIDFILE" ]; then
        local PID
        PID=$(cat "$PIDFILE" 2>/dev/null || true)
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            local EXE
            EXE=$(readlink -f "/proc/$PID/exe" 2>/dev/null || true)
            # Only terminate our own expected binaries
            if [ -n "$EXE" ] && [[ "$EXE" =~ (nfqws|tpws|python) ]]; then
                kill -15 "$PID" 2>/dev/null || true
                for _ in {1..20}; do
                    kill -0 "$PID" 2>/dev/null || break
                    sleep 0.1
                done
                kill -9 "$PID" 2>/dev/null || true
            fi
        fi
        rm -f "$PIDFILE"
    fi

    # Remove nftables mangle table cleanly
    nft delete table inet "$NFT_TABLE" 2>/dev/null || true
    rm -f "$STATE_DIR/nft-active"

    revert_dns "$iface"
    clean_ai_hosts

    echo "Zapret engine stopped."
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Zapret engine stopped." >> "$LOGFILE" 2>/dev/null || true
}

status_engine() {
    init_state_dir
    local RUNNING=0
    if systemctl is-active --quiet zapret-nfqws 2>/dev/null \
        || systemctl is-active --quiet zapret2-nfqws 2>/dev/null \
        || systemctl is-active --quiet zapret-tpws 2>/dev/null; then
        RUNNING=1
    elif [ -f "$PIDFILE" ]; then
        local PID
        PID=$(cat "$PIDFILE" 2>/dev/null || true)
        if [ -n "$PID" ] && kill -0 "$PID" 2>/dev/null; then
            RUNNING=1
        fi
    fi

    if [ "$RUNNING" -eq 0 ]; then
        echo "INACTIVE"
        exit 1
    fi
    if systemctl is-active --quiet zapret-tpws 2>/dev/null; then
        echo "ACTIVE"
        exit 0
    fi

    # Check kernel table directly (Single Source of Truth)
    if nft list table inet "$NFT_TABLE" >/dev/null 2>&1; then
        : > "$STATE_DIR/nft-active" 2>/dev/null || true
        chmod 0644 "$STATE_DIR/nft-active" 2>/dev/null || true
        echo "ACTIVE"
        exit 0
    elif [ "${EFFECTIVE_UID:-$EUID}" -ne 0 ] && [ -f "$STATE_DIR/nft-active" ]; then
        # When unprivileged user cannot inspect kernel netlink, fallback to root marker
        echo "ACTIVE"
        exit 0
    fi

    rm -f "$STATE_DIR/nft-active" 2>/dev/null || true
    echo "NFQWS_ONLY"
    exit 2
}

sync_general_hostlist() {
    if [ -f "$DIR/list-general.txt" ]; then
        cp -f "$DIR/list-general.txt" "$SYS_LIST_GENERAL"
    fi
    if [ -f "$CUSTOM_HOSTS_FILE" ]; then
        cp -f "$CUSTOM_HOSTS_FILE" "$SYS_CUSTOM_HOSTS"
    else
        : > "$SYS_CUSTOM_HOSTS"
    fi

    local sources=()
    [ -f "$SYS_LIST_GENERAL" ] && sources+=("$SYS_LIST_GENERAL")
    [ -s "$SYS_CUSTOM_HOSTS" ] && sources+=("$SYS_CUSTOM_HOSTS")
    if [ "${#sources[@]}" -gt 0 ]; then
        awk 'NF && !seen[$0]++' "${sources[@]}" > "$SYS_EFFECTIVE_LIST"
    else
        : > "$SYS_EFFECTIVE_LIST"
    fi
}

start_nfqws2_engine() {
    local IFACE="$1"
    local DNS_PROVIDER="$2"
    local ENABLE_AI_HOSTS="$3"

    echo "Applying Zapret2 nftables rules..."
    if ! nft -c -f "$NFQWS2_RUNTIME/firewall.nft"; then
        echo "ERROR: Invalid nftables syntax generated" >&2
        return 1
    fi
    if ! nft -f "$NFQWS2_RUNTIME/firewall.nft"; then
        echo "ERROR: Failed to load nftables rules into kernel" >&2
        nft delete table inet "$NFT_TABLE" 2>/dev/null || true
        rm -f "$STATE_DIR/nft-active"
        return 1
    fi

    # Truncate logfile if it exceeds 10MB to protect memory/tmpfs
    if [ -f "$LOGFILE" ] && [ "$(stat -c%s "$LOGFILE" 2>/dev/null || echo 0)" -gt 10485760 ]; then
        tail -n 2000 "$LOGFILE" > "$LOGFILE.tmp" 2>/dev/null && mv -f "$LOGFILE.tmp" "$LOGFILE" 2>/dev/null || true
    fi

    systemctl stop zapret2-nfqws 2>/dev/null || true
    systemctl reset-failed zapret2-nfqws 2>/dev/null || true
    validate_exec_target "$DIR/zapret2_core.py"
    if ! systemd-run --unit=zapret2-nfqws \
        --description="Zapret2 nfqws2 Lua DPI Engine" \
        --property=Restart=always \
        --property=RestartSec=2 \
        --property=LimitNOFILE=65535 \
        --property=StandardOutput=append:$LOGFILE \
        --property=StandardError=append:$LOGFILE \
        /usr/bin/python3 "$DIR/zapret2_core.py" run --runtime "$NFQWS2_RUNTIME"; then
        echo "systemd-run failed; launching nfqws2 directly..."
        nohup /usr/bin/python3 "$DIR/zapret2_core.py" run --runtime "$NFQWS2_RUNTIME" >> "$LOGFILE" 2>&1 &
        echo $! > "$PIDFILE"
        chmod 0644 "$PIDFILE" 2>/dev/null || true
    fi

    if ! wait_for_process_start "zapret2-nfqws" "$PIDFILE" 5 "zapret2_core|nfqws2|nfqws"; then
        rollback_startup "$IFACE"
        return 1
    fi

    # Only mark active and configure DNS AFTER process is guaranteed alive
    : > "$STATE_DIR/nft-active"
    chmod 0644 "$STATE_DIR/nft-active" 2>/dev/null || true
    apply_dns "$IFACE" "$DNS_PROVIDER"
    apply_ai_hosts "$ENABLE_AI_HOSTS"
    echo "Zapret2 nfqws2 started with PID: $(cat "$PIDFILE")"
}

start_engine() {
    acquire_lock
    local PRESET="${1:-general}"
    local IFACE="${2:-any}"
    local DNS_PROVIDER="${3:-cloudflare}"
    local ENABLE_AI_HOSTS="${4:-1}"
    local ENABLE_QUIC="${5:-1}"
    local ENABLE_DISCORD_VOICE="${6:-1}"
    local CONNTRACK_LIMIT="${7:-12}"
    local HOSTLIST_MODE="${8:-all_except_exclude}"
    local ENGINE_MODE="${9:-nfqws2}"
    local CUSTOM_PARAMS="${10:-}"
    local Z2_PRESET="${11:-Default (circular)}"
    local ENABLE_YOUTUBE="${12:-1}"
    local ENABLE_DISCORD_TCP="${13:-1}"
    local ENABLE_GENERAL_HTTPS="${14:-1}"

    # Validate nfqws2 and all Lua/resources before interrupting a working engine.
    if [ "$ENGINE_MODE" = "nfqws2" ]; then
        local ACTIVE_IFACE
        ACTIVE_IFACE=$(get_active_iface "$IFACE")
        [ -n "$ACTIVE_IFACE" ] || { echo "ERROR: Active network interface not found" >&2; return 1; }
        mkdir -p "$NFQWS2_RUNTIME"
        local AUTO_HL_OPT=""
        local USER_CFG="$HOME/.config/zapret-gui/config.json"
        if [ -n "$SUDO_USER" ]; then
            local U_HOME
            U_HOME="$(getent passwd "$SUDO_USER" 2>/dev/null | cut -d: -f6)"
            [ -n "$U_HOME" ] && [ -f "$U_HOME/.config/zapret-gui/config.json" ] && USER_CFG="$U_HOME/.config/zapret-gui/config.json"
        elif [ -n "$PKEXEC_UID" ]; then
            local U_HOME
            U_HOME="$(getent passwd "$PKEXEC_UID" 2>/dev/null | cut -d: -f6)"
            [ -n "$U_HOME" ] && [ -f "$U_HOME/.config/zapret-gui/config.json" ] && USER_CFG="$U_HOME/.config/zapret-gui/config.json"
        fi
        if [ "$ENABLE_AUTO_HOSTLIST" = "1" ] || grep -q '"enable_auto_hostlist": true' "$USER_CFG" 2>/dev/null || grep -q '"enable_auto_hostlist": true' "$HOME/.config/zapret-gui/config.json" 2>/dev/null; then
            AUTO_HL_OPT="--enable-auto-hostlist"
        fi
        validate_exec_target "$DIR/zapret2_core.py"
        python3 "$DIR/zapret2_core.py" prepare \
            --preset "$Z2_PRESET" --output "$NFQWS2_RUNTIME" --iface "$ACTIVE_IFACE" $AUTO_HL_OPT || return 1
    fi

    # Network conntrack tuning for reliable long-running desync sessions
    sysctl -w net.netfilter.nf_conntrack_tcp_be_liberal=1 >/dev/null 2>&1 || true
    sysctl -w net.netfilter.nf_conntrack_max=524288 >/dev/null 2>&1 || true
    sysctl -w net.netfilter.nf_conntrack_tcp_timeout_established=86400 >/dev/null 2>&1 || true
    sysctl -w net.netfilter.nf_conntrack_udp_timeout=60 >/dev/null 2>&1 || true
    sysctl -w net.netfilter.nf_conntrack_udp_timeout_stream=1800 >/dev/null 2>&1 || true

    stop_engine "$IFACE"

    # Always synchronize bases and lists to /etc/zapret
    mkdir -p /etc/zapret
    if [ -d "$DIR/fake" ]; then
        cp -r "$DIR/fake" /etc/zapret/ 2>/dev/null || true
    fi
    if [ -d "$DIR/lists" ]; then
        cp -r "$DIR/lists" /etc/zapret/ 2>/dev/null || true
    fi
    SYS_EXCLUDE="/etc/zapret/exclude.txt"
    if [ -f "$EXCLUDE_FILE" ]; then
        cp -f "$EXCLUDE_FILE" "$SYS_EXCLUDE" 2>/dev/null || true
    fi
    SYS_BADSUM="/etc/zapret/badsum_hosts.txt"
    if [ -f "$BADSUM_FILE" ]; then
        cp -f "$BADSUM_FILE" "$SYS_BADSUM" 2>/dev/null || true
    fi
    sync_general_hostlist
    chmod -R 755 /etc/zapret 2>/dev/null || true

    rm -f "$LOGFILE" "$PIDFILE"
    touch "$LOGFILE" && chmod 644 "$LOGFILE" 2>/dev/null || true

    # Mode check: TPWS (local SOCKS5 only) vs NFQWS/NFQWS2
    if [ "$ENGINE_MODE" = "tpws" ]; then
        echo "Starting TPWS (SOCKS5 Proxy on 127.0.0.1:1080)..."
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting TPWS (SOCKS5 Proxy on 127.0.0.1:1080)..." >> "$LOGFILE"

        systemctl stop zapret-tpws 2>/dev/null || true
        systemctl reset-failed zapret-tpws 2>/dev/null || true

        if ! systemd-run --unit=zapret-tpws \
            --description="Zapret tpws SOCKS5 Proxy Watchdog" \
            --property=Restart=always \
            --property=RestartSec=2 \
            --property=LimitNOFILE=65535 \
            --property=StandardOutput=append:$LOGFILE \
            --property=StandardError=append:$LOGFILE \
            "$DIR/bin/tpws" --bind-addr=127.0.0.1 --port=1080 --socks --split-pos=1,midsld --disorder --hostcase --domcase 2>/dev/null; then
            echo "systemd-run failed; launching tpws directly..."
            nohup "$DIR/bin/tpws" --bind-addr=127.0.0.1 --port=1080 --socks --split-pos=1,midsld --disorder --hostcase --domcase >> "$LOGFILE" 2>&1 &
            echo $! > "$PIDFILE"
            chmod 0644 "$PIDFILE" 2>/dev/null || true
        fi

        if ! wait_for_process_start "zapret-tpws" "$PIDFILE" 5 "tpws"; then
            rollback_startup "$IFACE"
            return 1
        fi

        apply_dns "$IFACE" "$DNS_PROVIDER"
        apply_ai_hosts "$ENABLE_AI_HOSTS"

        echo "Zapret TPWS engine started successfully with PID: $(cat "$PIDFILE" 2>/dev/null || true)"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] Zapret TPWS engine active." >> "$LOGFILE"
        return 0
    fi

    if [ "$ENGINE_MODE" = "nfqws2" ]; then
        start_nfqws2_engine "$IFACE" "$DNS_PROVIDER" "$ENABLE_AI_HOSTS"
        return $?
    fi

    # Legacy NFQWS Mode: configure firewall
    echo "Configuring firewall for interface: $IFACE..."

    # Configure nftables mangle table
    nft add table inet "$NFT_TABLE"
    nft add chain inet "$NFT_TABLE" postrouting '{ type filter hook postrouting priority mangle; }'

    OIF_CLAUSE=""
    if [ "$IFACE" != "any" ] && [ -n "$IFACE" ]; then
        OIF_CLAUSE="oifname \"$IFACE\""
    fi

    # TCP rule: Intercept HTTPS ports ONLY with dynamic conntrack limit
    local CT_LIMIT="${CONNTRACK_LIMIT:-12}"
    if [ "$CT_LIMIT" = "1" ] || [ "$CT_LIMIT" = "true" ] || [ "$CT_LIMIT" -le 1 ] 2>/dev/null; then
        CT_LIMIT=12
    fi
    nft add rule inet "$NFT_TABLE" postrouting $OIF_CLAUSE \
        meta mark and 0x40000000 == 0 tcp dport '{ 443, 2053, 2083, 2087, 2096, 8443 }' \
        ct original packets "1-$CT_LIMIT" \
        queue num $QNUM bypass comment "\"zapret_gui_tcp\""

    # QUIC (UDP 443) handling
    if [ "$ENABLE_QUIC" != "0" ]; then
        # Route QUIC Initial packets (1-6) to nfqws bypass queue
        nft add rule inet "$NFT_TABLE" postrouting $OIF_CLAUSE \
            meta mark and 0x40000000 == 0 udp dport 443 \
            ct original packets 1-6 \
            queue num $QNUM bypass comment "\"zapret_gui_quic\""
    else
        # Dedicated output filter chain for instant QUIC rejection
        nft add chain inet "$NFT_TABLE" output '{ type filter hook output priority filter; }'
        nft add rule inet "$NFT_TABLE" output $OIF_CLAUSE udp dport 443 reject
    fi

    # Intercept Discord voice and STUN UDP / Game ports
    if [ "$PRESET" = "game_filter" ]; then
        nft add rule inet "$NFT_TABLE" postrouting $OIF_CLAUSE \
            meta mark and 0x40000000 == 0 udp dport '{ 19294-19344, 50000-50100, 27015-27050, 3074, 3478-3480 }' \
            ct original packets 1-6 \
            queue num $QNUM bypass comment "\"zapret_gui_game_udp\""
    elif [ "$ENABLE_DISCORD_VOICE" != "0" ]; then
        nft add rule inet "$NFT_TABLE" postrouting $OIF_CLAUSE \
            meta mark and 0x40000000 == 0 udp dport '{ 19294-19344, 50000-50100 }' \
            ct original packets 1-6 \
            queue num $QNUM bypass comment "\"zapret_gui_udp\""
    fi

    mkdir -p "$NFQWS2_STATE_DIR"
    echo "Firewall rules applied."
    echo "Starting nfqws with preset: $PRESET..."

    FAKE_DIR="/etc/zapret/fake"
    [ ! -d "$FAKE_DIR" ] && FAKE_DIR="$FAKE"

    FAKE_TLS="$FAKE_DIR/tls_clienthello_www_google_com.bin"
    [ ! -f "$FAKE_TLS" ] && FAKE_TLS="$FAKE_DIR/tls_clienthello_vk_com_kyber.bin"

    FAKE_DISCORD="$FAKE_DIR/ACTIVE_DISCORD_UDP.bin"
    [ ! -f "$FAKE_DISCORD" ] && FAKE_DISCORD="$FAKE_DIR/quic_initial_www_google_com.bin"

    FAKE_STUN="$FAKE_DIR/stun.bin"
    [ ! -f "$FAKE_STUN" ] && FAKE_STUN="$FAKE_DIR/quic_initial_www_google_com.bin"

    SYS_SERVICE_LIST="/etc/zapret/list-services.effective.txt"
    SYS_SERVICE_EXCLUDE="/etc/zapret/list-services.exclude.txt"
    local enabled_lists=()
    local disabled_lists=()
    if [ "$ENABLE_YOUTUBE" != "0" ]; then
        enabled_lists+=("/etc/zapret/lists/youtube.txt" "/etc/zapret/lists/youtubeGV.txt")
    else
        disabled_lists+=("/etc/zapret/lists/youtube.txt" "/etc/zapret/lists/youtubeGV.txt")
    fi
    if [ "$ENABLE_DISCORD_TCP" != "0" ]; then
        enabled_lists+=("/etc/zapret/lists/discord.txt")
    else
        disabled_lists+=("/etc/zapret/lists/discord.txt")
    fi

    local exclude_sources=()
    [ -f "$SYS_EXCLUDE" ] && exclude_sources+=("$SYS_EXCLUDE")
    for list_file in "${disabled_lists[@]}"; do
        [ -f "$list_file" ] && exclude_sources+=("$list_file")
    done
    if [ "${#exclude_sources[@]}" -gt 0 ]; then
        awk 'NF && !seen[$0]++' "${exclude_sources[@]}" > "$SYS_SERVICE_EXCLUDE"
    else
        : > "$SYS_SERVICE_EXCLUDE"
    fi

    HOSTLIST_OPT=()
    if [ "$ENABLE_GENERAL_HTTPS" = "0" ]; then
        local service_sources=()
        for list_file in "${enabled_lists[@]}"; do
            [ -f "$list_file" ] && service_sources+=("$list_file")
        done
        if [ "${#service_sources[@]}" -gt 0 ]; then
            awk 'NF && !seen[$0]++' "${service_sources[@]}" > "$SYS_SERVICE_LIST"
        else
            : > "$SYS_SERVICE_LIST"
        fi
        HOSTLIST_OPT=("--hostlist=$SYS_SERVICE_LIST")
    elif [ "$HOSTLIST_MODE" = "strict_list" ] && [ -f "$SYS_EFFECTIVE_LIST" ]; then
        HOSTLIST_OPT=("--hostlist=$SYS_EFFECTIVE_LIST")
    fi
    HOSTLIST_OPT+=("--hostlist-exclude=$SYS_SERVICE_EXCLUDE")

    ARGS=("--qnum=$QNUM" "--bind-fix4")

    case "$PRESET" in
        "general")
            # Profile 1: badsum fooling for servers that reject TS-fooling
            if [ -f "$SYS_BADSUM" ] && [ -s "$SYS_BADSUM" ]; then
                ARGS+=(
                    "--filter-tcp=443,2053,2083,2087,2096,8443"
                    "--hostlist=$SYS_BADSUM"
                    "--dpi-desync=fake,multidisorder"
                    "--dpi-desync-split-pos=1,midsld"
                    "--dpi-desync-repeats=6"
                    "--dpi-desync-fooling=badsum"
                    "--dpi-desync-fake-tls-mod=rnd,dupsid"
                    "--dpi-desync-fake-tls=$FAKE_TLS"
                    "--new"
                )
            fi

            # General: multidisorder + ts fooling + TLS mod
            ARGS+=(
                "--filter-tcp=443,2053,2083,2087,2096,8443"
                "${HOSTLIST_OPT[@]}"
                "--dpi-desync=fake,multidisorder"
                "--dpi-desync-split-pos=1,midsld"
                "--dpi-desync-repeats=6"
                "--dpi-desync-fooling=ts"
                "--dpi-desync-fake-tls-mod=rnd,dupsid"
                "--dpi-desync-fake-tls=$FAKE_TLS"
            )

            if [ "$ENABLE_QUIC" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--filter-udp=443"
                    "${HOSTLIST_OPT[@]}"
                    "--dpi-desync=fake"
                    "--dpi-desync-repeats=6"
                    "--dpi-desync-fake-quic=$FAKE_DIR/quic_initial_www_google_com.bin"
                    "--dpi-desync-cutoff=n3"
                )
            fi

            if [ "$ENABLE_DISCORD_VOICE" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--filter-udp=19294-19344,50000-50100"
                    "--filter-l7=discord,stun"
                    "--dpi-desync=fake"
                    "--dpi-desync-repeats=6"
                    "--dpi-desync-fake-discord=$FAKE_DISCORD"
                    "--dpi-desync-fake-stun=$FAKE_STUN"
                    "--dpi-desync-cutoff=n4"
                )
            fi
            ;;

        "youtube_discord")
            if [ -f "$SYS_BADSUM" ] && [ -s "$SYS_BADSUM" ]; then
                ARGS+=(
                    "--filter-tcp=443,2053,2083,2087,2096,8443"
                    "--hostlist=$SYS_BADSUM"
                    "--dpi-desync=fake,multidisorder"
                    "--dpi-desync-split-pos=1,midsld"
                    "--dpi-desync-repeats=6"
                    "--dpi-desync-fooling=badsum"
                    "--dpi-desync-fake-tls-mod=rnd,dupsid"
                    "--dpi-desync-fake-tls=$FAKE_TLS"
                    "--new"
                )
            fi

            ARGS+=(
                "--filter-tcp=443,2053,2083,2087,2096,8443"
                "${HOSTLIST_OPT[@]}"
                "--dpi-desync=fake,multidisorder"
                "--dpi-desync-split-pos=1,midsld"
                "--dpi-desync-repeats=6"
                "--dpi-desync-fooling=ts"
                "--dpi-desync-fake-tls-mod=rnd,dupsid"
                "--dpi-desync-fake-tls=$FAKE_TLS"
            )

            if [ "$ENABLE_QUIC" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--filter-udp=443"
                    "${HOSTLIST_OPT[@]}"
                    "--dpi-desync=fake"
                    "--dpi-desync-repeats=6"
                    "--dpi-desync-fake-quic=$FAKE_DIR/quic_initial_www_google_com.bin"
                    "--dpi-desync-cutoff=n3"
                )
            fi

            if [ "$ENABLE_DISCORD_VOICE" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--filter-udp=19294-19344,50000-50100"
                    "--filter-l7=discord,stun"
                    "--dpi-desync=fake"
                    "--dpi-desync-repeats=6"
                    "--dpi-desync-fake-discord=$FAKE_DISCORD"
                    "--dpi-desync-fake-stun=$FAKE_STUN"
                    "--dpi-desync-cutoff=n4"
                )
            fi
            ;;

        "alt_fakedsplit")
            ARGS+=(
                "--filter-tcp=443,2053,2083,2087,2096,8443"
                "${HOSTLIST_OPT[@]}"
                "--dpi-desync=fake,fakedsplit"
                "--dpi-desync-repeats=6"
                "--dpi-desync-fooling=ts"
                "--dpi-desync-fake-tls=$FAKE_TLS"
            )
            if [ "$ENABLE_QUIC" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--filter-udp=443"
                    "${HOSTLIST_OPT[@]}"
                    "--dpi-desync=fake"
                    "--dpi-desync-repeats=6"
                    "--dpi-desync-fake-quic=$FAKE_DIR/quic_initial_www_google_com.bin"
                    "--dpi-desync-cutoff=n3"
                )
            fi
            if [ "$ENABLE_DISCORD_VOICE" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--dpi-desync-repeats=6"
                    "--filter-udp=19294-19344,50000-50100"
                    "--filter-l7=discord,stun"
                    "--dpi-desync=fake"
                    "--dpi-desync-cutoff=n4"
                )
            fi
            ;;

        "alt_split")
            ARGS+=(
                "--filter-tcp=443,2053,2083,2087,2096,8443"
                "${HOSTLIST_OPT[@]}"
                "--dpi-desync=fake,split2"
                "--dpi-desync-split-pos=1,midsld"
                "--dpi-desync-repeats=6"
                "--dpi-desync-fooling=ts"
                "--dpi-desync-fake-tls=$FAKE_TLS"
            )
            if [ "$ENABLE_QUIC" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--filter-udp=443"
                    "${HOSTLIST_OPT[@]}"
                    "--dpi-desync=fake"
                    "--dpi-desync-repeats=6"
                    "--dpi-desync-fake-quic=$FAKE_DIR/quic_initial_www_google_com.bin"
                    "--dpi-desync-cutoff=n3"
                )
            fi
            if [ "$ENABLE_DISCORD_VOICE" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--dpi-desync-repeats=6"
                    "--filter-udp=19294-19344,50000-50100"
                    "--filter-l7=discord,stun"
                    "--dpi-desync=fake"
                    "--dpi-desync-cutoff=n4"
                )
            fi
            ;;

        "multidisorder")
            ARGS+=(
                "--filter-tcp=443,2053,2083,2087,2096,8443"
                "${HOSTLIST_OPT[@]}"
                "--dpi-desync=multidisorder"
                "--dpi-desync-split-pos=1,midsld"
                "--dpi-desync-repeats=6"
            )
            if [ "$ENABLE_QUIC" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--filter-udp=443"
                    "${HOSTLIST_OPT[@]}"
                    "--dpi-desync=fake"
                    "--dpi-desync-repeats=6"
                    "--dpi-desync-fake-quic=$FAKE_DIR/quic_initial_www_google_com.bin"
                    "--dpi-desync-cutoff=n3"
                )
            fi
            if [ "$ENABLE_DISCORD_VOICE" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--dpi-desync-repeats=6"
                    "--filter-udp=19294-19344,50000-50100"
                    "--filter-l7=discord,stun"
                    "--dpi-desync=fake"
                    "--dpi-desync-cutoff=n4"
                )
            fi
            ;;

        "game_filter")
            # Minimal latency: TCP 443 (fake,multidisorder) + extended game UDP
            ARGS+=(
                "--filter-tcp=443"
                "${HOSTLIST_OPT[@]}"
                "--dpi-desync=fake,multidisorder"
                "--dpi-desync-split-pos=1,midsld"
                "--dpi-desync-repeats=6"
                "--dpi-desync-fooling=ts"
                "--dpi-desync-fake-tls-mod=rnd,dupsid"
                "--dpi-desync-fake-tls=$FAKE_TLS"
            )
            if [ "$ENABLE_QUIC" != "0" ]; then
                ARGS+=(
                    "--new"
                    "--filter-udp=443"
                    "${HOSTLIST_OPT[@]}"
                    "--dpi-desync=fake"
                    "--dpi-desync-repeats=6"
                    "--dpi-desync-fake-quic=$FAKE_DIR/quic_initial_www_google_com.bin"
                    "--dpi-desync-cutoff=n3"
                )
            fi
            ARGS+=(
                "--new"
                "--filter-udp=19294-19344,50000-50100,27015-27050,3074,3478-3480"
                "--dpi-desync=fake"
                "--dpi-desync-cutoff=n3"
            )
            ;;

        "custom")
            if [ -n "$CUSTOM_PARAMS" ]; then
                mapfile -d '' -t CUSTOM_ARR < <(python3 -c 'import shlex,sys; print("\0".join(shlex.split(sys.argv[1])), end="\0")' "$CUSTOM_PARAMS")
                ARGS+=("${CUSTOM_ARR[@]}")
            else
                ARGS+=(
                    "--filter-tcp=443,2053,2083,2087,2096,8443"
                    "${HOSTLIST_OPT[@]}"
                    "--dpi-desync=fake,multidisorder"
                    "--dpi-desync-split-pos=1,midsld"
                )
            fi
            ;;

        *)
            ARGS+=(
                "--filter-tcp=443,2053,2083,2087,2096,8443"
                "${HOSTLIST_OPT[@]}"
                "--dpi-desync=fake,multidisorder"
                "--dpi-desync-split-pos=1,midsld"
                "--dpi-desync-repeats=6"
                "--dpi-desync-fooling=ts"
                "--dpi-desync-fake-tls-mod=rnd,dupsid"
                "--dpi-desync-fake-tls=$FAKE_TLS"
            )
            ;;
    esac

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting Zapret engine ($PRESET, $IFACE, $DNS_PROVIDER)..." >> "$LOGFILE"

    # Start and supervise nfqws via systemd-run watchdog with auto-restart in 2s
    systemctl stop zapret-nfqws 2>/dev/null || true
    systemctl reset-failed zapret-nfqws 2>/dev/null || true

    # Create watchdog script for health monitoring
    cat > "$WATCHDOG_SCRIPT" << WATCHDOG_EOF
#!/bin/bash
# Zapret nfqws watchdog - checks health and restarts if needed
PIDFILE="$PIDFILE"
LOGFILE="$LOGFILE"
NFT_TABLE="$NFT_TABLE"

check_health() {
    # Check if nfqws process is alive
    if [ -f "\$PIDFILE" ]; then
        local pid=\$(cat "\$PIDFILE" 2>/dev/null)
        if [ -n "\$pid" ] && ! kill -0 "\$pid" 2>/dev/null; then
            echo "[\$(date '+%Y-%m-%d %H:%M:%S')] WATCHDOG: nfqws process \$pid is dead" >> "\$LOGFILE"
            return 1
        fi
    else
        if ! pgrep -x nfqws >/dev/null; then
            echo "[\$(date '+%Y-%m-%d %H:%M:%S')] WATCHDOG: nfqws not found in process list" >> "\$LOGFILE"
            return 1
        fi
    fi

    # Check if nftables rules exist
    if ! nft list table inet "\$NFT_TABLE" >/dev/null 2>&1; then
        echo "[\$(date '+%Y-%m-%d %H:%M:%S')] WATCHDOG: nftables table \$NFT_TABLE missing" >> "\$LOGFILE"
        return 1
    fi

    return 0
}

# Main watchdog loop
while true; do
    if ! check_health; then
        echo "[\$(date '+%Y-%m-%d %H:%M:%S')] WATCHDOG: Health check failed, triggering restart..." >> "\$LOGFILE"
        systemctl restart zapret-nfqws 2>/dev/null || true
    fi
    sleep 10
done
WATCHDOG_EOF
    chmod 0755 "$WATCHDOG_SCRIPT"

    # Stop old watchdog if exists
    systemctl stop zapret-watchdog 2>/dev/null || true

    if ! systemd-run --unit=zapret-nfqws \
        --description="Zapret nfqws DPI Engine Watchdog" \
        --property=Restart=always \
        --property=RestartSec=2 \
        --property=LimitNOFILE=65535 \
        --property=StandardOutput=append:$LOGFILE \
        --property=StandardError=append:$LOGFILE \
        "$BIN" "${ARGS[@]}" 2>/dev/null; then
        echo "systemd-run failed; launching nfqws directly..."
        nohup "$BIN" "${ARGS[@]}" >> "$LOGFILE" 2>&1 &
        echo $! > "$PIDFILE"
        chmod 0644 "$PIDFILE" 2>/dev/null || true
    fi

    # Start watchdog service
    systemd-run --unit=zapret-watchdog \
        --description="Zapret Health Watchdog" \
        --property=Restart=always \
        --property=RestartSec=5 \
        "$WATCHDOG_SCRIPT" 2>/dev/null || true

    if ! wait_for_process_start "zapret-nfqws" "$PIDFILE" 5 "nfqws"; then
        rollback_startup "$IFACE"
        return 1
    fi

    : > "$STATE_DIR/nft-active"
    chmod 0644 "$STATE_DIR/nft-active" 2>/dev/null || true
    apply_dns "$IFACE" "$DNS_PROVIDER"
    apply_ai_hosts "$ENABLE_AI_HOSTS"

    echo "Zapret engine started successfully with PID: $(cat "$PIDFILE" 2>/dev/null || true)"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Zapret engine active with PID: $(cat "$PIDFILE" 2>/dev/null || true)" >> "$LOGFILE"
}

run_blockcheck2() {
    local DOMAIN="${1:-rutracker.org}"
    local IFACE="${2:-any}"
    local DNS_PROVIDER="${3:-cloudflare}"
    if [[ ! "$DOMAIN" =~ ^[A-Za-z0-9.-]+(/[A-Za-z0-9._~/?&=+%-]*)?$ ]]; then
        echo "ERROR: Invalid blockcheck domain" >&2
        return 2
    fi
    if [ ! -x /opt/zapret2/blockcheck2.sh ]; then
        echo "ERROR: /opt/zapret2/blockcheck2.sh not found" >&2
        return 2
    fi

    # Track if engine was actively running before blockcheck
    local ENGINE_WAS_RUNNING=0
    if systemctl is-active --quiet zapret-nfqws || systemctl is-active --quiet zapret2-nfqws || [ -f "$STATE_DIR/nft-active" ]; then
        ENGINE_WAS_RUNNING=1
    fi

    # Guarantee DNS restoration if engine was inactive
    restore_blockcheck_dns() {
        if [ "$ENGINE_WAS_RUNNING" -eq 0 ]; then
            echo "Restoring DNS after blockcheck run (engine was not running)..."
            revert_dns "$IFACE"
        fi
    }
    trap restore_blockcheck_dns EXIT INT TERM

    apply_dns "$IFACE" "$DNS_PROVIDER"
    sleep 1
    echo "Running non-interactive Blockcheck2 for $DOMAIN. Other bypass engines must be stopped."
    local RC=0
    timeout 900 env BATCH=1 TEST=standard DOMAINS="$DOMAIN" IPVS=4 \
        ENABLE_HTTP=0 ENABLE_HTTPS_TLS12=1 ENABLE_HTTPS_TLS13=0 ENABLE_HTTP3=0 \
        REPEATS=1 PARALLEL=0 SCANLEVEL=veryquick \
        /opt/zapret2/blockcheck2.sh || RC=$?
    trap - EXIT INT TERM
    restore_blockcheck_dns
    return $RC
}

sync_bases() {
    acquire_lock
    echo "Syncing updated lists and fakes to /etc/zapret/..."
    mkdir -p /etc/zapret
    if [ -d "$DIR/fake" ]; then
        cp -r "$DIR/fake" /etc/zapret/ 2>/dev/null || true
    fi
    if [ -d "$DIR/lists" ]; then
        cp -r "$DIR/lists" /etc/zapret/ 2>/dev/null || true
    fi
    sync_general_hostlist
    if [ -f "$DIR/badsum_hosts.txt" ]; then
        cp -f "$DIR/badsum_hosts.txt" /etc/zapret/badsum_hosts.txt 2>/dev/null || true
    fi
    if [ -f "$DIR/exclude.txt" ]; then
        cp -f "$DIR/exclude.txt" /etc/zapret/exclude.txt 2>/dev/null || true
    fi
    chmod -R 755 /etc/zapret 2>/dev/null || true
    echo "Sync completed successfully."
}

build_ipset() {
    echo "Aggregating IP subnets from list-general.txt using mdig and ip2net..."
    local src="$DIR/list-general.txt"
    [ -f "/etc/zapret/list-general.txt" ] && src="/etc/zapret/list-general.txt"
    if [ ! -f "$src" ]; then
        echo "ERROR: list-general.txt not found!" >&2
        exit 1
    fi
    mkdir -p /etc/zapret
    "$DIR/bin/mdig" --family=4 --threads=32 < "$src" | "$DIR/bin/ip2net" > /etc/zapret/ipset-general.txt
    chmod 644 /etc/zapret/ipset-general.txt
    local cnt=$(wc -l < /etc/zapret/ipset-general.txt 2>/dev/null || echo 0)
    echo "Subnets generated in /etc/zapret/ipset-general.txt ($cnt subnets)."
}

install_polkit() {
    check_root
    echo "Installing Polkit policy for Zapret GUI..."
    local POLICY_SRC="$DIR/moe.zapret.gui.policy"
    local POLICY_DST="/usr/share/polkit-1/actions/moe.zapret.gui.policy"
    mkdir -p /usr/share/polkit-1/actions
    if [ -f "$POLICY_SRC" ]; then
        sed -e "s|<annotate key=\"org.freedesktop.policykit.exec.path\">.*engine.sh</annotate>|<annotate key=\"org.freedesktop.policykit.exec.path\">$DIR/engine.sh</annotate>|g" \
            "$POLICY_SRC" > "$POLICY_DST"
        chmod 644 "$POLICY_DST"
        echo "Polkit policy installed: $POLICY_DST"
    fi

    # pkexec authenticates the administrator; unrestricted NOPASSWD rules are removed.
    rm -f /etc/sudoers.d/zapret-gui
    echo "Polkit setup completed; legacy sudoers rule removed."
}

if [ "${BASH_SOURCE[0]}" = "$0" ]; then
    set -euo pipefail
    trap release_lock EXIT INT TERM

    if [ "$1" != "status" ]; then
        check_root
    fi

    case "$1" in
        start)
            start_engine "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}" "${11}" "${12}" "${13}" "${14}" "${15}"
            ;;
        stop)
            stop_engine "$2"
            ;;
        restart)
            start_engine "$2" "$3" "$4" "$5" "$6" "$7" "$8" "$9" "${10}" "${11}" "${12}" "${13}" "${14}" "${15}"
            ;;
        status)
            status_engine
            ;;
        dns)
            apply_dns "$2" "$3"
            ;;
        tune)
            tune_network
            ;;
        hosts)
            apply_ai_hosts "$2"
            ;;
        clean_hosts)
            clean_ai_hosts
            ;;
        sync)
            sync_bases
            ;;
        ip2net|build_ipset)
            build_ipset
            ;;
        blockcheck2)
            run_blockcheck2 "$2" "$3" "$4"
            ;;
        install_polkit)
            install_polkit
            ;;
        *)
            echo "Usage: $0 {start|stop|restart|status|dns|tune|hosts|clean_hosts|sync|ip2net|install_polkit|blockcheck2} [preset] [interface] [dns_provider] [enable_ai_hosts] [enable_quic] [enable_discord_voice] [conntrack_limit] [hostlist_mode] [engine_mode] [custom_params] [zapret2_preset] [enable_youtube] [enable_discord_tcp] [enable_general_https]"
            exit 1
            ;;
    esac
fi


