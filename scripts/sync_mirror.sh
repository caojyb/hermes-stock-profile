#!/bin/bash
# sync_mirror.sh — stock-work 镜像同步器（方案 B）
# 作用：把生产侧（profiles/stock/scripts/cron + skills/.../feishu-bitable）
#       与 git 内镜像（scripts-cron/ + skills-mirror/）对齐 + 漂移检测。
#
# 用法：
#   bash scripts/sync_mirror.sh           # 同步生产 → 镜像（并显示 git 差异）
#   bash scripts/sync_mirror.sh --check   # 只检测漂移，不改文件；有漂移 exit 1
#
# 纪律：修改代码永远在【生产侧】做（或 skill 源文件），然后跑本脚本；
#       镜像目录只由本脚本生成，禁止手改（手改会被 --check 抓出）。

set -uo pipefail

# 2026-09-22: 统一 LC_ALL=C。两侧 sort 分别走 find -printf | sort 与 ls | sort，
# 一旦 collating sequence 不一致，comm 会报 "file 1/2 is not in sorted order" 而看不出真实漂移
# （实测：同一文件集在 zh_CN.UTF-8 与 C 下的 sort 次序不同，_k2_debug_shunt.py 等位置相异）。
# 统一 C 让 comm 的输入两侧同序，比较结果只反映真实集合差异。
export LC_ALL=C

STOCK_PROFILE="$HOME/.hermes/profiles/stock"
REPO="$STOCK_PROFILE/stock-work"
CRON_SRC="$STOCK_PROFILE/scripts/cron"
SKILL_SRC="$STOCK_PROFILE/skills/stock/stock-expert/skills/feishu-bitable"
CRON_DST="$REPO/scripts-cron"
SKILL_DST="$REPO/skills-mirror/feishu-bitable"

# 镜像范围：scripts/cron 只收顶层 .py/.sh（运行时子目录 decision/、reports/、
# logs/、.pytest_cache、*.db、*.json 状态文件一律不镜像——它们是运行时产物）
CRON_EXCLUDES=(--exclude='*.[!p][!y]')  # 占位，实际用 find 过滤

CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

sync_cron() {
    local drift=0
    # 用临时清单做精确对齐：镜像侧 = 生产侧顶层 py/sh 的精确集合
    local tmp_src tmp_dst
    tmp_src=$(mktemp); tmp_dst=$(mktemp)
    # 2026-09-22: 排除运行时备份（*_pre_*.py / *.pre_* / *.bak-* / *.before-*）。
    # 它们由手工修复产生，不是生产代码，进镜像等于把版本历史备份混进 git 追踪
    # （skill 既有教训：*_pre_v2_*.py 曾造成持续假 drift 与 git 污染）。
    find "$CRON_SRC" -maxdepth 1 -type f \
        \( -name '*.py' -o -name '*.sh' \) \
        ! -name '*_pre_*' ! -name '*.pre_*' \
        ! -name '*.bak-*' ! -name '*.before-*' \
        -printf '%f\n' | sort > "$tmp_src"
    # 2026-09-19: 镜像侧清单只列 py/sh（与 src 同口径）——原 ls 全量会把 __pycache__
    # 等运行时目录算进集合差异造成假 drift（实测 scripts-cron/__pycache__ 88 个 pyc 误报）
    (cd "$CRON_DST" && ls | grep -E '\.(py|sh)$' | sort) > "$tmp_dst" 2>/dev/null

    local diff_files
    diff_files=$(comm -3 "$tmp_src" "$tmp_dst" | tr -d ' ' | sort -u)
    local content_diff
    content_diff=$(rsync -rcn --out-format='%n' \
        --exclude='*_pre_*' --exclude='*.pre_*' \
        --exclude='*.bak-*' --exclude='*.before-*' \
        --include='*.py' --include='*.sh' \
        --exclude='*' \
        "$CRON_SRC/" "$CRON_DST/" 2>/dev/null | grep -v '/$' || true)

    if [ -n "$diff_files" ] || [ -n "$content_diff" ]; then
        drift=1
        echo "⇋ scripts-cron 漂移:"
        [ -n "$diff_files" ] && echo "$diff_files" | sed 's/^/    集合差异: /'
        [ -n "$content_diff" ] && echo "$content_diff" | sed 's/^/    内容差异: /'
        if [ "$CHECK_ONLY" -eq 0 ]; then
            find "$CRON_SRC" -maxdepth 1 -type f \
                \( -name '*.py' -o -name '*.sh' \) \
                ! -name '*_pre_*' ! -name '*.pre_*' \
                ! -name '*.bak-*' ! -name '*.before-*' \
                -exec cp {} "$CRON_DST/" \;
            # 删除镜像侧多余文件：不在本次同步清单里的 .py/.sh 一律清掉。
            # 清单（tmp_src）已排除运行时备份，所以曾被误收进镜像的 *_pre_* 一并清除。
            (cd "$CRON_DST" && ls) | while read -r f; do
                case "$f" in
                    *.py|*.sh)
                        if ! grep -qxF "$f" "$tmp_src"; then
                            echo "  - 移除镜像残留: $f"
                            rm "$CRON_DST/$f"
                        fi
                        ;;
                esac
            done
            echo "  → 已同步生产 → 镜像"
        fi
    else
        echo "✓ scripts-cron IN-SYNC"
    fi
    rm -f "$tmp_src" "$tmp_dst"
    return $drift
}

