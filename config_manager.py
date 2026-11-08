"""Configuration schema, validation, migration, and persistence."""

import os
import json
import logging
import tempfile

logger = logging.getLogger("zapret_gui.config")

CONFIG_VERSION = 2

VALID_ENGINE_MODES = ("nfqws2", "nfqws", "tpws")
DEFAULT_CUSTOM_PARAMS = (
    "--filter-tcp=443,2053,2083,2087,2096,8443 "
    "--dpi-desync=fake,multidisorder --dpi-desync-split-pos=1,midsld"
)

DEFAULT_CONFIG = {
    "version": CONFIG_VERSION,
    "preset": "general",
    "dns": "cloudflare",
    "iface": "any",
    "enable_ai_hosts": True,
    "ai_hosts": True,
    "dpi_auto": True,
    "enable_quic": True,
    "enable_discord_voice": True,
    "conntrack_limit": 12,
    "hostlist_mode": "all_except_exclude",
    "engine_mode": "nfqws2",
    "zapret2_preset": "Default (circular)",
    "custom_params": DEFAULT_CUSTOM_PARAMS,
    "enable_youtube": True,
    "enable_discord_tcp": True,
    "enable_general_https": True,
    "enable_auto_hostlist": False,
    "healer_enabled": True,
    "minimize_to_tray": True,
    "onboarding_completed": False,
    "block_gov_media": False,
    "block_telemetry": False,
    "enable_wssize": False,
    "debug_log": False,
    "window_width": 1080,
    "window_height": 720,
    "window_maximized": False,
    "last_page": "dashboard",
    "theme": "dark",
}


def _safe_int(val, default=12, min_val=1, max_val=64):
    try:
        if val is None:
            return default
        ival = int(val)
        if min_val <= ival <= max_val:
            return ival
        return default
    except (TypeError, ValueError):
        return default


def _safe_bool(val, default=True):
    if isinstance(val, bool):
        return val
    return default


def migrate_config(data: dict) -> dict:
    """Validate and migrate config dictionary from older or unversioned schema."""
    if not isinstance(data, dict):
        return dict(DEFAULT_CONFIG)

    out = dict(DEFAULT_CONFIG)

    # 1. Version migration
    raw_version = data.get("version", 1)
    try:
        version = int(raw_version)
    except (TypeError, ValueError):
        version = 1

    # 2. Key normalization: ai_hosts vs enable_ai_hosts
    ai_hosts_val = data.get("enable_ai_hosts", data.get("ai_hosts", DEFAULT_CONFIG["enable_ai_hosts"]))
    out["enable_ai_hosts"] = _safe_bool(ai_hosts_val, True)
    out["ai_hosts"] = out["enable_ai_hosts"]

    # 3. Conntrack limit clamping / sanitization
    out["conntrack_limit"] = _safe_int(
        data.get("conntrack_limit", DEFAULT_CONFIG["conntrack_limit"]),
        default=12,
        min_val=1,
        max_val=64
    )

    # 4. Minimize to tray
    raw_tray = data.get("minimize_to_tray")
    if raw_tray is None:
        out["minimize_to_tray"] = True
    else:
        out["minimize_to_tray"] = _safe_bool(raw_tray, True)

    # 5. Engine mode
    raw_engine = data.get("engine_mode")
    if raw_engine in VALID_ENGINE_MODES:
        out["engine_mode"] = str(raw_engine)
    else:
        out["engine_mode"] = "nfqws2"

    # 6. Boolean flags
    for bool_key in (
        "dpi_auto",
        "enable_quic",
        "enable_discord_voice",
        "enable_youtube",
        "enable_discord_tcp",
        "enable_general_https",
        "enable_auto_hostlist",
        "healer_enabled",
        "onboarding_completed",
        "block_gov_media",
        "block_telemetry",
        "enable_wssize",
        "debug_log",
    ):
        if bool_key in data:
            out[bool_key] = _safe_bool(data[bool_key], DEFAULT_CONFIG[bool_key])

    # 7. String fields
    for str_key in (
        "preset",
        "dns",
        "iface",
        "hostlist_mode",
        "zapret2_preset",
        "custom_params",
    ):
        if str_key in data and isinstance(data[str_key], str):
            out[str_key] = data[str_key]

    # 8. Window geometry and last active page
    out["window_width"] = _safe_int(
        data.get("window_width", DEFAULT_CONFIG["window_width"]),
        default=1080,
        min_val=400,
        max_val=7680,
    )
    out["window_height"] = _safe_int(
        data.get("window_height", DEFAULT_CONFIG["window_height"]),
        default=720,
        min_val=300,
        max_val=4320,
    )
    valid_pages = (
        "dashboard", "presets", "profiles", "zapret2", "dpi_mode",
        "monitor", "dns", "hosts", "updates", "blockcheck", "orchestra", "logs", "settings"
    )
    raw_page = data.get("last_page")
    if raw_page in valid_pages:
        out["last_page"] = str(raw_page)
    else:
        out["last_page"] = "dashboard"

    out["window_maximized"] = _safe_bool(data.get("window_maximized"), False)

    raw_theme = data.get("theme")
    if raw_theme in ("dark", "light", "system"):
        out["theme"] = str(raw_theme)
    else:
        out["theme"] = "dark"

    out["version"] = CONFIG_VERSION
    return out


def load_config_from_file(path: str) -> dict:
    """Safely load config from JSON file with migration and default fallback."""
    if not os.path.exists(path):
        return dict(DEFAULT_CONFIG)

    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return migrate_config(data)
    except Exception as e:
        logger.warning("Failed to load or parse config from %s: %s. Using defaults.", path, e)
        return dict(DEFAULT_CONFIG)


def save_config_to_file(path: str, data: dict) -> bool:
    """Atomically save config dictionary to JSON file."""
    try:
        clean_data = migrate_config(data)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        dir_name = os.path.dirname(os.path.abspath(path))
        with tempfile.NamedTemporaryFile("w", dir=dir_name, delete=False, encoding="utf-8") as tf:
            temp_name = tf.name
            json.dump(clean_data, tf, indent=2, ensure_ascii=False)
            tf.flush()
            os.fsync(tf.fileno())

        os.replace(temp_name, path)
        return True
    except Exception as e:
        logger.error("Failed to save config to %s: %s", path, e)
        if "temp_name" in locals() and os.path.exists(temp_name):
            try:
                os.remove(temp_name)
            except OSError:
                pass
        return False


def should_show_onboarding(config: dict) -> bool:
    """Check if onboarding dialog should be displayed."""
    if not isinstance(config, dict):
        return True
    return not bool(config.get("onboarding_completed", False))


def mark_onboarding_completed(config_file: str = None, in_memory_config: dict = None) -> bool:
    """Mark onboarding tour as completed both in-memory and on disk."""
    if isinstance(in_memory_config, dict):
        in_memory_config["onboarding_completed"] = True

    if not config_file:
        return True

    try:
        data = load_config_from_file(config_file)
        data["onboarding_completed"] = True
        return save_config_to_file(config_file, data)
    except Exception as e:
        logger.error("Failed to mark onboarding completed: %s", e)
        return False
