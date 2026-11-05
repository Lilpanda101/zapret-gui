#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Single Source of Truth for Zapret 2 GUI versioning.
"""

__version__ = "21.1.7.210"
__version_info__ = (21, 1, 7, 210)

APP_NAME = "Zapret 2 GUI"
APP_TITLE = f"Zapret 2 — Обход DPI блокировок (v{__version__})"
APP_DESCRIPTION = f"Zapret 2 GUI для Arch Linux / CachyOS (v{__version__})"
APP_SUBTITLE = f"Linux Fluent v{__version__}"
BUILD_TAG = f"v{__version__}"
UPSTREAM_VERSION = __version__


def get_version() -> str:
    """Return application version string."""
    return __version__


def get_version_info() -> tuple:
    """Return version components tuple."""
    return __version_info__


def get_app_title() -> str:
    """Return window title with version."""
    return APP_TITLE


if __name__ == "__main__":
    print(f"{APP_NAME} v{__version__}")
