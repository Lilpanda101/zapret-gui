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

APP_DIR = os.path.dirname(os.path.abspath(__file__))
FAKE_DIR = os.path.join(APP_DIR, "fake")
LISTS_DIR = os.path.join(APP_DIR, "lists")
LIST_GENERAL_FILE = os.path.join(APP_DIR, "list-general.txt")
BADSUM_FILE = os.path.join(APP_DIR, "badsum_hosts.txt")
EXCLUDE_FILE = os.path.join(APP_DIR, "exclude.txt")
HOSTS_FILE = os.path.join(APP_DIR, "hosts.txt")
UPDATE_META_FILE = os.path.expanduser("~/.config/zapret-gui/update_meta.json")

LOCAL_MANIFEST_CACHE = os.path.expanduser("~/.config/zapret-gui/update-manifest.json")

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

                    # Find update-manifest.json in assets
                    manifest_data = None
                    # Try all mirrors to fetch the manifest
                    manifest_mirrors = [mirror] + [m for m in MIRRORS if m != mirror]
                    for m_host in manifest_mirrors:
                        m_url = f"{m_host}/zapretdiscordyoutube/zapretgui/releases/download/{tag}/update-manifest.json"
                        try:
                            with self._open_url(m_url, timeout=TIMEOUT + 2) as m_res:
                                manifest_data = json.loads(m_res.read().decode("utf-8"))
                                if manifest_data and "files" in manifest_data:
                                    self.active_mirror = m_host
                                    break
                        except Exception:
                            continue

                    if not manifest_data and os.path.exists(LOCAL_MANIFEST_CACHE):
                        try:
                            with open(LOCAL_MANIFEST_CACHE, "r", encoding="utf-8") as f:
                                manifest_data = json.load(f)
                        except Exception:
                            pass

                    if not manifest_data or "files" not in manifest_data:
                        continue

                    # Cache valid manifest
                    try:
                        os.makedirs(os.path.dirname(LOCAL_MANIFEST_CACHE), exist_ok=True)
                        with open(LOCAL_MANIFEST_CACHE, "w", encoding="utf-8") as f:
                            json.dump(manifest_data, f)
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
            except Exception as e:
                last_err = e
                continue

        # If network failed completely, fall back to cached manifest if exists
        if os.path.exists(LOCAL_MANIFEST_CACHE):
            try:
                with open(LOCAL_MANIFEST_CACHE, "r", encoding="utf-8") as f:
                    manifest_data = json.load(f)
                return {
                    "mirror": self.active_mirror,
                    "tag_name": "cached",
                    "name": "Cached Zapret 2 Release",
                    "published_at": "",
                    "body": "Загружено из локального кэша",
                    "manifest": manifest_data
                }
            except Exception:
                pass

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

        return meta


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
