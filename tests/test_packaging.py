#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tests for packaging, desktop entries, systemd unit, and installation scripts.
Validates:
1. packaging/PKGBUILD (Arch Linux / AUR specification, variables, syntax, dependencies)
2. packaging/zapret-gui.desktop (XDG desktop entry specification, localization, categories)
3. packaging/zapret-gui.service (systemd unit structure, lifecycle actions)
4. install.sh and uninstall.sh (executable permissions, bash -n syntax, CLI flags, safe execution)
"""

import configparser
import os
import shutil
import subprocess
import tempfile
import pytest

from version import __version__

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PACKAGING_DIR = os.path.join(ROOT_DIR, "packaging")
PKGBUILD_PATH = os.path.join(PACKAGING_DIR, "PKGBUILD")
DESKTOP_PATH = os.path.join(PACKAGING_DIR, "zapret-gui.desktop")
SERVICE_PATH = os.path.join(PACKAGING_DIR, "zapret-gui.service")
INSTALL_SH = os.path.join(ROOT_DIR, "install.sh")
UNINSTALL_SH = os.path.join(ROOT_DIR, "uninstall.sh")


# ==============================================================================
# 1. PKGBUILD Tests
# ==============================================================================

class TestPkgbuild:
    def test_pkgbuild_exists(self):
        assert os.path.isfile(PKGBUILD_PATH), f"PKGBUILD not found at {PKGBUILD_PATH}"

    def test_pkgbuild_bash_syntax(self):
        proc = subprocess.run(["bash", "-n", PKGBUILD_PATH], capture_output=True, text=True)
        assert proc.returncode == 0, f"Bash syntax error in PKGBUILD: {proc.stderr}"

    def test_pkgbuild_mandatory_variables(self):
        with open(PKGBUILD_PATH, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract variables using bash evaluator
        extract_cmd = """
        source "$1"
        echo "pkgname=${pkgname}"
        echo "pkgver=${pkgver}"
        echo "pkgrel=${pkgrel}"
        echo "arch=${arch[*]}"
        echo "depends=${depends[*]}"
        """
        proc = subprocess.run(["bash", "-c", extract_cmd, "bash", PKGBUILD_PATH], capture_output=True, text=True)
        assert proc.returncode == 0, f"Failed to parse PKGBUILD: {proc.stderr}"

        parsed = {}
        for line in proc.stdout.splitlines():
            if "=" in line:
                k, v = line.split("=", 1)
                parsed[k.strip()] = v.strip()

        assert parsed.get("pkgname") == "zapret-gui", "pkgname must be 'zapret-gui'"
        assert parsed.get("pkgver") == __version__, f"pkgver ({parsed.get('pkgver')}) does not match version.py ({__version__})"
        assert parsed.get("pkgrel") is not None and int(parsed.get("pkgrel", 0)) >= 1, "pkgrel must be positive integer"

        arch_list = parsed.get("arch", "").split()
        assert "x86_64" in arch_list or "any" in arch_list, f"arch must contain x86_64 or any, got {arch_list}"

        depends_list = parsed.get("depends", "").split()
        required_deps = {"python-gobject", "gtk3", "nftables", "curl"}
        missing_deps = required_deps - set(depends_list)
        assert not missing_deps, f"PKGBUILD is missing required clean dependencies: {missing_deps}"

    def test_pkgbuild_package_function_defined(self):
        with open(PKGBUILD_PATH, "r", encoding="utf-8") as f:
            content = f.read()
        assert "package()" in content, "PKGBUILD must contain package() function"
        assert "$pkgdir/opt/zapret-gui" in content, "package() must install to /opt/zapret-gui"
        assert "zapret-gui.desktop" in content, "package() must install desktop entry"
        assert "icon.svg" in content, "package() must install icon"
        assert "moe.zapret.gui.policy" in content, "package() must install polkit policy"
        assert "zapret-gui.service" in content, "package() must install systemd service"

    @pytest.mark.skipif(shutil.which("makepkg") is None, reason="makepkg is not installed")
    def test_pkgbuild_makepkg_printsrcinfo(self):
        proc = subprocess.run(["makepkg", "--printsrcinfo"], cwd=PACKAGING_DIR, capture_output=True, text=True)
        assert proc.returncode == 0, f"makepkg --printsrcinfo failed: {proc.stderr}"
        assert "pkgname = zapret-gui" in proc.stdout
        assert f"pkgver = {__version__}" in proc.stdout
        assert "depends = python-gobject" in proc.stdout
        assert "depends = gtk3" in proc.stdout
        assert "depends = nftables" in proc.stdout
        assert "depends = curl" in proc.stdout


# ==============================================================================
# 2. zapret-gui.desktop Tests
# ==============================================================================

class TestDesktopFile:
    def test_desktop_file_exists(self):
        assert os.path.isfile(DESKTOP_PATH), f"Desktop file not found at {DESKTOP_PATH}"

    @pytest.mark.skipif(shutil.which("desktop-file-validate") is None, reason="desktop-file-validate not available")
    def test_desktop_file_validation_cli(self):
        proc = subprocess.run(["desktop-file-validate", DESKTOP_PATH], capture_output=True, text=True)
        assert proc.returncode == 0, f"desktop-file-validate error: {proc.stderr} {proc.stdout}"

    def test_desktop_file_keys_and_values(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read(DESKTOP_PATH, encoding="utf-8")

        assert "Desktop Entry" in config.sections(), "Missing [Desktop Entry] section"
        entry = config["Desktop Entry"]

        assert entry.get("Type") == "Application"
        assert entry.get("Name") == "Zapret 2 GUI"
        assert "Name[ru]" in entry
        assert entry.get("Exec") == "zapret-gui"
        assert entry.get("Icon") == "zapret-gui"
        assert entry.get("Terminal") == "false"

        categories = entry.get("Categories", "")
        assert "Network;" in categories, f"Categories must contain Network; (got {categories})"
        assert "Security;" in categories, f"Categories must contain Security; (got {categories})"

        # Localization check
        assert "Comment" in entry and len(entry.get("Comment")) > 0
        assert "Comment[ru]" in entry and len(entry.get("Comment[ru]")) > 0
        assert "GenericName" in entry and "GenericName[ru]" in entry
        assert "Keywords" in entry and "Keywords[ru]" in entry


# ==============================================================================
# 3. zapret-gui.service Tests
# ==============================================================================

class TestServiceFile:
    def test_service_file_exists(self):
        assert os.path.isfile(SERVICE_PATH), f"Service file not found at {SERVICE_PATH}"

    def test_service_file_structure(self):
        config = configparser.ConfigParser(interpolation=None)
        config.read(SERVICE_PATH, encoding="utf-8")

        for section in ["Unit", "Service", "Install"]:
            assert section in config.sections(), f"Missing [{section}] section in {SERVICE_PATH}"

        unit = config["Unit"]
        assert "Description" in unit and len(unit["Description"]) > 0
        assert "After" in unit and "network.target" in unit["After"]
        assert "nftables.service" in unit["After"]

        service = config["Service"]
        assert service.get("Type") == "oneshot"
        assert service.get("RemainAfterExit") == "yes"
        assert "engine.sh start" in service.get("ExecStart", "")
        assert "engine.sh stop" in service.get("ExecStop", "")
        assert "engine.sh restart" in service.get("ExecReload", "")

        install = config["Install"]
        assert install.get("WantedBy") == "multi-user.target"


# ==============================================================================
# 4. install.sh and uninstall.sh Tests
# ==============================================================================

class TestInstallScripts:
    def test_scripts_exist_and_executable(self):
        for script in [INSTALL_SH, UNINSTALL_SH]:
            assert os.path.isfile(script), f"Script not found: {script}"
            assert os.access(script, os.X_OK), f"Script is not executable: {script}"

    def test_scripts_shebang(self):
        for script in [INSTALL_SH, UNINSTALL_SH]:
            with open(script, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
            assert first_line in ("#!/usr/bin/env bash", "#!/bin/bash"), f"Invalid shebang in {script}: {first_line}"

    def test_scripts_bash_syntax(self):
        for script in [INSTALL_SH, UNINSTALL_SH]:
            proc = subprocess.run(["bash", "-n", script], capture_output=True, text=True)
            assert proc.returncode == 0, f"Bash syntax check failed for {script}: {proc.stderr}"

    def test_install_help_flag(self):
        proc = subprocess.run([INSTALL_SH, "--help"], capture_output=True, text=True)
        assert proc.returncode == 0
        assert "--system" in proc.stdout
        assert "--portable" in proc.stdout
        assert "--prefix" in proc.stdout

    def test_uninstall_help_flag(self):
        proc = subprocess.run([UNINSTALL_SH, "--help"], capture_output=True, text=True)
        assert proc.returncode == 0
        assert "--system" in proc.stdout
        assert "--portable" in proc.stdout
        assert "--prefix" in proc.stdout

    def test_portable_lifecycle_e2e(self):
        """Simulate portable install followed by uninstall inside a temp directory."""
        with tempfile.TemporaryDirectory() as tmp_home:
            custom_env = os.environ.copy()
            custom_env["HOME"] = tmp_home
            custom_env["XDG_DATA_HOME"] = os.path.join(tmp_home, ".local", "share")
            custom_env["XDG_CONFIG_HOME"] = os.path.join(tmp_home, ".config")

            bin_dir = os.path.join(tmp_home, ".local", "bin")
            desktop_dir = os.path.join(tmp_home, ".local", "share", "applications")
            target_launcher = os.path.join(bin_dir, "zapret-gui")
            target_desktop = os.path.join(desktop_dir, "zapret-gui.desktop")

            # 1. Run portable installation
            install_cmd = [
                INSTALL_SH,
                "--portable",
                "--bin-dir", bin_dir,
                "--skip-deps"
            ]
            res_install = subprocess.run(install_cmd, cwd=ROOT_DIR, env=custom_env, capture_output=True, text=True)
            assert res_install.returncode == 0, f"Portable install failed: {res_install.stderr}\nStdout: {res_install.stdout}"

            # Verify files were created
            assert os.path.isfile(target_launcher), f"Launcher script was not created at {target_launcher}"
            assert os.access(target_launcher, os.X_OK), "Launcher script is not executable"
            assert os.path.isfile(target_desktop), f"Desktop file was not created at {target_desktop}"

            # Verify desktop file content in portable mode
            with open(target_desktop, "r", encoding="utf-8") as f:
                d_content = f.read()
            assert f"Exec=python3 {ROOT_DIR}/main.py" in d_content
            assert f"Icon={ROOT_DIR}/icon.svg" in d_content

            # 2. Run portable uninstallation
            uninstall_cmd = [
                UNINSTALL_SH,
                "--portable",
                "--bin-dir", bin_dir
            ]
            res_uninstall = subprocess.run(uninstall_cmd, cwd=ROOT_DIR, env=custom_env, capture_output=True, text=True)
            assert res_uninstall.returncode == 0, f"Portable uninstall failed: {res_uninstall.stderr}"

            # Verify files were cleaned up
            assert not os.path.exists(target_launcher), f"Launcher still exists at {target_launcher}"
            assert not os.path.exists(target_desktop), f"Desktop shortcut still exists at {target_desktop}"

    def test_system_install_requires_root_check(self):
        """Non-root user attempting --system must fail cleanly without modifying system files."""
        if os.geteuid() != 0:
            proc = subprocess.run([INSTALL_SH, "--system", "--skip-deps"], capture_output=True, text=True)
            assert proc.returncode != 0
            assert "root" in proc.stderr.lower() or "root" in proc.stdout.lower()

    def test_safe_uninstall_guard_paths(self):
        """Verify uninstall.sh contains defensive guards against destructive root removal."""
        with open(UNINSTALL_SH, "r", encoding="utf-8") as f:
            src = f.read()
        assert '"/"' in src or '""' in src
        assert '"/usr"' in src
        assert '"/opt"' in src
        assert "rm -rf" in src