# 2026-09-19: decision/ 包进镜像（前九轮治理核心: user_authority /
# validation_integrity_gate / engine / execution / 36 个回归测试）。
# 排除运行时产物: __pycache__ / *.db / snapshots / executions / outcomes /
# reports / logs / .pytest_cache / *.json 状态文件。
sync_decision() {
    local drift=0
    local src="$CRON_SRC/decision"
    local dst="$CRON_DST/decision"
    [ -d "$src" ] || { echo "✓ scripts-cron/decision 不存在（跳过）"; return 0; }
    mkdir -p "$dst"
    local content_diff
    content_diff=$(rsync -rcn --out-format='%n' \
        --include='*/' --include='*.py' \
        --exclude='__pycache__' --exclude='*.pyc' --exclude='*.db' \
        --exclude='snapshots/' --exclude='executions/' --exclude='outcomes/' \
        --exclude='reports/' --exclude='logs/' --exclude='.pytest_cache' \
        --exclude='*.json' --exclude='*' \
        "$src/" "$dst/" 2>/dev/null | grep -v '/$' || true)
    if [ -n "$content_diff" ]; then
        drift=1
        echo "⇋ scripts-cron/decision 漂移:"
        echo "$content_diff" | sed 's/^/    /'
        if [ "$CHECK_ONLY" -eq 0 ]; then
            rsync -rc --delete-excluded --prune-empty-dirs --out-format='%n' \
                --include='*/' --include='*.py' \
                --exclude='__pycache__' --exclude='*.pyc' --exclude='*.db' \
                --exclude='snapshots/' --exclude='executions/' --exclude='outcomes/' \
                --exclude='reports/' --exclude='logs/' --exclude='.pytest_cache' \
                --exclude='*.json' --exclude='*' \
                "$src/" "$dst/" >/dev/null 2>&1
            # 清理 --check 阶段预建的 __pycache__ 空壳（mkdir -p 不产生, 但 rsync 目录遍历会）
            find "$dst" -type d -name '__pycache__' -empty -delete 2>/dev/null || true
            # 删除生产侧已不存在的 py（同顶层口径）
            (cd "$dst" && find . -name '*.py') | while read -r f; do
                [ -f "$src/${f#./}" ] || rm "$dst/${f#./}"
            done
            echo "  → 已同步 decision/ → 镜像"
        fi
    else
        echo "✓ scripts-cron/decision IN-SYNC"
    fi
    return $drift
}


sync_skill() {
    local drift=0
    local content_diff
    content_diff=$(rsync -rcn --delete --out-format='%n' \
        --exclude='__pycache__' --exclude='*.bak*' --exclude='*.pyc' \
        "$SKILL_SRC/" "$SKILL_DST/" 2>/dev/null | grep -v '/$' || true)

    if [ -n "$content_diff" ]; then
        drift=1
        echo "⇋ skills-mirror 漂移:"
        echo "$content_diff" | sed 's/^/    /'
        if [ "$CHECK_ONLY" -eq 0 ]; then
            rsync -rc --delete \
                --exclude='__pycache__' --exclude='*.bak*' --exclude='*.pyc' \
                "$SKILL_SRC/" "$SKILL_DST/"
            echo "  → 已同步生产 → 镜像"
        fi
    else
        echo "✓ skills-mirror IN-SYNC"
    fi
    return $drift
}

cd "$REPO" || exit 2
drift_total=0

sync_cron   || drift_total=1
sync_decision || drift_total=1
sync_skill  || drift_total=1

if [ "$CHECK_ONLY" -eq 1 ]; then
    if [ "$drift_total" -eq 1 ]; then
        echo ""
        echo "❌ DRIFT DETECTED — 生产与镜像不一致。运行 bash scripts/sync_mirror.sh 同步后 git commit"
        exit 1
    else
        echo ""
        echo "✅ NO DRIFT — 镜像与生产一致"
        exit 0
    fi
else
    if [ "$drift_total" -eq 1 ]; then
        echo ""
        echo "已同步。待提交的变更："
        git status --short scripts-cron/ skills-mirror/
    fi
fi
