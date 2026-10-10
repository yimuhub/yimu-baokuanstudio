#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# ⭐ YIMU git 开发模式：提交前同步检查 + 门禁 + 规范提交（见 docs/GIT_WORKFLOW.md）
#
# 用法：
#   scripts/git_safe_commit.sh "feat: 新增 XX 功能"          # 提交已暂存/已改动内容
#   scripts/git_safe_commit.sh -a "fix: 修复 XX"             # 自动 git add -A（gitignore 生效）
#   scripts/git_safe_commit.sh --sync                         # 只做同步检查（fetch+落后检测），不提交
#
# 流程（顺序不可跳过）：
#   1) 工作区状态检查（有未跟踪大文件先提示）
#   2) git fetch + 落后检测：远端有其他开发者的新提交 → 自动 rebase 同步；冲突即停
#   3) bash ci.sh 门禁（pytest / 真活探针 / 术语 / 密钥扫描）
#   4) 规范化提交（subject 必须是 <type>: 中文一句话）
#   5) git push（配置了 remote 时）

set -euo pipefail
cd "$(dirname "$0")/.."

MODE_COMMIT=1; MODE_SYNC=0; AUTO_ADD=0; MSG=""
while [ $# -gt 0 ]; do
  case "$1" in
    -a) AUTO_ADD=1; shift ;;
    --sync) MODE_SYNC=1; shift ;;
    *) MSG="$1"; shift ;;
  esac
done

step() { printf '\n\033[1;33m━━ %s ━━\033[0m\n' "$1"; }
ok()   { printf '\033[1;32m✅\033[0m %s\n' "$1"; }
err()  { printf '\033[1;31m⛔ %s\033[0m\n' "$1" >&2; exit 1; }

# ── 0. 基本检查 ────────────────────────────────────────────────
step "0/5 git 身份与远端检查"
[ -n "$(git config user.name)" ] || err "未配置 git 用户名（git config user.name）"
BR=$(git symbolic-ref --short HEAD 2>/dev/null || echo main)
if git remote | grep -q .; then
  REMOTE=$(git remote | head -1)
  ok "远端 $REMOTE 分支 $BR"
else
  REMOTE=""
  echo "⚠️  未配置 remote——本次只在本地提交。多人协作前请执行："
  echo "    git remote add origin <远端仓库URL> && git push -u origin $BR"
  echo "    （远端仓库地址找项目负责人获取；配置好后本脚本自动带 push）"
fi

# ── 1. 工作区状态 ──────────────────────────────────────────────
step "1/5 工作区状态"
CHANGED=$(git status --porcelain)
if [ -z "$CHANGED" ]; then
  [ $MODE_SYNC -eq 1 ] && { ok "工作区干净"; exit 0; }
  err "没有待提交的改动（git status 为空）"
fi
git status --short | head -30 || true
# 待提交内容体积粗查（>200MB 告警；中文文件名需 -c core.quotepath=false 才不被转义）
BIG=$(git -c core.quotepath=false status --porcelain -u | awk '{print $2}' \
      | xargs -I{} du -sm "{}" 2>/dev/null | awk '{s+=$1} END{print s+0}' || true)
if [ "${BIG:-0}" -gt 200 ]; then
  echo "⚠️  待提交内容合计 ${BIG}MB（>200MB），先检查是否误加 .venv / runs / 成片视频"
fi

# ── 2. 同步检查：拉取其他开发者的新提交 ───────────────────────
step "2/5 同步检查（其他开发者是否提交了新内容）"
if [ -n "$REMOTE" ]; then
  git fetch "$REMOTE" "$BR" 2>/dev/null || err "fetch 失败——网络或远端不可达，先解决再提交"
  AHEAD=$(git rev-list --count "$REMOTE/$BR"..HEAD 2>/dev/null || echo 0)
  BEHIND=$(git rev-list --count HEAD.."$REMOTE/$BR" 2>/dev/null || echo 0)
  echo "远端 $REMOTE/$BR：本地领先 $AHEAD 条，落后 $BEHIND 条"
  if [ "$BEHIND" -gt 0 ]; then
    if [ $MODE_COMMIT -eq 1 ] && [ -n "$(git status --porcelain)" ]; then
      err "远端有 $BEHIND 条新提交且本地有未提交改动——请先小步提交，或先 git stash。禁止把未提交的大杂烩直接 rebase。"
    fi
    echo "→ 正在 rebase 同步其他开发者的提交…"
    git pull --rebase "$REMOTE" "$BR" || err "rebase 出现冲突：请解决冲突（git status 查看）后 git rebase --continue，再重跑本脚本。"
    ok "已同步远端 $BEHIND 条提交（同步后必须重跑门禁）"
  else
    ok "与远端一致，无其他开发者新提交"
  fi
else
  echo "ℹ️  无远端，跳过同步检查（本地仓库）"
fi

# 本地多开发者/多进程并发改同一份代码时（当前项目实际情况）：
# 即使无 remote，也检查最近 5 分钟是否有他人提交
OTHERS=$(git log --since="5 minutes ago" --oneline --author="!$(git config user.email)" | wc -l | tr -d ' ')
if [ "${OTHERS:-0}" -gt 0 ]; then
  echo "⚠️  最近 5 分钟内有 $OTHERS 条非本机提交：$(git log --since='5 minutes ago' --oneline --author="!$(git config user.email)" | head -5)"
fi

# ── 3. 门禁 ────────────────────────────────────────────────────
step "3/5 发布门禁（ci.sh：pytest / 真活探针 / 术语 / 密钥扫描）"
if [ $AUTO_ADD -eq 1 ] && [ $MODE_COMMIT -eq 1 ]; then
  git add -A
  git status --short | grep '^[AM]' | head -30
fi
bash ci.sh || err "门禁未过——先修到全绿再提交（提交信息里不许写「跳过门禁」）"

if [ $MODE_SYNC -eq 1 ]; then
  ok "同步检查完成（--sync 模式，不提交）"; exit 0
fi

# ── 4. 规范化提交 ──────────────────────────────────────────────
step "4/5 提交"
[ -n "$MSG" ] || err "缺少提交信息：scripts/git_safe_commit.sh \"<type>: 中文一句话\""
case "$MSG" in
  feat:*|fix:*|docs:*|test:*|refactor:*|chore:*) : ;;
  *) err "提交信息必须 <type>: 开头（feat/fix/docs/test/refactor/chore），例如 \"feat: 视频模型能力表自动钳制\"";;
esac
BODY="$(git status --short | grep -c '^[AMDR]' || true)"
FULL="$MSG

- 改动文件：$BODY 个；门禁 ci.sh 4/4 通过
- 记录：问题修复记录.md 已同步更新（新功能写「修复 N」，功能类写「新增 N」）"
git commit -m "$FULL" || err "commit 失败（可能被 pre-commit 钩子拦截，看上方输出修完再来）"
LAST=$(git log -1 --oneline)
ok "已提交：$LAST"

# ── 5. 推送 ───────────────────────────────────────────────────
step "5/5 推送"
if [ -n "$REMOTE" ]; then
  git push "$REMOTE" "$BR" || err "push 失败——网络问题或需要 rebase 远端新提交，重跑本脚本"
  ok "已推送到 $REMOTE/$BR，其他开发者下次 --sync 即可看到"
else
  echo "ℹ️  无远端，跳过推送（本地提交完成）"
fi
echo
ok "完成。记住三步闭环：改完 → 本脚本提交 → 问题修复记录.md 留痕"
