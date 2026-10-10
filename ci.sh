#!/usr/bin/env bash
# SPDX-License-Identifier: BUSL-1.1
# 一幕·YIMU V7 一键 CI：pytest → 真活探针 → 术语检查 → 密钥扫描
# 任一步失败即停并输出中文提示；骨架期允许 skip，不允许 fail。
set -u
cd "$(dirname "$0")"

if [ -x ".venv/bin/python" ]; then
    PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
    PY=python3
else
    PY=python
fi

PASS=0

run_step() {
    local step_name="$1"
    shift
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "▶ $step_name"
    if "$PY" "$@"; then
        echo "✅ ${step_name}: 通过"
        PASS=$((PASS + 1))
    else
        echo "❌ ${step_name}: 失败，已停止后续步骤。请修复后重新运行 bash ci.sh。"
        exit 1
    fi
}

run_step "第 1 步：单元测试（pytest，含双向锁死/金丝雀）" -m pytest tests/ -q
run_step "第 2 步：真活探针（判据=产物存在）" -m tests.probes
run_step "第 3 步：术语检查（用户文案无内部黑话）" -m pytest tests/test_no_internal_jargon.py -q
run_step "第 4 步：密钥扫描（无硬编码密钥、无 .env 落盘）" -m pytest tests/test_no_secrets.py -q

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉 CI 全部通过：${PASS} 步通过，0 步失败。"
