# 一幕·YIMU V7 代码规范（CONVENTIONS）

> 适用范围：`studio/`、`gateway/`、`web/`、`cli/`、`tests/` 下全部代码与面向用户的文案。
> 许可：BSL-1.1（SPDX: `BUSL-1.1`），对外称 source-available。
> 配套门禁：`bash ci.sh`（pytest → 真活探针 → 术语检查 → 密钥扫描），提交前跑 `pre-commit run --all-files`。

---

## 0. 测试哲学（三件套，继承项目 A 工程文化）

1. **双向锁死**：`docs/CONTRACT.md` 的功能登记 ↔ `studio/main.py` 的路由实现互相锁死，
   `tests/test_contract_lock.py` 做双向 diff，任一方向缺失即 fail。
2. **数据金丝雀**：`tests/seed/` 是只读的最小种子数据，`tests/test_canary.py` 用它跑关键纯函数，
   输出必须与 `tests/seed/expected.json` 逐字一致；改算法必须同步更新期望文件。
3. **真活探针**：`python -m tests.probes`，判据 = **产物存在**（文件存在 / 时长达标），而非 HTTP 200。
   探针只写临时目录、用隔离测试库，绝不写 `runs/` 或生产账本表。

---

## 1. 文件头：SPDX-License-Identifier ⭐

- **⭐ 所有 `.py` 文件第一行必须是**：`# SPDX-License-Identifier: BUSL-1.1`
- pre-commit 钩子 `yimu-spdx-header`（`tests/check_spdx.py`）强制检查，缺失则拦截提交。

## 2. 中文注释与 docstring

- 模块 / 类 / 公开函数必须写**中文 docstring**：讲清「做什么、为什么、关键约束」，不复述代码。
- 复杂分支行内注释用中文一句话说明意图。
- 对外文案（报错信息、页面文字、API 描述）一律中文，禁止中英混杂的半成品文案上线。

## 3. 关键硬规则用 ⭐ 标记并集中注释 ⭐

- **⭐ 凡是「违反就会丢数据 / 丢钱 / 泄密」的规则，必须在代码处用 `⭐` 标记并写清后果**，例如：
  ```python
  # ⭐ 生产库守卫：命中疑似生产库路径直接抛错，测试绝不碰真库。
  assert_test_db_isolated(db_path)
  ```
- `⭐` 注释要求：是什么规则 + 违反了会怎样 + 到哪里看完整说明（指向本文档或 CONTRACT）。

## 4. 禁用营销话术注释

- 注释 / docstring / 提交信息里**禁止**营销话术，例如「颠覆式」「爆款神器」「吊打」「革命性」「最强」。
- 写清楚事实（做了什么、指标多少），让用户和测试替你夸。

## 5. 目录与命名

- 包结构：`studio/`（主服务）、`gateway/`（YIMU Gateway 独立服务）、`web/`（前端）、`cli/`（命令行）。
- 模块名小写下划线；类名大驼峰；函数 / 变量小写下划线；常量全大写。
- 面向用户的文案禁用内部黑话，完整词表与检查见 `tests/test_no_internal_jargon.py`
  （如：供应商、闸门、降级、mock、dummy、占位、主库、TODO、FIXME、lorem）。

## 6. 单文件建议 ≤ 800 行

- 单个 `.py` 文件建议不超过 800 行；超了就按职责拆模块。
- 测试文件按被测模块一对一命名：`tests/test_<模块>.py`。

## 7. 提交信息：Conventional Commits + 中文 subject ⭐

- 格式：`<type>: <中文一句话>`，例如 `feat: 网关增加按 Key 配额限速`。
- type 只用：`feat`（新功能）、`fix`（修 bug）、`docs`（文档）、`test`（测试）、`refactor`（重构）、`chore`（杂务）。
- body 可写英文技术细节，subject 必须中文。

## 8. 敏感操作：二次确认或审计日志 ⭐

- **⭐ 删数据、扣费 / 扣 credits、改会员额度、对外群发**四类操作，必须二选一：
  1. 交互式二次确认（CLI / 页面二次弹窗），或
  2. 写入审计日志（含：操作人、时间、参数、事由），审计日志不可删、只可追加。
- 网关 credits 与会员额度是**同一账本**（见 CONTRACT），扣减逻辑必须走账本唯一入口并记账。

## 9. 数据库：测试绝不碰真库 ⭐

- **⭐ 测试只能使用 `conftest` 提供的隔离库**（`YIMU_TEST_DB` 指向的临时 SQLite）。
  `assert_test_db_isolated()` 命中生产库路径标记（prod / 生产 / 主库 / `yimu.db` / `runs/` 等）直接抛错。
- 本地默认库 `data/yimu.db` 与云端 PostgreSQL 均为生产库，测试代码不得引用其路径。

## 10. 密钥：绝不硬编码 ⭐

- **⭐ 密钥只走环境变量与密钥管理服务**；`tests/test_no_secrets.py` 会扫描全仓库，
  命中密钥嫌疑（各类云厂商与平台密钥格式、各类赋值字面量写法）即 fail，
  仓库内出现 `.env` 文件即 fail；误报走 `tests/allowlist.txt` 豁免。

## 11. 本地开发流程

```bash
pip install pre-commit && pre-commit install   # 安装提交钩子
bash ci.sh                                     # 一键门禁：pytest → 探针 → 术语 → 密钥
python -m tests.probes                          # 单独跑真活探针
python -m pytest tests/test_canary.py -q        # 单独跑数据金丝雀
```
