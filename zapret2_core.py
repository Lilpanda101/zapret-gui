#!/usr/bin/env python3
"""Platform adapter and profile tools for the Linux nfqws2 engine."""

from __future__ import annotations

import argparse
import json
import logging
import os
import pwd
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from typing import Iterable

APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "zapret2"
BUILTIN_PRESETS = DATA_DIR / "presets" / "winws2_builtin"


def _calling_user_home() -> Path:
    if os.geteuid() == 0:
        username = os.environ.get("SUDO_USER", "")
        try:
            if not username and os.environ.get("PKEXEC_UID"):
                username = pwd.getpwuid(int(os.environ["PKEXEC_UID"])).pw_name
            if username and username != "root":
                return Path(pwd.getpwnam(username).pw_dir)
        except (KeyError, ValueError):
            pass
    return Path.home()


USER_PRESETS = _calling_user_home() / ".config" / "zapret-gui" / "presets"

logger = logging.getLogger("zapret_gui.zapret2_core")
BUILTIN_VERSION_HEADER_PREFIX = "# BuiltinVersion:"
FAKE_DIR = APP_DIR / "fake"
LISTS_DIR = APP_DIR / "lists"
NFQWS2 = Path("/usr/bin/nfqws2")
MAX_PRESET_SIZE = 4 * 1024 * 1024


class PresetError(ValueError):
    pass


@dataclass
class Profile:
    index: int
    name: str
    enabled: bool
    start: int
    end: int
    filters: list[str] = field(default_factory=list)
    strategies: list[str] = field(default_factory=list)


@dataclass
class PresetDocument:
    lines: list[str]
    profiles: list[Profile]

    @classmethod
    def parse(cls, text: str) -> "PresetDocument":
        lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
        starts: list[int] = []
        seen_profile = False
        for index, raw in enumerate(lines):
            stripped = raw.strip()
            if stripped == "--new" or stripped.startswith("--new="):
                starts.append(index)
                seen_profile = True
            elif not seen_profile and _is_profile_line(stripped):
                starts.append(index)
                seen_profile = True
        profiles: list[Profile] = []
        for number, start in enumerate(starts):
            end = starts[number + 1] if number + 1 < len(starts) else len(lines)
            body = lines[start:end]
            if not any(_has_profile_content(line) for line in body):
                continue
            name = f"Профиль {len(profiles) + 1}"
            enabled = True
            filters: list[str] = []
            strategies: list[str] = []
            for raw in body:
                stripped = raw.strip()
                if stripped.startswith("--new="):
                    val = stripped.split("=", 1)[1].strip()
                    name = val.strip("\"'") or name
                elif stripped.startswith("--name="):
                    val = stripped.split("=", 1)[1].strip()
                    name = val.strip("\"'") or name
                elif re.match(r"^--skip(?:\s*#.*)?$", stripped):
                    enabled = False
                elif _is_filter_line(stripped):
                    filters.append(stripped)
                elif stripped.startswith(("--lua-desync=", "--payload=", "--in-range=", "--out-range=")):
                    strategies.append(stripped)
            profiles.append(Profile(len(profiles), name, enabled, start, end, filters, strategies))
        return cls(lines, profiles)

    def text(self) -> str:
        return "\n".join(self.lines).rstrip("\n") + "\n"

    def profile_text(self, index: int) -> str:
        profile = self._profile(index)
        return "\n".join(self.lines[profile.start:profile.end]).strip("\n") + "\n"

    def set_profile_enabled(self, index: int, enabled: bool) -> None:
        profile = self._profile(index)
        body = self.lines[profile.start:profile.end]
        body = [line for line in body if not re.match(r"^--skip(?:\s*#.*)?$", line.strip())]
        if not enabled:
            insert_at = 1 if body and body[0].strip().startswith("--new") else 0
            while insert_at < len(body) and not body[insert_at].strip():
                insert_at += 1
            if insert_at < len(body) and body[insert_at].strip().startswith(("--name=", "--name ")):
                insert_at += 1
            body.insert(insert_at, "--skip")
        self.lines[profile.start:profile.end] = body
        self._reparse()

    def replace_profile(self, index: int, text: str) -> None:
        profile = self._profile(index)
        replacement = PresetDocument.parse(text)
        if len(replacement.profiles) != 1:
            raise PresetError("Редактор должен содержать ровно один профиль")
        new_lines = text.replace("\r\n", "\n").replace("\r", "\n").strip("\n").split("\n")
        # Сохранение структуры --new при редактировании профилей с index > 0
        if index > 0 and new_lines:
            first_stripped = new_lines[0].strip()
            if not (first_stripped == "--new" or first_stripped.startswith("--new=")):
                new_lines.insert(0, "--new")
        self.lines[profile.start:profile.end] = new_lines
        self._reparse()

    def _profile(self, index: int) -> Profile:
        if not 0 <= index < len(self.profiles):
            raise PresetError(f"Профиль {index + 1} не существует")
        return self.profiles[index]

    def _reparse(self) -> None:
        parsed = PresetDocument.parse(self.text())
        self.lines = parsed.lines
        self.profiles = parsed.profiles


