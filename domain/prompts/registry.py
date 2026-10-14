# SPDX-License-Identifier: BUSL-1.1
"""提示词模板加载与渲染注册表。"""
from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

_TEMPLATE_FILE = Path(__file__).resolve().parent / "templates.yaml"


def _load_templates() -> dict[str, Any]:
    if not _TEMPLATE_FILE.exists():
        return {}
    return yaml.safe_load(_TEMPLATE_FILE.read_text(encoding="utf-8")) or {}


PROMPT_REGISTRY: dict[str, Any] = _load_templates()


def get_prompt(category: str, key: str, default: str = "") -> str:
    blk = PROMPT_REGISTRY.get(category) or {}
    return str(blk.get(key) or default)
