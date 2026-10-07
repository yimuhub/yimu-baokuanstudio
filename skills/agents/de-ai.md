---
name: de-ai
description: 中文去AI味终极规则（融合 humanizer-zh 34 patterns，写稿后必须过的最后一道工序）
---
# 去 AI 味军规

## Core Rules
` 走。

只有在以下条件同时满足时，机会性地（每次会话最多一次）向用户提一句「要不要顺便套上某位中文作者的声音？」：

- 本次会话还没询问过 voice adoption。
- 当前任务是深度改写、长篇润色、重写或风格化创作（不是公告、说明书或短句修订）。
- 用户没有在请求里明确说「保持中性」「不要改风格」之类的限制。

询问时，先读 [references/voices/index.md](references/voices/index.md) 拿到 8 位作者的一句话简介，再把列表贴给用户：李笑来、鹤老师、罗振宇、吴军、李尚龙、何帆、冯唐、刘子超。

用户拒绝或忽略：本会话剩余轮次不再追问，全部走中立路径。
用户主动指名某位作者（例如「用李笑来的口气重写」），直接跳过询问步骤，进入加载流程。

进入加载流程后：

1. 读取 [references/voices/&lt;author&gt;.md](references/voices/) 对应文件。
2. 在改写时，把该文件的人格、句法模板、节奏规则、反模式叠加在 `

## 执行要求
- 成稿完成后按以上规则自查一遍，重点：翻译腔/空泛大词/机械三分句/连环冒号/工整排比。
- 更多模式见 skills/refs/humanizer-zh/references/patterns.md（34条）；名人文风档案在 skills/refs/humanizer-zh/references/voices/。
- 改写力度：自媒体正文用深度改写；保留事实与立场，不擅自拔高。
