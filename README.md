# AI 每日早报推送系统

自动聚合 [橘鸦 AI 早报](https://daily.juya.uk/)、[AI HOT](https://aihot.virxact.com/) 和 [follow-builders](https://github.com/zarazhangrui/follow-builders) 三个源的 AI 资讯，解析成飞书卡片，每天定时推送到飞书群。

## 它做什么

- 每天上午 8:00-14:30，每 30 分钟检查一次三个源是否有新内容
- juya 有新日报 → 解析 RSS 里的 HTML 概览，渲染成飞书卡片推送
- aihot 有新日报 → 解析 JSON API，渲染成飞书卡片推送
- builders 有新推文 → 拉取 AI 大佬动态，Google 翻译成中文，中英双语推送
- 三个源独立去重，当天推过就不再重复
- 解析失败自动降级，11:00 后仍失败则发带链接的文本兜底
- 连续 3 次失败或 3 天没更新 → 自动告警到运维群

## 效果

飞书群每天收到 3 条卡片消息：

### 橘鸦 AI 早报

![juya card](assets/juya-card.png)

### AI HOT 日报

![aihot card](assets/aihot-card.png)

### AI 大佬动态（中英双语）

来自 follow-builders 的 AI 大佬推文，按互动量排序取 Top 10，中文由 Google Translate 自动翻译，英文原文同步展示。

## 快速部署

把下面这段话发给你的 AI 助手，它会一步步带你完成：

> 帮我部署一个 AI 每日早报推送系统。
> 仓库地址：https://github.com/<你的用户名>/ainews-to-feishu
> 我已经 Fork 了这个仓库。
> 请按照 README 里的 "部署引导" 一步步带我完成。

### 部署引导（给 AI 助手的指令）

**第 1 步：确认仓库已 Fork**
- 用户应该已经 Fork 了仓库。如果还没，先让他 Fork。

**第 2 步：创建飞书自定义机器人**
- 让用户打开飞书，进入一个群
- 群设置 → 群机器人 → 添加机器人 → 自定义机器人
- 勾选"签名校验"
- 拿到：webhook URL（类似 `https://open.feishu.cn/open-apis/bot/v2/hook/xxxxx`）和签名 secret
- **提醒用户：这两个信息不要截图发到群里**

**第 3 步：设置 GitHub Secrets**
- 打开 Fork 后的仓库 → Settings → Secrets and variables → Actions
- 点 "New repository secret"，依次添加 4 个：

| Secret 名称 | 值 |
|---|---|
| `LARK_WEBHOOK_URL` | 飞书机器人的 webhook URL |
| `LARK_WEBHOOK_SECRET` | 签名 secret |
| `LARK_OPS_WEBHOOK_URL` | 和上面同一个 URL（单群模式） |
| `LARK_OPS_WEBHOOK_SECRET` | 和上面同一个 secret（单群模式） |

**第 4 步：生成 GitHub PAT**
- 打开 https://github.com/settings/tokens
- 点 "Generate new token (classic)"
- 名字填 `cron-job-daily-news`
- 只勾选 `workflow` 权限
- 有效期建议 90 天
- 生成后复制 token（只显示一次）

**第 5 步：配置 cron-job.org**
- 打开 https://cron-job.org → 注册/登录
- 点 "Create cronjob"
- **Title**: `ai-news-daily-push`
- **URL**: `https://api.github.com/repos/<你的用户名>/ainews-to-feishu/actions/workflows/daily-ai-news.yml/dispatches`
- **Method**: `POST`
- **Headers**:
  - `Authorization: Bearer <刚才复制的 GitHub PAT>`
  - `Accept: application/vnd.github.v3+json`
  - `Content-Type: application/json`
- **Body**: `{"ref":"master","inputs":{"target_date":""}}`
- **Execution time / Timezone**: `Asia/Shanghai`
- **Schedule**: Crontab 填 `*/30 8-14 * * *`
- 点 "TEST RUN" → 返回 204 就是成功
- 点 "CREATE"

**第 6 步：验证**
- 打开仓库 → Actions → `daily-ai-news-push`
- 点 "Run workflow" → 留空 → "Run workflow"
- 等 30-60 秒，看飞书群是否收到卡片
- 如果 juya 今天还没发，日志会显示 `[skip] not updated`，这是正常的
- 如果收到卡片 → 部署成功

**第 7 步：确认明天能自动推送**
- 告诉用户：明天上午 8:00 开始，每 30 分钟会自动检查
- 如果 juya 发布了新日报，会在 30 分钟内推送到飞书群
- follow-builders 的源数据通常在 14:00 后更新，15:00 GitHub Actions 兜底时会推送

### 常见问题（部署时）

| 问题 | 原因 | 解决 |
|---|---|---|
| TEST RUN 返回 404 | URL 里的用户名或仓库名填错了 | 检查 `<你的用户名>` 和仓库名 |
| TEST RUN 返回 401/403 | PAT 权限不够或已过期 | 重新生成 PAT，只勾 `workflow` |
| Run workflow 后飞书没收到 | Secrets 填错了 | 检查 4 个 Secrets 的值 |
| 日志显示 `[skip] not updated` | juya 今天还没发 | 正常，等 juya 发布后会自动推 |
| 收到的是纯文本不是卡片 | 卡片解析失败 | 检查 juya RSS 格式是否变了 |
| 日志显示 `frequency limited` | 飞书 webhook 频率限制（1 分钟内最多 5 条） | 代码已内置 30 秒等待 + 自动重试；正常 cron 不会触发，仅手动连续推送时可能遇到 |
| GitHub 邮箱收到失败通知 | workflow 运行失败 | 去仓库 Actions 页面查看具体日志；可在 Settings → Notifications 关闭邮件通知 |

## 项目结构

```
push.py          # 主入口：先推 aihot，再推 juya，最后推 builders
rss.py           # juya RSS 抓取 + 当天条目提取
aihot.py         # aihot JSON API 拉取
builders.py      # follow-builders feed 拉取 + Google 翻译
lark.py          # 飞书 webhook 签名 + POST
lark_card.py     # juya 卡片渲染（HTML → 飞书卡片）
aihot_card.py    # aihot 卡片渲染（JSON → 飞书卡片）
builders_card.py # builders 卡片渲染（中英双语）
state.py         # 推送状态管理（去重、失败计数、停更告警）
state.json       # 运行状态（workflow 自动 commit）
tests/           # 90 个测试
.github/workflows/daily-ai-news.yml  # GitHub Actions 调度
```

## 工作流程

```mermaid
flowchart TB
    subgraph 调度["🕐 调度层"]
        C1["cron-job.org<br/>08:00-14:30 每30分钟"]
        C2["GitHub Actions<br/>15:00 兜底"]
    end

    subgraph 推送["⚙️ 推送层"]
        P["push.py<br/>主入口"]
        A["aihot.py → aihot_card.py<br/>JSON → 卡片"]
        J["rss.py → lark_card.py<br/>XML → 卡片"]
        B["builders.py → builders_card.py<br/>Feed → 中英双语卡片"]
    end

    subgraph 数据["📡 数据源"]
        A1["aihot API<br/>JSON"]
        J1["juya RSS<br/>XML"]
        B1["follow-builders<br/>GitHub JSON"]
        T["Google Translate<br/>英文→中文"]
    end

    subgraph 输出["📱 输出"]
        F["飞书群<br/>卡片消息"]
    end

    C1 -->|"POST 触发"| P
    C2 -->|"定时触发"| P
    P --> A
    P --> J
    P --> B
    A --> A1
    J --> J1
    B --> B1
    B -->|"翻译"| T
    A -->|"卡片"| F
    J -->|"卡片"| F
    B -->|"双语卡片"| F

    style C1 fill:#e1f5fe,stroke:#0288d1
    style C2 fill:#e3f2fd,stroke:#1976d2
    style P fill:#fff3e0,stroke:#f57c00
    style A fill:#e8f5e9,stroke:#388e3c
    style J fill:#e8f5e9,stroke:#388e3c
    style B fill:#f3e5f5,stroke:#7b1fa2
    style T fill:#fff9c4,stroke:#f9a825
    style F fill:#fce4ec,stroke:#c62828
```

## 容错机制

```mermaid
flowchart LR
    A["09:00 cron 触发"] --> B{"juya 已发布?"}
    B -->|"否"| S1["SKIP<br/>等下一个 cron"]
    B -->|"是"| C{"content:encoded<br/>有内容?"}
    C -->|"空"| D["降级模式<br/>运维群告警"]
    D --> E{"11:00 前?"}
    E -->|"是"| F["不标记已推送<br/>返回失败<br/>等下一个 cron 重试"]
    E -->|"否"| G["最终兜底<br/>发带链接文本到主群"]
    C -->|"有"| H["解析 HTML<br/>渲染飞书卡片"]
    H --> I["推送成功<br/>标记已推送"]

    style S1 fill:#f5f5f5,stroke:#9e9e9e
    style D fill:#fff3e0,stroke:#f57c00
    style F fill:#fff3e0,stroke:#f57c00
    style G fill:#e3f2fd,stroke:#1976d2
    style I fill:#e8f5e9,stroke:#388e3c
```

**一个上午的完整时间线**（以 juya 09:00 发布为例）：

| 时间 | 触发 | juya 状态 | 行为 |
|------|------|----------|------|
| 08:00 | cron | 未发布 | skip |
| 08:30 | cron | 未发布 | skip |
| 09:00 | cron | 已发布，content 为空 | 降级 → 告警 → 不标记 → 等重试 |
| 09:30 | cron | content 已完整 | **卡片推送成功** |
| 10:00+ | cron | 已推送 | skip |

最坏情况（juya 一直没填 content）：

| 时间 | 行为 |
|------|------|
| 09:00-10:30 | 降级 → 告警（只发1次）→ 不标记 → 等重试 |
| 11:00 | 降级 → **发文本到主群**（带链接）→ 标记已推送 |
| 11:30 | skip（已推送） |
| 15:00 | GitHub Actions 兜底 → skip |

## 本地开发

```bash
pip install -r requirements.txt
pytest -v                    # 90 个测试，应全绿

# 本地跑一次推送：
export LARK_WEBHOOK_URL="你的URL"
export LARK_WEBHOOK_SECRET="你的secret"
export LARK_OPS_WEBHOOK_URL="同上"
export LARK_OPS_WEBHOOK_SECRET="同上"
python push.py
```

## 告警机制

| 场景 | 行为 |
|---|---|
| 连续 3 次拉取失败 | 运维群告警，重置计数 |
| 连续 3 天没更新 | 运维群告警"停更" |
| 飞书 webhook 失效 | 连续 3 次失败后告警 |

## 外部依赖

| 依赖 | 用途 |
|---|---|
| `daily.juya.uk` | juya AI 早报 RSS |
| `aihot.virxact.com` | aihot 日报 JSON API |
| `follow-builders` (GitHub) | AI 大佬推文 feed |
| `translate.googleapis.com` | Google 免费翻译（英文→中文） |
| GitHub Actions | 调度 + 执行 |
| 飞书开放平台 | 推送通道 |

## License

MIT (c) 2026 Ai路人 — 详见 [LICENSE](LICENSE)

---

Made by [Ai路人](https://github.com/ainews-to-feishu)
