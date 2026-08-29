from __future__ import annotations

import os


def build_info() -> dict[str, str]:
    return {
        "version": os.getenv("APP_VERSION", "development").strip() or "development",
        "build": os.getenv("BUILD_SHA", "local").strip() or "local",
    }