def _has_profile_content(line: str) -> bool:
    stripped = line.strip()
    return bool(stripped and not stripped.startswith("#") and stripped != "--new")


def _is_filter_line(stripped: str) -> bool:
    return stripped.startswith((
        "--filter-", "--hostlist=", "--hostlist-domains=", "--hostlist-exclude=",
        "--hostlist-exclude-domains=", "--hostlist-auto=", "--ipset=", "--ipset-ip=",
        "--ipset-exclude=", "--ipset-exclude-ip=",
    ))


def _is_profile_line(stripped: str) -> bool:
    return _is_filter_line(stripped) or stripped.startswith((
        "--name=", "--template", "--import=", "--skip", "--comment=", "--cookie",
        "--payload=", "--in-range=", "--out-range=", "--lua-desync=",
    ))



GAME_PRESET_WARNING = (
    "Пресеты game filter используют ipset вместо SNI hostlist "
    "и могут сбоить при смене пулов IP Google/Discord."
)


def normalize_preset_id(preset_id: str) -> str:
    """Нормализует ID пресета к виду '<name>.txt', убирая дублирование расширений и path traversal."""
    if not preset_id or not isinstance(preset_id, str):
        raise PresetError("Некорректное имя пресета")
    raw = preset_id.strip()
    value = Path(raw).name
    if value != raw or value in {"", ".", ".."}:
        raise PresetError("Некорректное имя пресета")
    while value.lower().endswith(".txt"):
        value = value[:-4].strip()
    if not value or value in {"", ".", ".."}:
        raise PresetError("Некорректное имя пресета")
    return f"{value}.txt"


def _safe_preset_id(preset_id: str) -> str:
    return normalize_preset_id(preset_id)


def is_top_preset(name: str) -> bool:
    """Проверяет, относится ли пресет к рекомендуемым/топовым."""
    return categorize_preset(name) == "recommended"


def categorize_preset(name: str, text: str = "") -> str:
    """Категоризирует пресет на 'recommended', 'game', 'circular' или 'other'."""
    stem = Path(name).stem if name.endswith(".txt") else name
    stem_lower = stem.casefold().strip()

    # 1. game: если в названии есть 'game filter' или 'game'
    if "game filter" in stem_lower or "game" in stem_lower:
        return "game"

    # 2. recommended: 'general ALT', 'Default (circular)', 'general FAKE TLS AUTO',
    # 'ALL TCP & UDP hostfakesplit' (и вариации)
    recommended_prefixes = (
        "general alt",
        "default (circular)",
        "general fake tls auto",
        "all tcp & udp hostfakesplit",
    )
    if any(stem_lower == p or stem_lower.startswith(p) for p in recommended_prefixes):
        return "recommended"

    # 3. circular: если в названии есть 'circular' или в пресете есть zapret-multishake / zapret-auto
    if (
        "circular" in stem_lower
        or "zapret-multishake" in text
        or "zapret-auto" in text
        or is_circular(text)
    ):
        return "circular"

    # 4. other: все остальные
    return "other"


def get_preset_warning(name: str, text: str = "") -> str | None:
    if categorize_preset(name, text) == "game":
        return GAME_PRESET_WARNING
    return None


RUNTIME_AUTOHOSTLIST = Path("/etc/zapret/zapret2-runtime/writable/autohostlist.txt")


def get_auto_hostlist_path() -> Path:
    if RUNTIME_AUTOHOSTLIST.is_file():
        return RUNTIME_AUTOHOSTLIST
    if os.geteuid() == 0:
        return Path("/var/lib/zapret-gui/autohostlist.txt")
    return _calling_user_home() / ".config" / "zapret-gui" / "autohostlist.txt"


