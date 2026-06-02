from __future__ import annotations

import re
from pathlib import Path


def normalize_key(key: str) -> str:
    return key.lstrip("﻿").strip()


def mask_identifier(value: str) -> str:
    if not value:
        return "已遮蔽"
    if len(value) <= 4:
        return "****"
    return f"{value[:3]}{'*' * max(4, len(value) - 3)}"


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
