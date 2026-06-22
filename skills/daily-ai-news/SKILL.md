---
name: daily-ai-news
description: Use when the user wants to set up, test, configure, or troubleshoot the design-team-ai-daily push system — a GitHub-Actions-based daily Lark/Feishu push of AI news to a team group. Triggers on phrases like "/daily-ai-news setup", "早报没到", "换个飞书群", "改推送时间", "手动推一次测试", "AI日报没到", "换RSS", "换新电脑", "换公司", "重新部署".
---

# Daily AI News Skill

## 一句话说清楚

这个系统跑在 **GitHub Actions** 上，每天自动抓 RSS 日报推到飞书群。
核心配置全在 GitHub，换电脑/换群/换源都不需要动代码。

**仓库：** `<你的用户名>/design-team-ai-daily`（私有）

## 在其他 AI 工具里使用

这个 skill 文件是 Claude Code 专属格式，但底层全是 `gh` CLI 命令，任何 AI 工具都能操作。

**Codex / Trae Solo / Cursor 等工具的用法：**
把下面这段话发给它，然后说你要做什么（换群/换源/排障等），它会照着执行：

> 我有一个 AI 新闻自动推送系统，仓库是 `<你的用户名>/design-team-ai-daily`。
> 推送跑在 GitHub Actions 上，配置通过 `gh` CLI 管理：
> - 换飞书群：`gh secret set LARK_WEBHOOK_URL / LARK_WEBHOOK_SECRET / LARK_OPS_WEBHOOK_URL / LARK_OPS_WEBHOOK_SECRET`
> - 换 RSS 源：`gh variable set RSS_URL --body "新地址"`
> - 查推送状态：`gh run list --workflow=daily-ai-news.yml --limit 10`
> - 手动触发：`gh workflow run daily-ai-news.yml`
> - 暂停：`gh workflow disable daily-ai-news.yml`
> 请帮我[你的需求]。

---

## 场景导航