def get_auto_hostlist_stats(path: Path | None = None) -> dict:
    target = path or get_auto_hostlist_path()
    if not target.is_file():
        return {"count": 0, "size": 0, "domains": []}
    try:
        size = target.stat().st_size
        text = target.read_text(encoding="utf-8", errors="replace")
        domains = [
            line.strip()
            for line in text.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return {
            "count": len(domains),
            "size": size,
            "domains": domains,
        }
    except OSError:
        return {"count": 0, "size": 0, "domains": []}


def clear_auto_hostlist(path: Path | None = None) -> bool:
    target = path or get_auto_hostlist_path()
    try:
        if target.exists():
            target.write_text("", encoding="utf-8")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()
        return True
    except OSError:
        return False


def _find_preset_by_filename(filename: str, app_dir: Path = APP_DIR) -> Path | None:
    """Повторный поиск пресета по имени файла (регистр букв не важен).

    Нужен, когда файл выбранного пресета пропал между получением пути и
    чтением: пользовательская копия могла уйти в replaced при обновлении
    встроенного пресета, и пресет теперь находится по встроенному пути или
    записан на диске в другом регистре. Находится только тот же пресет по
    имени файла, другой пресет не подставляется никогда.
    """
    for directory in (USER_PRESETS, app_dir / "zapret2" / "presets" / "winws2_builtin"):
        if not directory.is_dir():
            continue
        for path in directory.glob("*.txt"):
            if path.name.casefold() == filename.casefold() and path.is_file():
                return path
    return None


def re_resolve_preset_path(path: Path, app_dir: Path = APP_DIR) -> Path:
    """Если ранее полученный путь к выбранному пресету пропал, ищет его заново один раз по имени файла."""
    if path.is_file():
        return path
    found = _find_preset_by_filename(path.name, app_dir)
    if found is not None:
        return found
    raise PresetError(f"Пресет не найден: {path.stem}")


def preset_path(preset_id: str, app_dir: Path = APP_DIR) -> Path:
    filename = normalize_preset_id(preset_id)
    user_path = USER_PRESETS / filename
    if user_path.is_file():
        return user_path
    builtin = app_dir / "zapret2" / "presets" / "winws2_builtin" / filename
    if builtin.is_file():
        return builtin
    found = _find_preset_by_filename(filename, app_dir)
    if found is not None:
        return found
    raise PresetError(f"Пресет не найден: {Path(filename).stem}")


def load_preset(preset_id: str, app_dir: Path = APP_DIR) -> str:
    path = preset_path(preset_id, app_dir)
    try:
        if path.stat().st_size > MAX_PRESET_SIZE:
            raise PresetError("Пресет больше 4 МиБ")
        return path.read_text(encoding="utf-8-sig")
    except FileNotFoundError:
        path = re_resolve_preset_path(path, app_dir)
        if path.stat().st_size > MAX_PRESET_SIZE:
            raise PresetError("Пресет больше 4 МиБ")
        return path.read_text(encoding="utf-8-sig")


def discover_presets(app_dir: Path = APP_DIR) -> list[dict]:
    builtin = app_dir / "zapret2" / "presets" / "winws2_builtin"
    paths: dict[str, Path] = {}
    if builtin.is_dir():
        for path in builtin.glob("*.txt"):
            try:
                paths[normalize_preset_id(path.name)] = path
            except PresetError:
                continue
    if USER_PRESETS.is_dir():
        for path in USER_PRESETS.glob("*.txt"):
            try:
                paths[normalize_preset_id(path.name)] = path
            except PresetError:
                continue
    result = []
    for filename, path in sorted(paths.items(), key=lambda item: item[0].casefold()):
        title = Path(filename).stem
        try:
            text = path.read_text(encoding="utf-8-sig")
            document = PresetDocument.parse(text)
            category = categorize_preset(filename, text)
            item = {
                "id": filename, "title": title, "path": str(path),
                "profiles": len(document.profiles),
                "enabled_profiles": sum(profile.enabled for profile in document.profiles),
                "circular": is_circular(text) or category == "circular",
                "category": category,
                "custom": USER_PRESETS in path.parents,
            }
            if category == "game":
                item["warning"] = GAME_PRESET_WARNING
            result.append(item)
        except (OSError, UnicodeError) as exc:
            category = categorize_preset(filename, "")
            item = {"id": filename, "title": title, "category": category, "error": str(exc)}
            if category == "game":
                item["warning"] = GAME_PRESET_WARNING
            result.append(item)
    return result


def save_user_preset(preset_id: str, text: str) -> Path:
    filename = normalize_preset_id(preset_id)
    document = PresetDocument.parse(text)
    if not document.profiles or not any(profile.enabled for profile in document.profiles):
        raise PresetError("Нужен хотя бы один включённый профиль")
    if len(text.encode("utf-8")) > MAX_PRESET_SIZE:
        raise PresetError("Пресет больше 4 МиБ")
    USER_PRESETS.mkdir(parents=True, exist_ok=True)
    destination = USER_PRESETS / filename
    _atomic_write(destination, document.text())
    return destination


def import_preset(source: Path) -> Path:
    if not source.is_file() or source.stat().st_size > MAX_PRESET_SIZE:
        raise PresetError("Файл пресета не найден или больше 4 МиБ")
    text = source.read_text(encoding="utf-8-sig")
    if "--lua-desync=" not in text:
        raise PresetError("Это не пресет Zapret2: отсутствует --lua-desync")
    return save_user_preset(source.name, text)


def reset_user_preset(preset_id: str) -> None:
    path = USER_PRESETS / normalize_preset_id(preset_id)
    if path.exists():
        path.unlink()


def builtin_preset_version(text: str) -> tuple[int, ...] | None:
    """Номер версии из шапки пресета ('# BuiltinVersion: 2.44' дает (2, 44)); None, если номера нет."""
    for raw in str(text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if not line.startswith("#"):
            return None
        if not line.startswith(BUILTIN_VERSION_HEADER_PREFIX):
            continue
        parts = line[len(BUILTIN_VERSION_HEADER_PREFIX):].strip().split(".")
        try:
            return tuple(int(part) for part in parts)
        except ValueError:
            return None
    return None


def _version_text(version: tuple[int, ...] | None) -> str:
    return ".".join(str(part) for part in version) if version else ""


@dataclass
class BuiltinOverrideRefreshResult:
    refreshed: list[tuple[str, str, str]] = field(default_factory=list)
    failed: list[tuple[str, str]] = field(default_factory=list)


def replaced_presets_dir() -> Path:
    """Каталог прежних копий внутри пользовательского каталога пресетов: presets/replaced."""
    return USER_PRESETS / "replaced"


def refresh_outdated_builtin_overrides(app_dir: Path = APP_DIR) -> BuiltinOverrideRefreshResult:
    """Заменяет пользовательские копии встроенных пресетов, отставшие по BuiltinVersion.

    Если у встроенного пресета номер '# BuiltinVersion:' больше, чем в копии
    пользователя (или в копии номера нет), копия заменяется встроенным тем же
    действием, что ручной сброс к встроенному: прежняя копия сохраняется в
    presets/replaced внутри пользовательского каталога пресетов, сама копия
    удаляется, и дальше работает встроенный пресет. Каждая замена пишется в
    лог. Пресеты пользователя с другими именами файлов не трогаются.
    """
    result = BuiltinOverrideRefreshResult()
    builtin_dir = app_dir / "zapret2" / "presets" / "winws2_builtin"
    if not builtin_dir.is_dir() or not USER_PRESETS.is_dir():
        return result
    for builtin_path in sorted(builtin_dir.glob("*.txt"), key=lambda p: p.name.casefold()):
        user_path = USER_PRESETS / builtin_path.name
        if not user_path.is_file():
            continue
        try:
            builtin_version = builtin_preset_version(builtin_path.read_text(encoding="utf-8-sig"))
            if builtin_version is None:
                continue
            user_version = builtin_preset_version(user_path.read_text(encoding="utf-8-sig"))
            if user_version is not None and user_version >= builtin_version:
                continue
            backup_dir = replaced_presets_dir()
            backup_dir.mkdir(parents=True, exist_ok=True)
            (backup_dir / builtin_path.name).write_bytes(user_path.read_bytes())
            user_path.unlink()
        except OSError as exc:
            result.failed.append((builtin_path.name, str(exc)))
            logger.warning("Пресет '%s' не удалось заменить встроенным: %s", builtin_path.name, exc)
            continue
        result.refreshed.append((builtin_path.name, _version_text(user_version), _version_text(builtin_version)))
        logger.info(
            "Пресет '%s' заменён встроенным версии %s (у вашей копии была %s); прежняя копия сохранена в presets/replaced",
            builtin_path.name,
            _version_text(builtin_version),
            _version_text(user_version) or "без номера",
        )
    return result


def is_circular(text: str) -> bool:
    return any(
        line.strip().startswith(("--lua-desync=circular", "--lua-desync=shadow_probe"))
        for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


@dataclass
class FirewallSpec:
    tcp_out: list[str] = field(default_factory=list)
    udp_out: list[str] = field(default_factory=list)
    tcp_in: list[str] = field(default_factory=list)
    udp_in: list[str] = field(default_factory=list)
    tcp_empty: bool = False


@dataclass
class AdaptedPreset:
    arguments: list[str]
    firewall: FirewallSpec
    warnings: list[str]
    profile_count: int


def _split_option(line: str) -> list[str]:
    try:
        return shlex.split(line, posix=True)
    except ValueError as exc:
        raise PresetError(f"Ошибка кавычек в строке: {line[:160]}: {exc}") from exc


def _validate_ports(value: str) -> list[str]:
    if value == "*":
        return ["1-65535"]
    result = []
    for part in value.split(","):
        part = part.strip()
        if not re.fullmatch(r"(?:\d{1,5})(?:-\d{1,5})?", part):
            raise PresetError(f"Неподдерживаемый фильтр портов: {value}")
        low, _, high = part.partition("-")
        if not 1 <= int(low) <= 65535 or (high and not int(low) <= int(high) <= 65535):
            raise PresetError(f"Порт вне диапазона: {part}")
        if part not in result:
            result.append(part)
    return result


def _resource_path(value: str, option: str, app_dir: Path, data_dir: Path,
                   writable_dir: Path, missing: list[str]) -> str:
    original = value
    prefix = ""
    if option == "--lua-init" and not value.startswith("@"):
        return original
    if option == "--lua-init" and value.startswith("@"):
        prefix, value = "@", value[1:]
    elif option == "--blob":
        match = re.match(r"^([^:]+):((?:\+\d+)?)@(.+)$", value)
        if not match:
            return original
        name, offset, value = match.groups()
        prefix = f"{name}:{offset}@"
    value = value.replace("\\", "/").strip('"')
    if option in {"--hostlist-auto", "--hostlist-auto-debug"}:
        target = writable_dir / Path(value).name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=True)
        return str(target)
    if value.startswith("bin/"):
        target = app_dir / "fake" / value[4:]
    elif value.startswith("lua/"):
        target = data_dir / value
    elif value.startswith("lists/"):
        target = app_dir / value
    elif value.startswith("windivert.filter/"):
        target = data_dir / value
    else:
        raise PresetError(f"Небезопасный или неизвестный путь {original} в {option}")
    if ".." in Path(value).parts or not target.is_file():
        missing.append(f"{option}: {original}")
        return original
    return prefix + str(target)


def adapt_preset(text: str, app_dir: Path = APP_DIR, data_dir: Path = DATA_DIR,
                 writable_dir: Path = Path("/var/lib/zapret-gui"),
                 enable_auto_hostlist: bool = False) -> AdaptedPreset:
    document = PresetDocument.parse(text)
    enabled_count = sum(profile.enabled for profile in document.profiles)
    if not enabled_count:
        raise PresetError("В пресете нет включённых профилей")
    firewall = FirewallSpec()
    arguments: list[str] = []
    warnings: list[str] = []
    missing: list[str] = []
    raw_parts: list[str] = []
    file_options = {
        "--hostlist", "--hostlist-exclude", "--hostlist-auto", "--hostlist-auto-debug",
        "--ipset", "--ipset-exclude", "--lua-init", "--blob",
    }
    for raw in document.lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        for argument in _split_option(stripped):
            option, separator, value = argument.partition("=")
            option = option.lower()
            if option.startswith("--wf-"):
                if not separator:
                    if option != "--wf-l3":
                        warnings.append(f"Пропущен Windows-фильтр: {option}")
                    continue
                if option == "--wf-tcp-out":
                    firewall.tcp_out = _validate_ports(value)
                elif option == "--wf-udp-out":
                    firewall.udp_out = _validate_ports(value)
                elif option == "--wf-tcp-in":
                    firewall.tcp_in = _validate_ports(value)
                elif option == "--wf-udp-in":
                    firewall.udp_in = _validate_ports(value)
                elif option == "--wf-tcp-empty":
                    firewall.tcp_empty = True
                elif option == "--wf-raw-part":
                    raw_parts.append(value)
                elif option != "--wf-l3":
                    warnings.append(f"Пропущен Windows-фильтр: {option}")
                continue
            if option in {"--qnum", "--daemon", "--pidfile", "--user", "--uid", "--dry-run", "--intercept"}:
                continue
            if option == "--chdir":
                continue
            if option == "--writable":
                arguments.append(f"--writable={writable_dir}")
                continue
            if option == "--ipcache-lifetime" and separator:
                try:
                    val_int = int(value)
                    if 0 < val_int < 86400:
                        argument = "--ipcache-lifetime=86400"
                except ValueError:
                    pass
            if option in file_options and separator:
                argument = f"{option}={_resource_path(value, option, app_dir, data_dir, writable_dir, missing)}"
            arguments.append(argument)
    if raw_parts:
        for port in ("3478-3480", "19294-19344", "50000-50100"):
            if port not in firewall.udp_out:
                firewall.udp_out.append(port)
        if firewall.udp_in:
            for port in ("3478-3480", "19294-19344", "50000-50100"):
                if port not in firewall.udp_in:
                    firewall.udp_in.append(port)
        warnings.append("WinDivert raw-фильтры заменены UDP-группами Discord/STUN; основные wf-диапазоны сохранены")
    if missing:
        raise PresetError("Отсутствуют ресурсы:\n" + "\n".join(sorted(set(missing))[:20]))
    if not firewall.tcp_out and not firewall.udp_out:
        raise PresetError("В пресете нет --wf-tcp-out или --wf-udp-out")
    if not any(argument.startswith("--lua-desync=") for argument in arguments):
        raise PresetError("В пресете нет активной Lua-стратегии")

    if enable_auto_hostlist:
        writable_dir.mkdir(parents=True, exist_ok=True)
        autohostlist_file = writable_dir / "autohostlist.txt"
        autohostlist_file.touch(exist_ok=True)
        try:
            autohostlist_file.chmod(0o666)
        except OSError:
            pass
        auto_arg = f"--hostlist-auto={autohostlist_file}"

        chunks: list[list[str]] = []
        current_chunk: list[str] = []
        for arg in arguments:
            if arg == "--new" or arg.startswith("--new="):
                if current_chunk:
                    chunks.append(current_chunk)
                current_chunk = [arg]
            else:
                current_chunk.append(arg)
        if current_chunk:
            chunks.append(current_chunk)

        new_arguments: list[str] = []
        for chunk in chunks:
            has_hostlist = any(
                a.startswith(("--hostlist=", "--hostlist-domains=")) or a == "--hostlist"
                for a in chunk
            )
            has_auto = any(
                a.startswith("--hostlist-auto=") or a == "--hostlist-auto"
                for a in chunk
            )
            if has_hostlist and not has_auto:
                last_hl_idx = max(
                    i for i, a in enumerate(chunk)
                    if a.startswith(("--hostlist=", "--hostlist-domains=")) or a == "--hostlist"
                )
                chunk.insert(last_hl_idx + 1, auto_arg)
            new_arguments.extend(chunk)
        arguments = new_arguments

    return AdaptedPreset(arguments, firewall, warnings, len(document.profiles))


def check_preset_unsupported_options(text: str) -> list[str]:
    """Проверяет пресет на наличие непереносимых для Linux Windows/WinDivert параметров."""
    warnings: list[str] = []
    for raw in text.splitlines():
        stripped = raw.strip()
        if not stripped or stripped.startswith("#"):
            continue
        try:
            tokens = _split_option(stripped)
        except PresetError:
            continue
        for arg in tokens:
            opt, sep, val = arg.partition("=")
            opt = opt.lower()
            if opt.startswith("--wf-") and opt != "--wf-tcp-empty":
                warnings.append(f"Непереносимый Windows-параметр WinDivert: {opt}")
    return warnings


def _ports_expression(ports: Iterable[str]) -> str:
    values = list(ports)
    if not values:
        raise PresetError("Пустой список портов")
    if len(values) == 1:
        return values[0]
    return "{ " + ", ".join(values) + " }"


VOICE_MEDIA_RANGES: tuple[tuple[int, int], ...] = (
    (3478, 3480),    # STUN / TURN
    (19294, 19344),  # Discord voice
    (50000, 50100),  # Discord voice alternate / WebRTC media
)
VOICE_MEDIA_PORTS = frozenset({"19294-19344", "50000-50100", "3478-3480"})


def _parse_port_range(port_spec: str) -> tuple[int, int]:
    parts = port_spec.split("-")
    p_low = int(parts[0])
    p_high = int(parts[1]) if len(parts) > 1 else p_low
    return p_low, p_high


def is_voice_media_port(port_spec: str) -> bool:
    """Проверяет, является ли порт или диапазон строго подмножеством голосовых/STUN портов."""
    try:
        p_low, p_high = _parse_port_range(port_spec)
        return any(r_low <= p_low and p_high <= r_high for r_low, r_high in VOICE_MEDIA_RANGES)
    except (ValueError, IndexError):
        return False


def carve_range_from_voices(p_low: int, p_high: int,
                            voice_ranges: tuple[tuple[int, int], ...] = VOICE_MEDIA_RANGES) -> list[str]:
    """Вырезает голосовые диапазоны из заданного диапазона [p_low, p_high]."""
    current = [(p_low, p_high)]
    for v_low, v_high in voice_ranges:
        next_ranges = []
        for c_low, c_high in current:
            if c_high < v_low or c_low > v_high:
                next_ranges.append((c_low, c_high))
            else:
                if c_low < v_low:
                    next_ranges.append((c_low, v_low - 1))
                if c_high > v_high:
                    next_ranges.append((v_high + 1, c_high))
        current = next_ranges
    return [str(l) if l == h else f"{l}-{h}" for l, h in current]


def carve_web_ports(web_ports: Iterable[str]) -> list[str]:
    """Для любого широкого диапазона в web_ports вырезает интервалы Discord/STUN."""
    result: list[str] = []
    for p in web_ports:
        try:
            p_low, p_high = _parse_port_range(p)
        except (ValueError, IndexError):
            if p not in result:
                result.append(p)
            continue

        overlaps = any(not (p_high < v_low or p_low > v_high) for v_low, v_high in VOICE_MEDIA_RANGES)
        if overlaps:
            for carved in carve_range_from_voices(p_low, p_high):
                if carved not in result:
                    result.append(carved)
        else:
            if p not in result:
                result.append(p)
    return result


def render_nftables(spec: FirewallSpec, iface: str, qnum: int = 201,
                    table: str = "zapret_gui") -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,15}", iface):
        raise PresetError(f"Некорректный сетевой интерфейс: {iface}")
    if not re.fullmatch(r"[A-Za-z0-9_]{1,32}", table) or not 1 <= qnum <= 65535:
        raise PresetError("Некорректные параметры NFQUEUE")
    lines = [
        f"add table inet {table}",
        f"add chain inet {table} postrouting {{ type filter hook postrouting priority mangle; policy accept; }}",
    ]
    if spec.tcp_in or spec.udp_in:
        lines.append(f"add chain inet {table} prerouting {{ type filter hook prerouting priority mangle; policy accept; }}")
    # DNS must stay outside broad all-port desync profiles, otherwise DoT/UDP
    # resolution itself is modified before any hostname can be reached.
    for protocol in ("tcp", "udp"):
        lines.append(f"add rule inet {table} postrouting oifname \"{iface}\" {protocol} dport {{ 53, 853 }} accept")
        if spec.tcp_in or spec.udp_in:
            lines.append(f"add rule inet {table} prerouting iifname \"{iface}\" {protocol} sport {{ 53, 853 }} accept")
    mark = "meta mark & 0x40000000 == 0x00000000 "
    if spec.tcp_out:
        lines.append(
            f"add rule inet {table} postrouting oifname \"{iface}\" {mark}tcp dport "
            f"{_ports_expression(spec.tcp_out)} ct original packets 1-20 queue num {qnum} bypass"
        )
    if spec.udp_out:
        voice_udp = [p for p in spec.udp_out if is_voice_media_port(p)]
        raw_web_udp = [p for p in spec.udp_out if not is_voice_media_port(p)]
        web_udp = carve_web_ports(raw_web_udp)
        if voice_udp:
            lines.append(
                f"add rule inet {table} postrouting oifname \"{iface}\" {mark}udp dport "
                f"{_ports_expression(voice_udp)} queue num {qnum} bypass"
            )
        if web_udp:
            lines.append(
                f"add rule inet {table} postrouting oifname \"{iface}\" {mark}udp dport "
                f"{_ports_expression(web_udp)} ct original packets 1-12 queue num {qnum} bypass"
            )
    if spec.tcp_in:
        lines.append(
            f"add rule inet {table} prerouting iifname \"{iface}\" tcp sport "
            f"{_ports_expression(spec.tcp_in)} ct reply packets 1-10 queue num {qnum} bypass"
        )
    if spec.udp_in:
        voice_udp_in = [p for p in spec.udp_in if is_voice_media_port(p)]
        raw_web_udp_in = [p for p in spec.udp_in if not is_voice_media_port(p)]
        web_udp_in = carve_web_ports(raw_web_udp_in)
        if voice_udp_in:
            lines.append(
                f"add rule inet {table} prerouting iifname \"{iface}\" udp sport "
                f"{_ports_expression(voice_udp_in)} queue num {qnum} bypass"
            )
        if web_udp_in:
            lines.append(
                f"add rule inet {table} prerouting iifname \"{iface}\" udp sport "
                f"{_ports_expression(web_udp_in)} ct reply packets 1-3 queue num {qnum} bypass"
            )
    if spec.tcp_empty:
        lines.append(
            f"add rule inet {table} postrouting oifname \"{iface}\" {mark}"
            f"tcp flags & (syn|ack|rst) == syn queue num {qnum} bypass"
        )
    return "\n".join(lines) + "\n"


def prepare_runtime(preset_id: str, output_dir: Path, iface: str, nfqws2: Path = NFQWS2,
                    app_dir: Path = APP_DIR, dry_run: bool = True,
                    enable_auto_hostlist: bool = False) -> dict:
    if not nfqws2.is_file():
        raise PresetError(f"nfqws2 не найден: {nfqws2}. Установи пакет zapret2")
    refresh_outdated_builtin_overrides(app_dir)
    source = load_preset(preset_id, app_dir)
    # nfqws2 drops privileges and cannot traverse /home on a typical desktop.
    # Run only from a root-readable snapshot, never from the project directory.
    resource_app = output_dir / "resources"
    for relative in ("fake", "lists", "zapret2/lua"):
        source_dir = app_dir / relative
        if source_dir.is_dir():
            shutil.copytree(source_dir, resource_app / relative, dirs_exist_ok=True)
    writable_dir = output_dir / "writable"
    writable_dir.mkdir(parents=True, exist_ok=True)
    arguments_prefix = [
        "--qnum=201",
        "--bind-fix4",
        "--bind-fix6",
        "--debug=0",
        "--ctrack-timeouts=60:86400:60:3600",
    ]
    if os.geteuid() == 0:
        shutil.chown(writable_dir, "nobody", "nobody")
        writable_dir.chmod(0o755)
        if (writable_dir / "autohostlist.txt").exists():
            try:
                (writable_dir / "autohostlist.txt").chmod(0o666)
            except OSError:
                pass
        arguments_prefix.append("--user=nobody")
    adapted = adapt_preset(
        source, resource_app, resource_app / "zapret2", writable_dir,
        enable_auto_hostlist=enable_auto_hostlist,
    )
    warnings = list(adapted.warnings)
    game_warn = get_preset_warning(preset_id, source)
    if game_warn and game_warn not in warnings:
        warnings.append(game_warn)
    adapted_args = list(adapted.arguments)
    if not any(a.startswith("--ipcache-lifetime=") or a == "--ipcache-lifetime" for a in adapted_args):
        adapted_args.append("--ipcache-lifetime=86400")
    if not any(a.startswith("--ipcache-hostname=") or a == "--ipcache-hostname" for a in adapted_args):
        adapted_args.append("--ipcache-hostname=1")
    arguments = [*arguments_prefix, *adapted_args]
    nft_script = render_nftables(adapted.firewall, iface)
    if os.geteuid() == 0 and shutil.which("nft"):
        nft_check = subprocess.run(["nft", "-c", "-f", "-"], input=nft_script, text=True, capture_output=True)
        if nft_check.returncode != 0:
            raise PresetError("nftables отклонил правила:\n" + nft_check.stderr[-3000:])
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".zapret2-prepare-", dir=output_dir.parent) as temporary:
        temp_dir = Path(temporary)
        argv_path = temp_dir / "argv.json"
        argv_path.write_text(json.dumps(arguments, ensure_ascii=False, indent=2), encoding="utf-8")
        if dry_run:
            process = subprocess.run(
                [str(nfqws2), "--dry-run", *arguments], capture_output=True, text=True, timeout=30,
            )
            output = (process.stdout + process.stderr).strip()
            if process.returncode != 0:
                raise PresetError("nfqws2 отклонил пресет:\n" + output[-5000:])
        metadata = {
            "preset": Path(normalize_preset_id(preset_id)).stem,
            "source": str(preset_path(preset_id, app_dir)),
            "profiles": adapted.profile_count,
            "warnings": warnings,
            "dry_run": dry_run,
            "enable_auto_hostlist": enable_auto_hostlist,
            "nfqws2": str(nfqws2),
        }
        (temp_dir / "metadata.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        (temp_dir / "firewall.nft").write_text(nft_script, encoding="utf-8")
        (temp_dir / "preset.txt").write_text(source, encoding="utf-8")
        for filename in ("argv.json", "metadata.json", "firewall.nft", "preset.txt"):
            os.replace(temp_dir / filename, output_dir / filename)
    return metadata


def apply_firewall(runtime_dir: Path, table: str = "zapret_gui") -> None:
    script = (runtime_dir / "firewall.nft").read_text(encoding="utf-8")
    subprocess.run(["nft", "-c", "-f", "-"], input=script, text=True, check=True, capture_output=True)
    subprocess.run(["nft", "-f", "-"], input=script, text=True, check=True, capture_output=True)


def run_engine(runtime_dir: Path) -> None:
    arguments = json.loads((runtime_dir / "argv.json").read_text(encoding="utf-8"))
    if not isinstance(arguments, list) or not all(isinstance(item, str) for item in arguments):
        raise PresetError("Повреждён argv.json")
    os.execv(str(NFQWS2), [str(NFQWS2), *arguments])



def analyze_log(path: Path, max_bytes: int = 2 * 1024 * 1024) -> dict:
    if not path.is_file():
        return {"summary": "Журнал nfqws2 пока не создан", "errors": [], "profiles": {}, "tail": ""}
    with path.open("rb") as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max_bytes))
        text = stream.read().decode("utf-8", errors="replace")
    lines = text.splitlines()
    errors = [line.strip() for line in lines if re.search(
        r"\b(error|failed|failure|cannot|undefined|exception|traceback)\b", line, re.IGNORECASE,
    )]
    profiles: dict[str, int] = {}
    strategies: dict[str, int] = {}
    for line in lines:
        for match in re.finditer(r"(?:profile|instance)[=: ]+([\w .-]+)", line, re.IGNORECASE):
            name = match.group(1).strip()
            profiles[name] = profiles.get(name, 0) + 1
        for match in re.finditer(r"strategy[=: ]+(\d+)", line, re.IGNORECASE):
            name = match.group(1)
            strategies[name] = strategies.get(name, 0) + 1
    return {
        "summary": f"Строк: {len(lines)}; ошибок: {len(errors)}; профилей в событиях: {len(profiles)}",
        "errors": errors[-20:], "profiles": profiles, "strategies": strategies,
        "tail": "\n".join(lines[-200:]),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("list")
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--preset", required=True)
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--iface", required=True)
    prepare.add_argument("--nfqws2", type=Path, default=NFQWS2)
    prepare.add_argument("--no-dry-run", action="store_true")
    prepare.add_argument("--enable-auto-hostlist", action="store_true")
    run = subparsers.add_parser("run")
    run.add_argument("--runtime", type=Path, required=True)
    firewall = subparsers.add_parser("firewall")
    firewall.add_argument("--runtime", type=Path, required=True)
    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--log", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        if args.command == "list":
            print(json.dumps(discover_presets(), ensure_ascii=False, indent=2))
        elif args.command == "prepare":
            metadata = prepare_runtime(
                args.preset, args.output, args.iface, args.nfqws2,
                dry_run=not args.no_dry_run,
                enable_auto_hostlist=args.enable_auto_hostlist,
            )
            print(json.dumps(metadata, ensure_ascii=False))
        elif args.command == "run":
            run_engine(args.runtime)
        elif args.command == "firewall":
            apply_firewall(args.runtime)
        elif args.command == "analyze":
            print(json.dumps(analyze_log(args.log), ensure_ascii=False, indent=2))
        return 0
    except (PresetError, OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

