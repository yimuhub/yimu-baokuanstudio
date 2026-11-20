# SPDX-License-Identifier: BUSL-1.1
"""PromptForge：热榜选题 → 生图提示词组装（金丝雀锁死契约）。

⭐ 硬规则：
- assemble_prompt 是金丝雀锁死算法：输出必须与 tests/seed/expected.json 逐字一致，
  任何格式改动（标点、换行、拼接符号）都会导致 CI 金丝雀测试失败。改算法必须同步
  更新 expected.json 与 docs/CONTRACT.md §6，并经评审批准。

v15.9.9 变更：移除 forge_prompt 与 12 风格库依赖。
why：forge_prompt 唯一服务于孤儿链 /api/image/*（studio/image_forge，前端零调用，
随 R1 整改整目录下线）；其风格解析依赖的 studio.image_forge.styles 也随目录删除。
在用的生图风格真源是 core/imagegen（主链），本模块只保留金丝雀契约 assemble_prompt，
避免把孤儿风格数据搬进在用链形成新的重复。
"""

from __future__ import annotations

# 方头括号：U+3010 为开括号、U+3011 为合括号（源码用 chr 构造，
# 避免字面量在写入链路中被误处理；运行时即为期望的方头括号字符）
_BRACKET_OPEN = chr(0x3010)
_BRACKET_CLOSE = chr(0x3011)


def assemble_prompt(hotspot: dict, style: str) -> str:
    """⭐ 金丝雀算法（锁死，逐字精确）：热点 → 三行生图提示词。

    hotspot 字段：id / title / keywords(list[str]) / angle / heat / platform。
    算法：先用顿号拼接 keywords，再按模板组装三行文本
    （模板：方头括号包裹风格名后接标题 / 关键词：… / 切入角度：…，
    行间用换行分隔）。
    """
    keywords = "、".join(hotspot["keywords"])
    head = _BRACKET_OPEN + style + _BRACKET_CLOSE + hotspot["title"]
    return head + "\n关键词：" + keywords + "\n切入角度：" + hotspot["angle"]
