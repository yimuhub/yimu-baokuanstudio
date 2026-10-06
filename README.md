# 一幕·YIMU 爆款工作室 V7

> 一念起 一幕开 万象生
> One Thought. One Scene. Infinite Worlds.

面向自媒体创作者与短剧团队的**全链路爆款生产引擎 + 大模型 API 中转站（YIMU Gateway）**双核产品。

## 当前状态

- **版本**：`7.0.0-dev`（见 `version.py`，全项目唯一真源）
- **许可**：Business Source License 1.1（见 `LICENSE`）——源码公开、个人免费、商用需授权（可免费登记）、每版发布满 4 年自动转 Apache-2.0
- **立项文档**：`docs/合并立项建议书-V3.0.md`

## 双核

- 生产核 `studio/`：Copilot 对话入口 → 11 Agent 矩阵 → 8 步短剧流水线 → 图片质量专项 → 交付发布
- 网关核 `gateway/`：OpenAI 兼容 API 中转站；会员额度 = 网关 credits，同一账本

## 部署

- 本地：`docker compose up`（SQLite，零运维）
- 云端：PostgreSQL + Redis + 对象存储（见 `deploy/cloud/`）

## 基线

- 功能基线：项目 B @ commit `0cb424f`（功能 100% 保留，见立项书 §二）
- 工程基线：项目 A 的测试体系 / 采集 pipeline / TTS 降级链 / 内容方法论

## 开发

多 Agent 并行，契约先行、每日集成。详见立项书 §七。
