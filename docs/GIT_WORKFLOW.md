# 一幕·YIMU git 开发模式共识（GIT_WORKFLOW）

> 立宪日期：2026-10-10。所有开发者（含 AI 代理）**必须**遵守。
> 配套工具：`scripts/git_safe_commit.sh`（提交前自动同步检查 + 门禁 + 规范提交）。
> 提交信息格式与代码规范见 `docs/CONVENTIONS.md` §7。

---

## 一、共识四原则（不可妥协）

1. **每一次修改都必须进 git 库**——无论多小（一个注释、一条配置、一个文案）。
   判断标准：`git status` 有未提交内容 = 违规状态，必须当天清掉。
2. **提交前必须先同步**——检查其他开发者是否提交了新内容（远端 fetch 落后检测
   + 本地 5 分钟非本机提交检测），有则先 `pull --rebase` 同步再提交，**禁止**把
   未提交的大杂烩直接 rebase。
3. **提交前门禁必须全绿**——`bash ci.sh` 4 步（pytest / 真活探针 / 术语 / 密钥扫描）
   任一失败不许提交。
4. **每一步工作必须留痕**——新功能写「新增 N」，修 bug 写「修复 N」，进
   `问题修复记录.md`（卡点 / 原因 / 解决方案 / 验证 四段式），让任何人看 git log +
   修复记录就能看懂我们每一步在做什么。

## 二、标准工作流（三步闭环）

```
① 改代码 → ② scripts/git_safe_commit.sh "<type>: 中文一句话" → ③ 问题修复记录.md 加一条
```

`git_safe_commit.sh` 内部执行（顺序固定、不可手动跳步）：

```
0  git 身份与远端检查
1  工作区状态（>200MB 待提交会警告：别误加 .venv / runs / 成片视频）
2  同步检查：git fetch → 落后 N 条 → 自动 pull --rebase；冲突即停
            + 本地最近 5 分钟非本机提交检测（多人同机协作）
3  bash ci.sh 门禁全绿
4  规范化提交（<type> 校验：feat/fix/docs/test/refactor/chore）
5  git push（配置了 remote 时）
```

### 日常命令速查

| 场景 | 命令 |
|------|------|
| 提交已暂存内容 | `scripts/git_safe_commit.sh "fix: 视频生成 503 退避重试"` |
| 自动 add + 提交 | `scripts/git_safe_commit.sh -a "feat: 视频模型能力表自动钳制"` |
| 只做同步检查不提交 | `scripts/git_safe_commit.sh --sync` |
| 查看他人刚做了什么 | `git log --since="1 hour ago" --oneline --stat` |
| 看某次改动细节 | `git show <hash>` |

## 三、提交信息规范（沿用 CONVENTIONS §7，加两条）

- 格式：`<type>: <中文一句话>`，type ∈ feat/fix/docs/test/refactor/chore。
- **正文（body）必须列改动文件数 + 门禁结果 + 修复记录条目号**（脚本自动附加模板）。
- 一次提交只干一件事；「同步 + 大杂烩」禁止。
- 版本号升级提交必须带 `V{x.y.z}` 标记（如 `fix(aivideo): … V8.2.2`），与
  `version.py` 单一真源一致。

## 四、远端仓库（多人同步的前提）

- 当前仓库**尚未配置 remote**。负责人请执行一次：
  ```bash
  git remote add origin <远端URL>        # Gitee 私有仓库（国内网络稳定）
  git push -u origin main
  ```
- 之后所有提交自动 `push`，其他开发者克隆后用 `--sync` 随时对齐。
- 分支策略：日常在 `main` 上小步提交（项目当前模式）；大版本（8.x → 9.x）
  开 `dev-x.y` 分支，合回 main 前跑全量门禁。

## 五、留痕规范（问题修复记录.md）

- 位置：项目根目录 `问题修复记录.md`（已跟踪进 git，随提交走）。
- 每条四段式：**卡点**（现象/报错）→ **原因**（根因）→ **解决方案**（改了什么）
  → **验证**（测试数 / 门禁结果 / 实测输出）。
- 编号顺延：`修复 N`（bug）、`新增 N`（功能）、`文档 N`（纯文档）；**只增不改**
  历史条目（改错了追加勘误）。
- 提交 body 里引用条目号，形成 `git log ↔ 修复记录` 双向可查。

## 六、禁区（git 层面）

- **⭐ 禁止** `git push --force` 到 main（会抹掉他人提交）；需要重写历史时
  先群内喊一嗓子。
- **⭐ 禁止** 提交 `.env` / 密钥 / 数据库 / `data/` 本地状态（`.gitignore` 已拦，
  门禁密钥扫描双保险）；唯一例外 `data/video_model_rules.json`（代码资产白名单）。
- **禁止** 绕过脚本手敲 commit 混过同步检查——`--sync` 10 秒的事，别省。

## 七、AI 代理（Hermes）执行本共识的约束

AI 改完代码后必须：跑全量测试 + `ci.sh` → 更新 `问题修复记录.md` → 调
`scripts/git_safe_commit.sh -a "<type>: …"` 完成提交闭环；提交前若检测到 5 分钟
内存在非本机提交，必须先 rebase 再提交；任何一步失败就停，不许跳过门禁强提。
