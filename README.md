# AI 每日早报 → 飞书

每天从 `https://daily.juya.uk/rss.xml` 抓取最新一期 AI 早报，
解析为飞书卡片，推送到指定群组。

**调度**：GitHub Actions cron，北京时间 09:00 / 09:30 / 10:00 / 10:30 各跑一次。
**去重**：当天推送成功后，后续 cron 自动跳过，飞书群每天最多收到 1 条。

---

## 快速一览

| 项 | 值 |
|---|---|
| 信息源 | `https://daily.juya.uk/rss.xml` |
| 推送目标 | Feishu 自定义机器人 |
| 调度方式 | GitHub Actions `schedule`（UTC `0,30 1,2 * * *`）|
| 语言 | Python 3.11 |
| 测试 | `pytest`，72 个测试，预期全绿 |
| 状态文件 | `state.json`（记录 `last_pushed_date` / `consecutive_failures` / `last_juya_entry_date`）|

---

## 项目结构

```
.
├── push.py              # 主流程：去重 → 拉取 → 解析 → 推送 → 写 state
├── rss.py               # RSS 抓取 + 解析 + 当天条目提取
├── lark.py              # Feishu webhook：签名 + POST
├── lark_card.py         # 把 RSS 内容渲染为飞书卡片
├── state.py             # state.json 原子读写（原子写入，不会半截损坏）
├── state.json           # 运行状态（由 workflow 自动提交回仓库）
├── requirements.txt     # 依赖：feedparser, requests, beautifulsoup4, pytz
├── pytest.ini
├── .github/workflows/
│   └── daily-ai-news.yml  # cron + workflow_dispatch
└── tests/               # 单元测试
```

---

## 它是怎么工作的

```
   GitHub Actions 触发
   (cron 或手动 dispatch)
            ↓
       python push.py
            ↓
   1. 检查 state.json → 今天推过？ → 是 → [skip] 退出
   2. 拉取 RSS (https://daily.juya.uk/rss.xml)
   3. 找到"今天日期"的条目 → 没有？ → [skip] 等下一个 cron
   4. 解析 HTML → 生成飞书卡片
   5. POST 到飞书 webhook
   6. 成功 → state.json 记录今天为 last_pushed_date
      失败 → consecutive_failures +1，连续 3 次失败发告警
```

**失败告警**：
- 连续 3 次拉取/推送失败 → 推一条告警到同一个飞书群
- juya 连续 3 天没更新 → 推一条"停更告警"到同一个飞书群

---

## 部署（只做一次）

### 需要的 Secrets（GitHub → Settings → Secrets and variables → Actions）

| Secret 名称 | 值 |
|---|---|
| `LARK_WEBHOOK_URL` | 飞书自定义机器人的 webhook URL |
| `LARK_WEBHOOK_SECRET` | 飞书机器人的签名密钥（勾选"签名校验"后生成）|
| `LARK_OPS_WEBHOOK_URL` | **和上面同一个 URL**（运维告警发到同一个群）|
| `LARK_OPS_WEBHOOK_SECRET` | **和上面同一个 secret** |

> 如果你想把"早报"和"告警"分到两个群，就填不同的值。不用改代码。

### 测试是否正常

在 GitHub 仓库 → Actions → 选择 `daily-ai-news-push` → 点「Run workflow」→ 留空 = 推送今天。

等待完成后检查飞书群是否收到卡片。

---

## 日常运维（常见问题）

### 1. 今天没收到早报？

去 `Actions` 页面看最新的 run 日志，搜关键词：

| 日志关键词 | 含义 | 怎么办 |
|---|---|---|
| `[skip] already pushed today` | 今天已推送成功 | 等明天 |
| `[skip] juya not updated` | juya 还没发布今天的 | 等下一个 cron（每 30 分钟重试一次）|
| `[fail] push attempt failed (2/3)` | 推送失败，正在重试 | 看看飞书机器人是否还活着，或者等下一个 cron |
| `[ok] pushed` | 推送成功，但群里没看到 | 检查机器人是否被禁用 / 群是否被解散 |

### 2. 想改推送时间

编辑 `.github/workflows/daily-ai-news.yml` 里的 `cron`。

**规则**：cron 写的是 **UTC 时间**，不是北京时间。北京时间 = UTC + 8 小时。

当前配置 `'0,30 1,2 * * *'` 代表：
- UTC 01:00 → 北京 09:00
- UTC 01:30 → 北京 09:30
- UTC 02:00 → 北京 10:00
- UTC 02:30 → 北京 10:30

改完 `git push` 即可，立即生效。

### 3. 想补发某一天

GitHub → Actions → `daily-ai-news-push` → 「Run workflow」→ 在输入框填日期 `YYYY-MM-DD`（例如 `2026-06-13`），留空 = 今天。

或者命令行：
```bash
gh workflow run daily-ai-news.yml -f target_date=2026-06-13
```

### 4. 想停掉 / 暂停

GitHub → Actions → 选中 `daily-ai-news-push` → 右上 `···` → `Disable workflow`。
随时可以再 Enable 回来。

### 5. juya 的 RSS URL 改了怎么办

编辑 `rss.py` 里的 `_RSS_URL_DEFAULT`，把新 URL 填进去，`git push` 即可。
代码本身也有兜底：如果以后旧的 `imjuya.github.io` 地址被配置，会自动回退到默认值。

---

## 本地开发

```bash
pip install -r requirements.txt
pytest -v           # 跑测试（72 个，应全绿）

# 想本地跑一次推送：
export LARK_WEBHOOK_URL="你的 URL"
export LARK_WEBHOOK_SECRET="你的 secret"
export LARK_OPS_WEBHOOK_URL="同上"
export LARK_OPS_WEBHOOK_SECRET="同上"
python push.py
```

---

## 外部依赖（都不可控，挂了会自动告警）

| 依赖 | 用途 | 风险 |
|---|---|---|
| `daily.juya.uk` | 信息源 RSS | 停更 → 3 天后告警；改 URL → 手动更新 `rss.py` 中 `_RSS_URL_DEFAULT` |
| GitHub Actions | 调度 + 执行 | 免费额度够用；历史上极少宕机 |
| Feishu / Lark 开放平台 | 推送通道 | webhook URL 失效 / 机器人被删 → 连续 3 次失败后告警 |

---

## 对 AI 的一句话说明（给 LLM 看的）

> 这是一个最小化的"RSS → 飞书"推送器。入口是 `.github/workflows/daily-ai-news.yml` 的 `schedule`，执行 `push.py`。`push.py` 依赖 `rss.py`（拉取解析）、`lark_card.py`（渲染卡片）、`lark.py`（POST 飞书）、`state.py`（状态原子读写）。状态存在仓库根的 `state.json`，每次运行后由 workflow 自动 commit 回去。测试用 `pytest`，覆盖所有核心函数。复刻时只需要：1) 复制文件结构 2) 设 4 个飞书 secrets 3) 确认 cron 时区正确。没有其他数据库、缓存、外部服务。
