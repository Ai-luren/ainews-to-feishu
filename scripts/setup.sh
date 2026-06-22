#!/usr/bin/env bash
# 一键部署：把这个仓库的推送系统部署到你（或新公司）的 GitHub + 飞书。
#
# 用法：
#   1. 先在新群里建一个飞书自定义机器人（开签名校验），拿到 URL 和 secret
#   2. 在项目根目录跑：bash scripts/setup.sh
#   3. 照提示输入 GitHub 账户、仓库名、粘贴 webhook URL 和 secret
#
# 脚本做的事：
#   - 检查前置（gh / git / python 已安装并登录）
#   - gh repo create 建一个新的 private 仓库并首次 push
#   - gh secret set 设置 4 个密钥（单群模式下填同一对值两遍）
#   - gh workflow run 手动触发一次验证
#
# 安全：webhook/secret 通过 stdin 读取（read -rs），不走命令行参数，不进 shell history。

set -euo pipefail

# ---------- 工具函数 ----------
die() { echo "❌ $*" >&2; exit 1; }
info() { echo "👉 $*"; }
ok() { echo "✅ $*"; }

prompt() {
  # prompt VAR "描述" [默认值]
  local __var=$1 __desc=$2 __default=${3:-}
  local __val
  if [[ -n "$__default" ]]; then
    read -rp "$__desc [默认: $__default]: " __val
    __val=${__val:-$__default}
  else
    read -rp "$__desc: " __val
  fi
  printf -v "$__var" '%s' "$__val"
}

prompt_secret() {
  # prompt_secret VAR "描述"（输入不回显）
  local __var=$1 __desc=$2
  local __val
  read -rsp "$__desc: " __val
  echo
  printf -v "$__var" '%s' "$__val"
}

# ---------- 0. 目录与前置检查 ----------
cd "$(dirname "$0")/.."
ROOT=$(pwd)
info "工作目录：$ROOT"

command -v git >/dev/null || die "找不到 git，请先装。"
command -v python3 >/dev/null || die "找不到 python3，请先装（macOS 内置或装 Homebrew 的 python）。"
command -v gh >/dev/null || die "找不到 gh CLI。先装：brew install gh"
gh auth status >/dev/null 2>&1 || die "gh 未登录。先跑：gh auth login"

[[ -d .git ]] || die "当前目录不是 git 仓库。请确保你是从本仓库根目录运行此脚本。"
[[ -f push.py && -f lark_card.py ]] || die "找不到 push.py / lark_card.py。请确保你是从本仓库根目录运行。"

ok "前置检查通过：gh 已登录为 $(gh api user --jq .login)"

# ---------- 1. 收集部署参数 ----------
echo ""
info "开始收集部署参数。Webhook 和 secret 不会在屏幕回显，也不会进 shell 历史。"
echo ""

DEFAULT_USER=$(gh api user --jq .login)
prompt GH_OWNER "目标 GitHub 账户或组织（repo 将建在这个账户下）" "$DEFAULT_USER"
prompt REPO_NAME "新仓库名" "design-team-ai-daily"

echo ""
info "现在输入飞书自定义机器人的 Webhook URL 和签名 Secret。"
info "Webhook 格式：https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx 或 open.larksuite.com/..."
echo ""

