# SPDX-License-Identifier: BUSL-1.1
"""外部化提示词工程注册中心（Prompt Engineering Registry）。"""
from .registry import PROMPT_REGISTRY, get_prompt

__all__ = ["PROMPT_REGISTRY", "get_prompt"]
