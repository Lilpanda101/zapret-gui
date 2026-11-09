#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Zapret 2 Database & Fakes Synchronizer for Linux.
Fetches official domain lists and binary fakes directly from Zapret 2 releases
on Forgejo (git2.zapret.moe, fallback to git3 / git).
"""

import os
import sys
import json
import time
import shutil
import hashlib
import subprocess
import urllib.request
import urllib.error
import ssl
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

from version import __version__

from signed_manifest import (
    MANIFEST_NAME,
    SIGNATURE_NAME,
    TRUSTED_KEYS,
    ManifestSignatureError,
    BsdiffError,
    apply_bsdiff,
    load_signed_manifest,
)

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FAKE_DIR = os.path.join(APP_DIR, "fake")
LISTS_DIR = os.path.join(APP_DIR, "lists")
LIST_GENERAL_FILE = os.path.join(APP_DIR, "list-general.txt")
BADSUM_FILE = os.path.join(APP_DIR, "badsum_hosts.txt")
EXCLUDE_FILE = os.path.join(APP_DIR, "exclude.txt")
HOSTS_FILE = os.path.join(APP_DIR, "hosts.txt")
UPDATE_META_FILE = os.path.expanduser("~/.config/zapret-gui/update_meta.json")

RESCUE_DIR = os.path.expanduser("~/.local/share/zapret-gui/rescue")
DEFAULT_PRESERVE = [
    os.path.expanduser("~/.config/zapret-gui"),
    os.path.expanduser("~/.config/zapret-gui/config.json"),
    os.path.expanduser("~/.config/zapret-gui/presets"),
    os.path.expanduser("~/.config/zapret-gui/autohostlist.txt"),
    os.path.expanduser("~/.config/zapret-gui/update_meta.json"),
    "custom_hosts.txt",
    "hosts.txt",
    "badsum_hosts.txt",
    "exclude.txt",
]
DEFAULT_KEEP_RUNNING = [
    "engine.sh",
    "zapret",
    "nfqws",
    "nfqws2",
    "tpws",
    "zapret2_core",
    "zapret-watchdog",
    "zapret-watchdog.sh",
]

LOCAL_MANIFEST_CACHE = os.path.expanduser("~/.config/zapret-gui/update-manifest.json")
# Подпись к последнему проверенному манифесту. Кэш только записывается,
# как запись о последней проверке, и никогда не читается как fallback:
# битая подпись - отказ, а не возврат к кэшу.
LOCAL_MANIFEST_SIGNATURE_CACHE = LOCAL_MANIFEST_CACHE + ".sig"

MIRRORS = [
    "https://git2.zapret.moe",
    "https://git3.zapret.moe",
    "https://git.zapret.moe"
]

TIMEOUT = 6
MIRROR_CHECK_INTERVAL = 300  # 5 minutes


class MirrorHealthMonitor:
    """Background mirror health monitoring with automatic failover."""
    def __init__(self, updater):
        self.updater = updater
        self.running = False
        self.thread = None
        self.last_results = []
        self.on_mirror_change = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread:
            self.thread.join(timeout=5)

    def _loop(self):
        while self.running:
            try:
                results = self.updater.probe_mirrors()
                self.last_results = results
                alive = [r for r in results if r["ok"]]
                if not alive:
                    if self.on_mirror_change:
                        self.on_mirror_change(None, "All mirrors are down!")
                elif self.updater.active_mirror != alive[0]["mirror"]:
                    old = self.updater.active_mirror
                    self.updater.active_mirror = alive[0]["mirror"]
                    if self.on_mirror_change:
                        self.on_mirror_change(alive[0]["mirror"], f"Mirror switched: {old} -> {alive[0]['mirror']}")
            except Exception:
                pass
            time.sleep(MIRROR_CHECK_INTERVAL)

    def get_status(self):
        return {
            "running": self.running,
            "active_mirror": self.updater.active_mirror,
            "mirrors": self.last_results
        }


class ZapretUpdater:
    def __init__(self, app_dir=APP_DIR):
        self.app_dir = app_dir
        self.fake_dir = os.path.join(app_dir, "fake")
        self.lists_dir = os.path.join(app_dir, "lists")
        self.zapret2_dir = os.path.join(app_dir, "zapret2")
        self.active_mirror = MIRRORS[0]
        self.last_check_info = None

    def _open_url(self, url, timeout=TIMEOUT):
        """Helper to fetch URL with modern headers and SSL context."""
        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) ZapretLinuxGUI/2.0",
                "Accept": "*/*"
            }
        )
        return urllib.request.urlopen(req, timeout=timeout, context=ctx)

    def probe_mirrors(self):
        """Checks availability and latency of all mirrors in parallel."""
        def probe_one(mirror):
            t0 = time.time()
            ok = False
            error = None
            try:
                url = f"{mirror}/api/v1/repos/zapretdiscordyoutube/zapretgui/releases?limit=1"
                with self._open_url(url, timeout=TIMEOUT) as res:
                    if res.status == 200:
                        ok = True
            except Exception as e:
                error = str(e)
            dt = int((time.time() - t0) * 1000)
            return {
                "mirror": mirror,
                "ok": ok,
                "latency_ms": dt,
                "error": error
            }

        results = []
        with ThreadPoolExecutor(max_workers=len(MIRRORS)) as pool:
            futures = [pool.submit(probe_one, m) for m in MIRRORS]
            for f in as_completed(futures):
                results.append(f.result())

        # Sort so fastest ok mirror is first
        results.sort(key=lambda r: (not r["ok"], r["latency_ms"]))
        for r in results:
            if r["ok"]:
                self.active_mirror = r["mirror"]
                break
        return results

    def fetch_latest_release_info(self):
        """Fetches latest release info and manifest from the fastest available mirror."""
        # Prioritize currently active mirror, followed by others
        mirrors_to_try = [self.active_mirror] + [m for m in MIRRORS if m != self.active_mirror]
        last_err = None

        for mirror in mirrors_to_try:
            try:
                url = f"{mirror}/api/v1/repos/zapretdiscordyoutube/zapretgui/releases?limit=1"
                with self._open_url(url, timeout=TIMEOUT) as res:
                    releases = json.loads(res.read().decode("utf-8"))
                    if not releases:
                        continue
                    latest = releases[0]
                    tag = latest.get("tag_name", "")

                    # Find update-manifest.json in assets. Манифест применяется
                    # только после проверки Ed25519-подписи над точными байтами.
                    # Битый манифест - отказ, а не fallback на локальный кэш.
                    manifest_data = None
                    manifest_raw = None
                    manifest_signature = None
                    # Try all mirrors to fetch the manifest
                    manifest_mirrors = [mirror] + [m for m in MIRRORS if m != mirror]
                    for m_host in manifest_mirrors:
                        m_url = f"{m_host}/zapretdiscordyoutube/zapretgui/releases/download/{tag}/{MANIFEST_NAME}"
                        s_url = f"{m_host}/zapretdiscordyoutube/zapretgui/releases/download/{tag}/{SIGNATURE_NAME}"
                        try:
                            with self._open_url(m_url, timeout=TIMEOUT + 2) as m_res:
                                raw = m_res.read()
                            with self._open_url(s_url, timeout=TIMEOUT + 2) as s_res:
                                signature = s_res.read()
                        except Exception:
                            continue
                        try:
                            manifest_data = load_signed_manifest(raw, signature, trusted=TRUSTED_KEYS)
                        except ManifestSignatureError as exc:
                            raise RuntimeError(f"Подпись update-manifest.json не сошлась: {exc}") from exc
                        manifest_raw = raw
                        manifest_signature = signature
                        self.active_mirror = m_host
                        break

                    if not manifest_data or "files" not in manifest_data:
                        continue

                    # Cache valid manifest: только проверенные байты и подпись,
                    # как запись о последней проверке. Как fallback не читается.
                    try:
                        os.makedirs(os.path.dirname(LOCAL_MANIFEST_CACHE), exist_ok=True)
                        with open(LOCAL_MANIFEST_CACHE, "wb") as f:
                            f.write(manifest_raw)
                        with open(LOCAL_MANIFEST_SIGNATURE_CACHE, "wb") as f:
                            f.write(manifest_signature)
                    except Exception:
                        pass

                    info = {
                        "mirror": self.active_mirror,
                        "tag_name": tag or "unknown",
                        "name": latest.get("name", ""),
                        "published_at": latest.get("published_at", ""),
                        "body": latest.get("body", ""),
                        "manifest": manifest_data,
                    }
                    self.last_check_info = info
                    return info
            except RuntimeError:
                raise
            except Exception as e:
                last_err = e
                continue

        # Нет fallback на кэш ~/.config/zapret-gui/update-manifest.json:
        # ни битый манифест, ни недоступность зеркал не дают права применять
        # непроверенный локальный файл.
        raise RuntimeError(f"Не удалось связаться с зеркалами Zapret 2: {last_err}")

    def decompress_zst(self, compressed_bytes):
        """Decompresses zstd bytes using CLI tool or python module."""
        try:
            proc = subprocess.run(
                ["zstd", "-d", "-c"],
                input=compressed_bytes,
                capture_output=True,
                check=True
            )
            return proc.stdout
        except Exception:
            pass

        try:
            import zstandard
            dctx = zstandard.ZstdDecompressor()
            return dctx.decompress(compressed_bytes)
        except Exception as e:
            raise RuntimeError(f"Ошибка распаковки zstd (убедитесь, что zstd установлен): {e}")

    def download_blob(self, sha256_hash, expected_size=None):
        """Downloads and decompresses a single package blob from generic store."""
        path_name = f"{sha256_hash}.zst"
        mirrors_to_try = [self.active_mirror] + [m for m in MIRRORS if m != self.active_mirror]
        last_err = None

        for mirror in mirrors_to_try:
            url = f"{mirror}/api/packages/zapretdiscordyoutube/generic/zapret-gui-store/1/{path_name}"
            try:
                with self._open_url(url, timeout=TIMEOUT + 4) as res:
                    zst_data = res.read()
                    data = self.decompress_zst(zst_data)
                    if expected_size is not None and len(data) != expected_size:
                        raise ValueError(f"Размер не совпадает: {len(data)} != {expected_size}")
                    h = hashlib.sha256(data).hexdigest()
                    if h != sha256_hash:
                        raise ValueError(f"Хэш sha256 не совпадает: {h} != {sha256_hash}")
                    return data
            except Exception as e:
                last_err = e
                continue

        raise RuntimeError(f"Не удалось скачать блоб {sha256_hash}: {last_err}")

    def sync_bases_and_fakes(self, progress_callback=None):
        """
        Downloads latest domain lists and fake binaries from Zapret 2 release,
        saves to local project directories and syncs with /etc/zapret/.
        Uses parallel workers for high-speed download.
        """
        def log(msg, percent=None):
            if progress_callback:
                progress_callback(msg, percent)
            print(f"[ZapretUpdater] {msg}")

        log("Подключение к зеркалам Zapret 2...")
        info = self.fetch_latest_release_info()
        manifest = info.get("manifest")
        if not manifest or "files" not in manifest:
            raise RuntimeError("В релизе Zapret 2 отсутствует корректный update-manifest.json")

        tag = info.get("tag_name", __version__)
        files = manifest.get("files", [])
        log(f"Найдена версия {tag} на {info['mirror']}. Всего файлов в выпуске: {len(files)}")

        fake_files = [f for f in files if f.get("path", "").startswith("bin/") and f.get("path", "").endswith(".bin")]
        list_files = [f for f in files if f.get("path", "").startswith("lists/base/") and f.get("path", "").endswith(".txt")]
        runtime_prefixes = ("lua/", "presets/winws2_builtin/", "windivert.filter/")
        runtime_files = [
            f for f in files
            if f.get("path", "").startswith(runtime_prefixes)
            and not f.get("path", "").endswith("/")
        ]

        all_tasks = (
            [(f, self.fake_dir, os.path.basename(f["path"]), "fake") for f in fake_files]
            + [(f, self.lists_dir, os.path.basename(f["path"]), "list") for f in list_files]
            + [(f, self.zapret2_dir, f["path"], "runtime") for f in runtime_files]
        )
        total_tasks = len(all_tasks)
        log(f"К синхронизации: {len(fake_files)} fakes, {len(list_files)} списков, {len(runtime_files)} файлов Zapret2.")

        os.makedirs(self.fake_dir, exist_ok=True)
        os.makedirs(self.lists_dir, exist_ok=True)
        os.makedirs(self.zapret2_dir, exist_ok=True)

        completed = 0
        updated_counts = {"fake": 0, "list": 0, "runtime": 0}
        errors = []

        def download_and_save(file_info, dest_dir, rel_name, category):
            normalized = os.path.normpath(rel_name)
            if os.path.isabs(rel_name) or normalized.startswith(".." + os.sep) or normalized == "..":
                raise ValueError(f"Небезопасный путь в манифесте: {rel_name}")
            dest = os.path.join(dest_dir, normalized)
            expected_sha = file_info.get("sha256")
            expected_size = file_info.get("size")
            if not isinstance(expected_sha, str) or len(expected_sha) != 64 or not isinstance(expected_size, int):
                raise ValueError(f"Некорректные метаданные файла: {rel_name}")

            needs_download = True
            if os.path.isfile(dest) and os.path.getsize(dest) == expected_size:
                with open(dest, "rb") as cur_f:
                    needs_download = hashlib.sha256(cur_f.read()).hexdigest() != expected_sha
            if needs_download:
                data = self.download_blob(expected_sha, expected_size)
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                temporary = dest + f".tmp-{threading.get_ident()}"
                try:
                    with open(temporary, "wb") as out_f:
                        out_f.write(data)
                        out_f.flush()
                        os.fsync(out_f.fileno())
                    os.replace(temporary, dest)
                finally:
                    if os.path.exists(temporary):
                        os.unlink(temporary)
                return True, rel_name, category
            return False, rel_name, category

        with ThreadPoolExecutor(max_workers=8) as pool:
            futures = [pool.submit(download_and_save, *task) for task in all_tasks]
            for future in as_completed(futures):
                try:
                    did_update, name, category = future.result()
                    if did_update:
                        updated_counts[category] += 1
                except Exception as exc:
                    errors.append(str(exc))
                    print(f"[ZapretUpdater] File download error: {exc}")
                completed += 1
                if total_tasks > 0 and (completed % 10 == 0 or completed == total_tasks):
                    pct = completed / total_tasks
                    log(f"Загрузка файлов: {completed}/{total_tasks} ({int(pct*100)}%)", percent=pct)

        if errors:
            raise RuntimeError("Обновление не завершено:\n" + "\n".join(errors[:15]))

        # Update root project list files
        src_general = os.path.join(self.lists_dir, "list-general.txt")
        if os.path.exists(src_general):
            shutil.copyfile(src_general, os.path.join(self.app_dir, "list-general.txt"))

        src_exclude = os.path.join(self.lists_dir, "list-exclude.txt")
        if os.path.exists(src_exclude):
            shutil.copyfile(src_exclude, os.path.join(self.app_dir, "exclude.txt"))

        log(
            f"Обновлено: {updated_counts['fake']} fakes, {updated_counts['list']} списков, "
            f"{updated_counts['runtime']} файлов Zapret2.",
            percent=1.0,
        )

        # Save metadata
        os.makedirs(os.path.dirname(UPDATE_META_FILE), exist_ok=True)
        meta = {
            "version": tag,
            "last_sync": time.strftime("%Y-%m-%d %H:%M:%S"),
            "mirror": info["mirror"],
            "fakes_count": len(fake_files),
            "lists_count": len(list_files),
            "presets_count": sum(f.get("path", "").startswith("presets/winws2_builtin/") for f in runtime_files),
            "lua_count": sum(f.get("path", "").startswith("lua/") for f in runtime_files)
        }
        with open(UPDATE_META_FILE, "w", encoding="utf-8") as mf:
            json.dump(meta, mf, indent=2, ensure_ascii=False)

        # Save installed manifest and hashes cache
        if "manifest_raw" in info and "signature_raw" in info:
            self.save_installed_manifest(info["manifest_raw"], info["signature_raw"], manifest)

        return meta

    def build_update_plan(
        self,
        target_version: str,
        from_version: str | None = None,
        preserve: list[str] | None = None,
        keep_running: list[str] | None = None,
        rescue_dir: str = RESCUE_DIR,
    ) -> dict:
        """
        Creates an update plan (plan.json) following the Zapret 2 update specification.
        Guarantees user settings preservation, keep_running daemon list, and rescue directory configuration.
        """
        work_dir = os.path.join(self.app_dir, ".update", target_version)
        tree_dir = os.path.join(work_dir, "tree")
        plan = {
            "product": "zapret-gui",
            "version": target_version,
            "from_version": from_version or __version__,
            "app_dir": self.app_dir,
            "tree_dir": tree_dir,
            "work_dir": work_dir,
            "app_pid": os.getpid(),
            "app_exe": "main.py",
            "restart_args": ["--tray"],
            "preserve": list(preserve) if preserve is not None else list(DEFAULT_PRESERVE),
            "remove": ["*.orig", "*.tmp"],
            "failure_file": os.path.join(work_dir, "failure.txt"),
            "blocker_file": os.path.join(work_dir, "blocker.txt"),
            "error_log": os.path.join(work_dir, "error.log"),
            "hold_file": "",
            "keep_running": list(keep_running) if keep_running is not None else list(DEFAULT_KEEP_RUNNING),
            "keep_files": [],
            "rescue_dir": rescue_dir,
            "extra": {},
        }
        return plan

    def download_bsdiff_patch(self, from_sha: str, to_sha: str) -> bytes:
        """Downloads a bsdiff delta patch from generic store."""
        patch_name = f"{from_sha}-{to_sha}.bsdiff"
        mirrors_to_try = [self.active_mirror] + [m for m in MIRRORS if m != self.active_mirror]
        last_err = None

        for mirror in mirrors_to_try:
            url = f"{mirror}/api/packages/zapretdiscordyoutube/generic/zapret-gui-store/1/{patch_name}"
            try:
                with self._open_url(url, timeout=TIMEOUT + 4) as res:
                    return res.read()
            except Exception as e:
                last_err = e
                continue
        raise RuntimeError(f"Не удалось скачать патч {patch_name}: {last_err}")

    def apply_file_update(
        self,
        dest_path: str,
        file_info: dict,
        bsdiff_map: dict | None = None,
        rescue_backup_dir: str | None = None,
    ) -> tuple[bool, str]:
        """
        Applies update to a single file using bsdiff delta patches when available,
        with automatic fallback to full blob download.
        Backs up previous file into rescue_backup_dir for atomic rollback.
        """
        expected_sha = file_info.get("sha256")
        expected_size = file_info.get("size")
        if not expected_sha or expected_size is None:
            raise ValueError(f"Некорректные метаданные файла: {file_info}")

        # Check if already matches
        current_data = None
        current_sha = None
        if os.path.isfile(dest_path):
            try:
                with open(dest_path, "rb") as cur_f:
                    current_data = cur_f.read()
                current_sha = hashlib.sha256(current_data).hexdigest()
                if current_sha == expected_sha and len(current_data) == expected_size:
                    return False, "up_to_date"
            except OSError:
                pass

        # Backup for rescue if backup dir specified
        if rescue_backup_dir and current_data is not None:
            rel = os.path.relpath(dest_path, self.app_dir)
            backup_target = os.path.join(rescue_backup_dir, rel)
            os.makedirs(os.path.dirname(backup_target), exist_ok=True)
            with open(backup_target, "wb") as bf:
                bf.write(current_data)

        # Attempt bsdiff delta patch
        new_data = None
        applied_delta = False
        if current_data is not None and bsdiff_map and current_sha:
            patch_info = bsdiff_map.get((current_sha, expected_sha))
            if patch_info:
                try:
                    patch_bytes = self.download_bsdiff_patch(current_sha, expected_sha)
                    patched = apply_bsdiff(current_data, patch_bytes, expected_size=expected_size)
                    if hashlib.sha256(patched).hexdigest() == expected_sha:
                        new_data = patched
                        applied_delta = True
                except Exception as exc:
                    print(f"[ZapretUpdater] Delta patch failed for {dest_path}, falling back to full download: {exc}")

        # Fallback to full blob download
        if new_data is None:
            new_data = self.download_blob(expected_sha, expected_size)

        # Atomic write with sync
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        temporary = dest_path + f".tmp-{threading.get_ident()}-{time.time()}"
        try:
            with open(temporary, "wb") as out_f:
                out_f.write(new_data)
                out_f.flush()
                os.fsync(out_f.fileno())
            os.replace(temporary, dest_path)
        finally:
            if os.path.exists(temporary):
                try:
                    os.unlink(temporary)
                except OSError:
                    pass

        return True, "bsdiff" if applied_delta else "full_blob"

    def rollback_from_rescue(self, journal_path: str, rescue_dir: str = RESCUE_DIR) -> bool:
        """
        Rolls back updated files from rescue directory using journal.json.
        Returns True if rollback completed successfully.
        """
        if not os.path.isfile(journal_path):
            return False

        try:
            with open(journal_path, "r", encoding="utf-8") as jf:
                journal = json.load(jf)
        except Exception:
            return False

        backed_up_files = journal.get("files", [])
        for rel_path in backed_up_files:
            backup_file = os.path.join(rescue_dir, rel_path)
            target_file = os.path.join(self.app_dir, rel_path)
            if os.path.isfile(backup_file):
                os.makedirs(os.path.dirname(target_file), exist_ok=True)
                shutil.copy2(backup_file, target_file)

        return True

    def save_installed_manifest(self, raw_manifest: bytes, raw_sig: bytes, manifest_dict: dict):
        """
        Saves verified installed-manifest.json and signature to system/update/
        and writes fast-lookup hashes cache to .update/hashes.json.
        """
        sys_update_dir = os.path.join(self.app_dir, "system", "update")
        os.makedirs(sys_update_dir, exist_ok=True)

        m_path = os.path.join(sys_update_dir, "installed-manifest.json")
        s_path = os.path.join(sys_update_dir, "installed-manifest.json.sig")

        # Atomic write
        for path, data in ((m_path, raw_manifest), (s_path, raw_sig)):
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)

        # Build .update/hashes.json
        dot_update_dir = os.path.join(self.app_dir, ".update")
        os.makedirs(dot_update_dir, exist_ok=True)
        hashes_path = os.path.join(dot_update_dir, "hashes.json")

        hashes_cache = {}
        for fi in manifest_dict.get("files", []):
            rel = fi.get("path")
            sha = fi.get("sha256")
            size = fi.get("size")
            if rel and sha and size is not None:
                full_p = os.path.join(self.app_dir, rel)
                try:
                    st = os.stat(full_p)
                    hashes_cache[full_p] = [size, getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)), sha]
                except OSError:
                    hashes_cache[full_p] = [size, 0, sha]

        tmp_h = hashes_path + ".tmp"
        with open(tmp_h, "w", encoding="utf-8") as hf:
            json.dump(hashes_cache, hf, indent=1)
            hf.flush()
            os.fsync(hf.fileno())
        os.replace(tmp_h, hashes_path)


def get_update_meta():
    """Reads saved update metadata if available."""
    if os.path.exists(UPDATE_META_FILE):
        try:
            with open(UPDATE_META_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {
        "version": __version__,
        "last_sync": "Не выполнялось",
        "mirror": "git2.zapret.moe",
        "fakes_count": 100,
        "lists_count": 129
    }


if __name__ == "__main__":
    updater = ZapretUpdater()
    print("Testing parallel mirror probe...")
    for m in updater.probe_mirrors():
        print("Mirror:", m)
    print("\nFetching latest release info...")
    rel = updater.fetch_latest_release_info()
    print(f"Latest release: {rel['tag_name']} from {rel['mirror']}")
