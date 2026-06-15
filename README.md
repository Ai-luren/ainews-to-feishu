# AI 每日早报 → 飞书（juya + aihot 双源）

每天从两个来源抓取 AI 资讯，各自独立解析为飞书卡片，推送到同一个群组。

| 源 | 说明 | 位置 |
|---|---|---|
| juya | `https://daily.juya.uk/rss.xml`，解析 HTML 内容 | rss.py + lark_card.py |
| aihot | `https://aihot.virxact.com/api/public/daily`，原生 JSON | aihot.py + aihot_card.py |

**调度**：GitHub Actions cron，北京时间 09:00 / 09:30 / 10:00 / 10:30。
**去重**：每个源独立记录 pushed_date，当天任一源推送成功后，该源后续 cron 自动跳过。飞书群每天最多收到 2 条卡片。

---

## 快速一览

| 项 | 值 |
|---|---|
| 信息源 | juya RSS + aihot JSON API（两个独立流程）|
| 推送目标 | Feishu 自定义机器人（两个源推到同一个群）|
| 调度方式 | GitHub Actions `schedule`（UTC `0,30 1,2 * * *` = 北京 09:00–10:30，每 30 分钟）|
| 语言 | Python 3.11 |
| 测试 | `pytest`，72 个测试，预期全绿 |
| 状态文件 | `state.json`（按源独立记录推送日期、失败计数、最新条目日期）|

---

## 项目结构

```
.
├── push.py              # 主入口：依次调 _push_juya() + _push_aihot()，各独立去重/告警
├── rss.py               # juya：RSS 抓取 + 当天条目提取
├── aihot.py             # aihot：JSON API 拉取 + 内容判空
├── lark.py              # Feishu webhook：签名 + POST（两个源共用）
├── lark_card.py         # juya 卡片渲染
├── aihot_card.py        # aihot 卡片渲染
├── state.py             # state.json 原子读写；按源拆分字段，互不污染
├── state.json           # 运行状态（由 workflow 自动 commit 回仓库）
├── requirements.txt     # feedparser, requests, beautifulsoup4, pytz
├── pytest.ini
├── .github/workflows/
│   └── daily-ai-news.yml  # cron + workflow_dispatch
└── tests/               # 单元测试（juya 流程覆盖）
```

---

## 它是怎么工作的

```
   GitHub Actions 触发
   (cron 每 30 分钟一次 / 或手动 dispatch)
            ↓
       python push.py
            ↓
   ┌────────┴────────┐
   ↓                 ↓
 [_push_juya]     [_push_aihot]
   1. 读 state.json    1. 读 state.json
      今天 juya 推过？ 今天 aihot 推过？
      → 是 → skip      → 是 → skip
   2. 拉 RSS           2. GET /api/public/daily
   3. 找今天条目       3. 取 sections[]
      无 → skip           空 → skip
   4. HTML→卡片         4. JSON→卡片
   5. POST 飞书         5. POST 飞书
   6. 成功 → 写状态    6. 成功 → 写状态
      失败 → 计数+1       失败 → 计数+1
      连续 3 次 → 告警    连续 3 次 → 告警

  * 两个流程完全独立，一个失败不影响另一个。
  * backfill（补发指定日期）不写状态，可重复跑。
```

**失败告警（到同一个飞书群）**：
- 任一源连续 3 次拉取/推送失败 → 发一条告警
- 任一源连续 3 天没更新 → 发一条"停更告警"

---

## 部署（只做一次）

### 需要的 Secrets（GitHub → Settings → Secrets and variables → Actions）

| Secret 名称 | 值 |
|---|---|
| `LARK_WEBHOOK_URL` | 飞书自定义机器人的 webhook URL |
| `LARK_WEBHOOK_SECRET` | 飞书机器人的签名密钥（勾选"签名校验"后生成）|
| `LARK_OPS_WEBHOOK_URL` | **和上面同一个 URL**（运维告警发到同一个群）|
| `LARK_OPS_WEBHOOK_SECRET` | **和上面同一个 secret** |

