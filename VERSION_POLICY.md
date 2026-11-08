# 版本号管理规范（Version Policy）

> **生效版本**：v15.0.0「太平令 · Great Peace Edict」（2026-11-08）
> **适用范围**：本仓库所有开发者、所有 Agent、所有工作区（含 WorkBuddy worktree）
> **强制性**：本规范为发布门禁的一部分；违反规范的版本号将在 CI 版本真源检查中红灯。

---

## 一、背景：为什么要有本规范

2026-11-08 排查发现一次严重的**版本线分叉事故**（根因与教训，所有人必读）：

1. 仓库存在多个工作区（本目录 + WorkBuddy worktree 等），其中一条发布线在
   GitHub 远端从 v10.3.0 一路发布到 **v14.0.0**（24 个提交），而另一条工作区
   停留在 v10.2.1，**长期未执行 `git pull`**。
2. 落后工作区不知道远端已消耗 v11~v14 与对应代号（长风谣/沧海吟/山岳赋/
   江河曲/竹韵篇/梅雪镜/兰心曲），按本地过期的 `release-codenames.json`
   发出了 **v11.0.0「长风谣」——与远端 v11.0.0 撞号撞名**（幸未推送）。
3. 同一日，远端 v14 的运行实例与本机 v10.2.1 代码实例并存，用户看到的
   版本号互相矛盾。

**结论：版本号混乱的根源不是规则缺失，而是「多工作区 + 拉取不勤 + 版本真源
各说各话」。本规范与配套检查即为根治此问题而立。**

## 二、版本线对齐决议（用户裁定）

**主版本锁定 V15**（本行由 CI 门禁解析，勿改格式）

| 决议 | 内容 |
|---|---|
| **对齐基线** | 全线统一升级到 **V15**（跳过远端已占用的 v11~v14 段，避免撞号） |
| **当前版本** | `15.0.0` · 代号「太平令 · Great Peace Edict」 |
| **默认迭代** | **一切日常开发只在 V15 内做小版本递增**：bug 修复 `15.x.Z+1`，新功能 `15.Y+1 且 Z 归零` |
| **主版本跳升** | **仅限开发者强烈要求时**：必须在任务/issue 中书面说明理由（如不可兼容的存储格式变更、品牌重命名等），经确认后修改本规范方可升为 V16；口头/顺手的 major 跳升一律禁止 |

## 三、日常发布流程（所有人照此执行）

1. **动手前先对齐**：任何版本相关改动之前，先
   ```bash
   git fetch origin --tags && git pull --rebase origin main
   ```
   确认本地 `version.py` 与远端最新 release 不冲突。**落后工作区禁止发版。**
2. **推导版本号**：按 `VERSION_RULES.md` 第二章在 **15.x.y** 内递增
   （纯修 bug → Z+1；新增功能 1~5 个 → Y+1 且 Z 归零）。
3. **分配代号**：版本号大于 `release-codenames.json` 的 `current_version`
   才取 `sequence[next_index]` 下一号，不得跳过、回退、复用。
4. **单一真源同步**：一次发布必须同步以下全部位置（CI 会互检）：
   - `version.py`（唯一手写点）
   - `pyproject.toml` 的 `version`
   - `web/static/locales/zh-CN.json` 与 `en-US.json` 的 `version`
   - `installer/windows/yimu_installer.iss` 的 `MyAppVersion`
   - `README.md` / `README_ZH.md` 徽章
   - `RELEASES.md` / `CHANGELOG.md` 新条目
   - `docs/CONTRACT.md`（有新路由时）
5. **提交信息**：`release(v15.x.y): 一句话说明`；远端打 tag `v15.x.y`。

## 四、多工作区纪律（新增，必读）

- **同一时刻只有一个工作区拥有发布权**：发布前在 `git fetch` 后确认
  `origin/main` 上没有比本地 `version.py` 更新的版本线。
- WorkBuddy worktree 等并行工作区**只做开发、不发版**：改动一律合回主
  工作区统一发版，禁止在 worktree 里改 `version.py` / 打 tag。
- 每次会话开始开发前先 `git pull`；会话结束前把已完成的改动 commit
  （允许不 push，但必须 commit，避免下次会话基于漂移状态开工）。

## 五、配套检查（自动门禁）

- `tests/test_v1002_dynamic_versions.py`：版本四源互检（version.py ↔ pyproject ↔ locales）；
- `tests/test_contract_lock.py`：路由契约锁死（CONTRACT.md ↔ app 双向）；
- `tests/test_no_secrets.py` + `ci.sh` 第 4 步：密钥扫描（版本发布流程中
  **严禁**把含 token 的 remote URL、.env 写入仓库文件）；
- 升版后必须全绿 `bash ci.sh` 才允许提交 `release(...)` 提交。

## 六、本规范修订权

本规范由仓库所有者修订。任何「跳过 V15 段位」「重用历史版本号/代号」的
PR 一律拒绝；确需主版本跳升时，先修订本文件第二节，再执行升版。