prompt_secret LARK_URL "Webhook URL (不回显)"
[[ "$LARK_URL" =~ ^https?://.*open-apis/bot/v2/hook/ ]] || die "URL 格式看起来不对，应该含有 /open-apis/bot/v2/hook/。"

prompt_secret LARK_SEC "Signature Secret (不回显)"
[[ -n "$LARK_SEC" ]] || die "Signature Secret 不能为空。开启签名校验后飞书会给你一段字符串。"

echo ""
info "单群模式（推送和告警都发到这同一个群）？[Y/n]（大多数人应该选 Y）"
read -rp "" SINGLE
SINGLE=${SINGLE:-Y}

if [[ "$SINGLE" =~ ^[Nn] ]]; then
  echo ""
  info "分群模式：再输入一对 Webhook URL + Secret（运维群）。"
  prompt_secret OPS_URL "运维群 Webhook URL (不回显)"
  prompt_secret OPS_SEC "运维群 Signature Secret (不回显)"
else
  OPS_URL="$LARK_URL"
  OPS_SEC="$LARK_SEC"
fi

# ---------- 2. 建仓库并首次 push ----------
echo ""
info "在 GitHub 上创建 $GH_OWNER/$REPO_NAME (private) 并 push 当前代码…"

# 如果已经有 remote 叫 origin，先检查是否冲突
if git remote get-url origin >/dev/null 2>&1; then
  EXISTING=$(git remote get-url origin)
  info "当前已有 remote origin: $EXISTING"
  read -rp "是否要替换为新仓库 $GH_OWNER/$REPO_NAME？[y/N]: " REPLACE
  if [[ "$REPLACE" =~ ^[Yy] ]]; then
    git remote remove origin
  else
    die "用户取消。"
  fi
fi

gh repo create "$GH_OWNER/$REPO_NAME" --private --source=. --push \
  || die "gh repo create 失败。检查是否已存在同名仓库（gh repo view $GH_OWNER/$REPO_NAME）。"

ok "仓库已建立并 push：https://github.com/$GH_OWNER/$REPO_NAME"

# ---------- 3. 设 4 个 GitHub Secrets ----------
echo ""
info "设置 4 个 GitHub Secrets（单群模式下 OPS_* 与主对值相同）…"

gh_setsecret() {
  local name=$1 value=$2
  printf '%s' "$value" | gh secret set "$name" --repo "$GH_OWNER/$REPO_NAME" >/dev/null
  ok "Secret 已设置：$name"
}

gh_setsecret LARK_WEBHOOK_URL     "$LARK_URL"
gh_setsecret LARK_WEBHOOK_SECRET  "$LARK_SEC"
gh_setsecret LARK_OPS_WEBHOOK_URL    "$OPS_URL"
gh_setsecret LARK_OPS_WEBHOOK_SECRET "$OPS_SEC"

# 显式擦除变量（防手滑日志）
LARK_URL=""; LARK_SEC=""; OPS_URL=""; OPS_SEC=""

# ---------- 3.6 设置 RSS_URL Variable（可选）----------
echo ""
DEFAULT_RSS="https://daily.juya.uk/rss.xml"
info "RSS 源地址（留空使用默认：橘鸦 AI 早报）"
read -rp "RSS URL [默认: $DEFAULT_RSS]: " CUSTOM_RSS
if [[ -n "$CUSTOM_RSS" ]]; then
  gh variable set RSS_URL --body "$CUSTOM_RSS" --repo "$GH_OWNER/$REPO_NAME" >/dev/null
  ok "已设置 RSS_URL: $CUSTOM_RSS"
else
  info "跳过 RSS_URL，使用橘鸦默认源"
fi

# ---------- 3.5 预置 state.json（防首日冷启动重复推）----------
# 把 last_pushed_date 设为"昨天"，这样即使今天 juya 已发，首次 cron 也会正常推一次，
# 但不会被误识别为"从未推过任何"从而多推老日期。
YESTERDAY=$(TZ=Asia/Shanghai date -v-1d +%F 2>/dev/null || TZ=Asia/Shanghai date -d 'yesterday' +%F)
printf '{"last_pushed_date": "%s", "consecutive_failures": 0, "last_juya_entry_date": null, "juya_dead_alerted_on": null}\n' "$YESTERDAY" > state.json
if git diff --quiet state.json; then
  info "state.json 无需初始化（已是预期值）"
else
  git add state.json && git commit -q -m "chore: seed state.json with yesterday ($YESTERDAY) to avoid first-day replay" && git push -q
  ok "已预置 state.json 为 yesterday=$YESTERDAY"
fi

# ---------- 4. 等 GitHub 索引 workflow 再触发 ----------
echo ""
info "等 GitHub 索引 workflow（通常 5–30 秒，慢时可能需要 2-3 分钟）…"

for i in {1..60}; do
  if gh workflow list --repo "$GH_OWNER/$REPO_NAME" 2>/dev/null | grep -q "daily-ai-news-push"; then
    ok "Workflow 已索引"
    break
  fi
  sleep 3
  if [[ $i -eq 60 ]]; then
    die "Workflow 3 分钟内仍未被索引。这通常是 GitHub 侧的延迟（新 private repo 常见），不是你的错。
稍等 5-10 分钟后重新跑一次 scripts/setup.sh 即可；或去
https://github.com/$GH_OWNER/$REPO_NAME/actions 看下 workflow 是否出现。"
  fi
done

# ---------- 5. 触发一次验证 ----------
info "手动触发一次 workflow 验证…"
gh workflow run daily-ai-news.yml --repo "$GH_OWNER/$REPO_NAME"
sleep 5

RUN_ID=$(gh run list --workflow=daily-ai-news.yml --repo "$GH_OWNER/$REPO_NAME" --limit 1 --json databaseId --jq '.[0].databaseId')
[[ -n "$RUN_ID" ]] || die "未能获取 run id。请手动去 Actions 页面看。"

info "Run ID: $RUN_ID"
info "等待运行完成（可能 20-60 秒）…"

gh run watch "$RUN_ID" --repo "$GH_OWNER/$REPO_NAME" --exit-status >/dev/null 2>&1 \
  && ok "Workflow 运行成功" \
  || info "Workflow 结束（看下面的日志判断是否成功）"

echo ""
info "推送日志（push.py stdout）："
gh run view "$RUN_ID" --repo "$GH_OWNER/$REPO_NAME" --log 2>&1 \
  | grep -E '\[ok\]|\[skip\]|\[fail\]' || echo "  （没有匹配日志行，请直接去 Actions 页面看）"

# ---------- 完成 ----------
echo ""
ok "部署完成 🎉"
echo ""
echo "下一步："
echo "  1. 去飞书群里看看是否收到了卡片（如果 juya 今天还没更新，会是 '[skip] juya not updated yet'，那也算正常）"
echo "  2. 默认次日北京时间 09:01 开始自动推送"
echo "  3. 换群/改时间/停止推送 请参考 README.md 的 '运维' 一节"
echo "  4. 仓库地址：https://github.com/$GH_OWNER/$REPO_NAME"