> 想把"早报"和"告警"分到两个群？改上面 4 个值即可，代码不改。

### 测试是否正常

GitHub → Actions → 选择 `daily-ai-news-push` → 点「Run workflow」→ 留空 = 推送今天。

---

## 日常运维（常见问题）

### 1. 今天没收到？

去 `Actions` 页面看最新的 run 日志，搜关键词：

| 日志关键词 | 含义 | 怎么办 |
|---|---|---|
| `[juya] [skip] already pushed today` | juya 今天已推过 | 等明天 |
| `[aihot] [skip] already pushed today` | aihot 今天已推过 | 等明天 |
| `[juya] [skip] juya not updated` | juya 还没发今天的 | 等下一个 cron |
| `[aihot] [skip] aihot no content` | aihot 今天没内容 | 等明天 |
| `[fail] push attempt failed (N/3)` | 推送失败，重试中 | 检查飞书机器人是否活着 |
| `[ok] pushed` | 已推送，看飞书群 | 正常 |

### 2. 想改推送时间

编辑 `.github/workflows/daily-ai-news.yml` 里的 `cron`。

**规则**：cron 写 **UTC 时间**，北京时间 = UTC + 8 小时。

当前配置 `'0,30 1,2 * * *'`：UTC 01:00/01:30/02:00/02:30 → 北京 09:00/09:30/10:00/10:30。

改完 `git push`，生效需要一点时间（GitHub Actions 刷新配置）。

### 3. 想补发某一天

GitHub → Actions → `daily-ai-news-push` → 「Run workflow」→ 填 `YYYY-MM-DD`，留空 = 今天。

补发模式不会写入状态（`last_pushed_date` 不变），所以可以反复跑。

### 4. 想停掉 / 暂停

GitHub → Actions → 选中 `daily-ai-news-push` → 右上 `···` → `Disable workflow`。随时可 Enable 回来。

### 5. 某个源的 URL 改了怎么办

| 源 | 改哪里 |
|---|---|
| juya RSS | `rss.py` 中的 `_RSS_URL_DEFAULT`（默认值）；代码已兜底：若配置为旧的 `imjuya.github.io` 会自动回退到默认值 |
| aihot API | `aihot.py` 中的 `AIHOT_BASE_URL` + `AIHOT_DAILY_ENDPOINT` |

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
| `daily.juya.uk` | juya 信息源 RSS | 停更 → 3 天后告警；改 URL → 手动更新 `rss.py` 中 `_RSS_URL_DEFAULT` |
| `aihot.virxact.com` | aihot 信息源 JSON API | 停更 → 3 天后告警；改 URL → 手动更新 `aihot.py` 中 `AIHOT_BASE_URL` |
| GitHub Actions | 调度 + 执行 | 免费额度够用；历史上极少宕机 |
| Feishu / Lark 开放平台 | 推送通道 | webhook URL 失效 / 机器人被删 → 连续 3 次失败后告警 |

---

## 对 AI 的一句话说明（给 LLM 看的）

> 这是一个"RSS/JSON → 飞书"双源推送器。入口是 `.github/workflows/daily-ai-news.yml` 的 `schedule`，执行 `push.py`。`push.py` 依次调两个独立函数 `_push_juya()` 和 `_push_aihot()`，各自有独立的去重逻辑、失败计数和停更告警（字段前缀 `juya_` / `aihot_` 写在同一个 `state.json` 中，互不污染）。两个源共用 `lark.py` 的飞书 POST。状态存在仓库根的 `state.json`，每次运行后由 workflow 自动 commit 回去。没有数据库、缓存、外部服务。测试用 `pytest`，72 个测试覆盖 juya 主流程（aihot 流程用相同骨架，测试由 aihot 专项覆盖）。复刻步骤：1) 复制文件结构 2) 设 4 个飞书 secrets 3) 确认 cron 时区正确。