| 你的情况 | 跳到 |
|---|---|
| 第一次部署 | [首次部署](#首次部署) |
| 换新电脑 / 换公司 | [换新电脑](#换新电脑) |
| 换飞书群 | [换飞书群](#换飞书群) |
| 换 RSS 源 | [换RSS源](#换rss源) |
| 今天没收到推送 | [排障](#排障早报没到) |
| 手动推一次 | [手动推送](#手动推送) |
| 查推送历史 | [查状态](#查状态) |
| 暂停 / 关停 | [暂停与关停](#暂停与关停) |

---

## 首次部署

### 准备
- 有 GitHub 账号，已安装 `gh` CLI：`brew install gh && gh auth login`
- 你是目标飞书群的群管理员

### 第 1 步：克隆仓库并推到你的 GitHub

```bash
git clone https://github.com/<你的用户名>/design-team-ai-daily.git ~/design-team-ai-daily
cd ~/design-team-ai-daily
gh repo create <你的GitHub用户名>/design-team-ai-daily --private --source=. --push
```

### 第 2 步：在飞书群里建机器人

群设置 → 群机器人 → 添加机器人 → **自定义机器人** → 勾选**签名校验**  
得到：webhook URL + signature secret（保存好，只显示一次）

**不要把 secret 发到对话里**

### 第 3 步：填入 GitHub Secrets（4 个，单群模式下 OPS 填和上面相同的值）

```bash
gh secret set LARK_WEBHOOK_URL        -R <用户名>/design-team-ai-daily
gh secret set LARK_WEBHOOK_SECRET     -R <用户名>/design-team-ai-daily
gh secret set LARK_OPS_WEBHOOK_URL    -R <用户名>/design-team-ai-daily
gh secret set LARK_OPS_WEBHOOK_SECRET -R <用户名>/design-team-ai-daily
```

### 第 4 步：验证推送通路

```bash
gh workflow run daily-ai-news.yml -R <用户名>/design-team-ai-daily
gh run watch -R <用户名>/design-team-ai-daily
```

飞书群 10 秒内收到卡片 = 成功。日志出现 `[skip] juya not updated yet` = 源头今天还没发，正常。

### 第 5 步：设置 cron-job.org（让推送在发布后 15 分钟内到达）

> GitHub Actions 自带 cron 有约 1 小时排队延迟，不适合"早报"。cron-job.org 补这个缺口。

1. 建 GitHub PAT：https://github.com/settings/tokens → 名字 `cron-job-daily-news`，只勾 `workflow` 权限，有效期 1 年
2. 注册 cron-job.org（免费，不需要信用卡）
3. 新建 cronjob，**COMMON 标签**：
   - URL: `https://api.github.com/repos/<用户名>/design-team-ai-daily/actions/workflows/daily-ai-news.yml/dispatches`
   - Crontab: `*/15 8-12 * * *`，时区 `Asia/Shanghai`
4. **ADVANCED 标签**：
   - Method: `POST`
   - Headers: `Authorization: Bearer <PAT>` / `Accept: application/vnd.github+json` / `X-GitHub-Api-Version: 2022-11-28` / `Content-Type: application/json`
   - Body: `{"ref":"master"}`
5. TEST RUN → 返回 204 → CREATE

---

## 换新电脑

一条命令完成环境恢复（前提：已有 `gh` CLI 并登录）：

```bash
brew install gh 2>/dev/null; gh auth login
git clone https://github.com/<你的用户名>/design-team-ai-daily.git ~/design-team-ai-daily
mkdir -p ~/.claude/skills && ln -s ~/design-team-ai-daily/skills/daily-ai-news ~/.claude/skills/daily-ai-news
```

完成后在 Claude Code 里说"daily-ai-news 查状态"验证 skill 可用。

**换公司但想继续用这套系统**：新电脑环境恢复 + [换飞书群](#换飞书群) 即可，GitHub 仓库和推送逻辑不用动。

---

## 换飞书群

1. 在**新群**里建自定义机器人，拿 webhook URL + secret
2. 更新 Secrets：

```bash
gh secret set LARK_WEBHOOK_URL        -R <你的用户名>/design-team-ai-daily
gh secret set LARK_WEBHOOK_SECRET     -R <你的用户名>/design-team-ai-daily
gh secret set LARK_OPS_WEBHOOK_URL    -R <你的用户名>/design-team-ai-daily
gh secret set LARK_OPS_WEBHOOK_SECRET -R <你的用户名>/design-team-ai-daily
```

3. 去**旧群**飞书设置里删除旧机器人（防 webhook 泄露）
4. 手动触发一次验证：`gh workflow run daily-ai-news.yml -R <你的用户名>/design-team-ai-daily`

---

## 换 RSS 源

RSS URL 存在 GitHub Variable（不是 Secret，因为不敏感），改一条命令生效，**无需动代码**：

```bash
gh variable set RSS_URL --body "https://你的新RSS地址" -R <你的用户名>/design-team-ai-daily
```

查看当前 RSS 源：

```bash
gh variable list -R <你的用户名>/design-team-ai-daily
```

恢复默认（橘鸦 AI 早报）：

```bash
gh variable delete RSS_URL -R <你的用户名>/design-team-ai-daily
```

> 如果 `RSS_URL` 变量未设置，系统自动使用橘鸦 AI 早报作为默认源。

---

## 手动推送

强制推送今天的内容（幂等，如果今天已推过会跳过）：

```bash
gh workflow run daily-ai-news.yml -R <你的用户名>/design-team-ai-daily
gh run watch -R <你的用户名>/design-team-ai-daily
```

补推历史某天（不更新推送状态，不影响今天）：

```bash
gh workflow run daily-ai-news.yml -R <你的用户名>/design-team-ai-daily -f target_date=2026-05-01
```

---

## 查状态

```bash
# 最近 10 次推送记录
gh run list --workflow=daily-ai-news.yml --limit 10 -R <你的用户名>/design-team-ai-daily

# 当前 RSS 源
gh variable list -R <你的用户名>/design-team-ai-daily
```

日志关键词：`[ok] pushed` = 成功推出；`[skip] already pushed today` = 今天已推；`[skip] juya not updated yet` = 源头未更新。

---

## 排障：早报没到

Claude 按顺序执行：

**1. 看最近几次 run 状态**
```bash
gh run list --workflow=daily-ai-news.yml --limit 5 -R <你的用户名>/design-team-ai-daily
```
全部 `success` 但没收到 → 看日志关键词（可能是 `[skip]`）。有红叉 → 下一步。

**2. 看失败详情**
```bash
gh run view <id> --log-failed -R <你的用户名>/design-team-ai-daily
```

**3. 确认 RSS 源是否更新**
```bash
curl -s "$(gh variable list -R <你的用户名>/design-team-ai-daily --json name,value -q '.[] | select(.name=="RSS_URL") | .value' 2>/dev/null || echo 'https://imjuya.github.io/juya-ai-daily/rss.xml')" | grep -o '<pubDate>[^<]*</pubDate>' | head -3
```
最新 pubDate 不是今天 → 源头还没发，等。

**4. 手动触发**
```bash
gh workflow run daily-ai-news.yml -R <你的用户名>/design-team-ai-daily && gh run watch -R <你的用户名>/design-team-ai-daily
```

---

## 暂停与关停

| 意图 | 命令 |
|---|---|
| 临时暂停 | `gh workflow disable daily-ai-news.yml -R <你的用户名>/design-team-ai-daily` |
| 恢复 | `gh workflow enable daily-ai-news.yml -R <你的用户名>/design-team-ai-daily` |
| 下线保档 | disable + 去飞书群手动删机器人 + `gh secret delete LARK_WEBHOOK_URL` ×4 |
| 彻底删除（不可逆） | 下线保档 + `gh repo delete <你的用户名>/design-team-ai-daily --yes` |

**执行"彻底删除"前必须向用户明确确认，即使在 auto mode 下也要先问。**

---

## 安全红线

- webhook URL / secret 不进代码、commit、日志、对话明文
- PAT 只存在 cron-job.org，不截图不发给 Claude
- 未经确认不执行 `gh secret delete` 或仓库删除
- `~/.claude/skills/daily-ai-news` 保持软链，不要改成真目录
