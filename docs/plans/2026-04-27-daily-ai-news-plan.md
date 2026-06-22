# Daily AI News Push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 用 GitHub Actions + Python 脚本，每日 6 次轮询 juya AI 早报 RSS，发现当日新日报后以飞书富文本卡片形式推送到设计团队飞书群；失败告警走独立运维群。

**Architecture:** 单仓库、无服务器。GitHub Actions 按 cron 触发 `push.py`，脚本拉 RSS、解析 HTML 为飞书 interactive 卡片、带签名 POST 到飞书 webhook，用仓库内 `state.json`（Actions 自动 commit）做去重。4 个密钥全走 GitHub Secrets。

**Tech Stack:** Python 3.11, feedparser, beautifulsoup4, requests, pytz, GitHub Actions

**Related spec:** [docs/specs/2026-04-27-daily-ai-news-design.md](../specs/2026-04-27-daily-ai-news-design.md)

---

## 任务总览

1. 项目骨架（requirements、.gitignore、state.json、pytest 配置）
2. `lark_sign` 签名函数（带测试）
3. `send_lark_text` 纯文本推送（带测试，mock 网络）
4. `fetch_rss` + `extract_today_entry` —— 拉 RSS、按北京时区筛当日
5. `is_pushed_today` / `mark_pushed_today` —— state.json 去重
6. `parse_entry_to_card` —— HTML → 飞书卡片 JSON
7. `send_lark_card` 卡片推送
8. `main()` 主流程
9. 解析失败降级 + 运维群告警
10. 连续失败告警（基于 Actions artifact 计数）
11. GitHub Actions workflow（cron、secrets、自动 commit state.json）
12. README 运维手册
13. `daily-ai-news` skill（setup / test / status / change-time / change-group 子命令）

---

## Task 1: 项目骨架

**Files:**
- Create: `<项目路径>/design-team-ai-daily/.gitignore`
- Create: `<项目路径>/design-team-ai-daily/requirements.txt`
- Create: `<项目路径>/design-team-ai-daily/state.json`
- Create: `<项目路径>/design-team-ai-daily/pytest.ini`
- Create: `<项目路径>/design-team-ai-daily/tests/__init__.py`

- [ ] **Step 1.1: 写 .gitignore**

```
__pycache__/
*.pyc
.pytest_cache/
.venv/
venv/
.env
.DS_Store
```

- [ ] **Step 1.2: 写 requirements.txt**

```
feedparser==6.0.11
beautifulsoup4==4.12.3
requests==2.32.3
pytz==2024.2
pytest==8.3.3
pytest-mock==3.14.0
responses==0.25.3
```

- [ ] **Step 1.3: 写 state.json 初始值**

```json
{"last_pushed_date": null, "consecutive_failures": 0}
```

- [ ] **Step 1.4: 写 pytest.ini**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
```

- [ ] **Step 1.5: 创建空 tests/__init__.py**

`touch tests/__init__.py`

- [ ] **Step 1.6: 装依赖并验证**

```bash
cd <项目路径>/design-team-ai-daily
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest --version
```
Expected: 打印 pytest 版本，无错误

- [ ] **Step 1.7: Commit**

```bash
git add .gitignore requirements.txt state.json pytest.ini tests/
git commit -m "chore: project skeleton"
```

---

## Task 2: 飞书签名函数 `lark_sign`

**Files:**
- Create: `<项目路径>/design-team-ai-daily/lark.py`
- Create: `<项目路径>/design-team-ai-daily/tests/test_lark_sign.py`

飞书自定义机器人签名：`HMAC-SHA256(secret, f"{timestamp}\n{secret}")` → base64。

- [ ] **Step 2.1: 写失败测试**

`tests/test_lark_sign.py`:
```python
from lark import lark_sign

def test_lark_sign_known_vector():
    # 已知向量：timestamp=1609459200, secret="test_secret"
    # 用飞书官方算法离线算出：
    # string_to_sign = "1609459200\ntest_secret"
    # hmac_sha256(secret="test_secret", msg=string_to_sign).b64encode()
    result = lark_sign("test_secret", 1609459200)
    assert result == "oQDP+UxUqWxlZYVjenjhcVbYGNc4lmo2DiFpnE2l01g="

def test_lark_sign_returns_base64_str():
    result = lark_sign("any_secret", 1700000000)
    assert isinstance(result, str)
    # base64 字符串不含空格换行
    assert "\n" not in result and " " not in result
```

- [ ] **Step 2.2: 运行测试确认失败**

Run: `pytest tests/test_lark_sign.py -v`
Expected: FAIL（`lark` 模块不存在）

- [ ] **Step 2.3: 写最小实现**

`lark.py`:
```python
import base64
import hashlib
import hmac


def lark_sign(secret: str, timestamp: int) -> str:
    """飞书自定义机器人签名。

    算法：HMAC-SHA256(key=secret, msg=f"{timestamp}\n{secret}") → base64。
    """
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(
        secret.encode("utf-8"),
        string_to_sign.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")
```

- [ ] **Step 2.4: 先离线验证已知向量**

```bash
python3 -c "
import base64, hashlib, hmac
s = 'test_secret'; t = 1609459200
msg = f'{t}\n{s}'
d = hmac.new(s.encode(), msg.encode(), hashlib.sha256).digest()
print(base64.b64encode(d).decode())
"
```
把实际输出填回 Step 2.1 的 `assert result == "..."`（如果和 `oQDP+UxUqWxlZYVjenjhcVbYGNc4lmo2DiFpnE2l01g=` 不同则以实际为准并更新测试）

- [ ] **Step 2.5: 跑测试确认通过**

Run: `pytest tests/test_lark_sign.py -v`
Expected: 2 passed

- [ ] **Step 2.6: Commit**

```bash
git add lark.py tests/test_lark_sign.py
git commit -m "feat(lark): HMAC-SHA256 signing for Lark bot webhooks"
```

---

## Task 3: 纯文本推送 `send_lark_text`

**Files:**
- Modify: `<项目路径>/design-team-ai-daily/lark.py`
- Create: `<项目路径>/design-team-ai-daily/tests/test_send_lark_text.py`

用于运维群告警。

- [ ] **Step 3.1: 写失败测试**

`tests/test_send_lark_text.py`:
```python
import json
import responses
from lark import send_lark_text

WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/abc"
SECRET = "sec"


@responses.activate
def test_send_lark_text_success():
    responses.add(
        responses.POST,
        WEBHOOK,
        json={"code": 0, "msg": "ok"},
        status=200,
    )
    send_lark_text(WEBHOOK, SECRET, "hello")

    assert len(responses.calls) == 1
    body = json.loads(responses.calls[0].request.body)
    assert body["msg_type"] == "text"
    assert body["content"]["text"] == "hello"
    assert "timestamp" in body
    assert "sign" in body


@responses.activate
def test_send_lark_text_raises_on_lark_error():
    responses.add(
        responses.POST,
        WEBHOOK,
        json={"code": 19021, "msg": "sign verification failed"},
        status=200,
    )
    import pytest
    with pytest.raises(RuntimeError, match="sign verification failed"):
        send_lark_text(WEBHOOK, SECRET, "hello")


@responses.activate
def test_send_lark_text_raises_on_http_error():
    responses.add(
        responses.POST,
        WEBHOOK,
        json={"error": "nope"},
        status=500,
    )
    import pytest
    with pytest.raises(RuntimeError):
        send_lark_text(WEBHOOK, SECRET, "hello")
```

- [ ] **Step 3.2: 运行测试确认失败**

Run: `pytest tests/test_send_lark_text.py -v`
Expected: FAIL（`send_lark_text` 不存在）

- [ ] **Step 3.3: 实现 `send_lark_text`**

追加到 `lark.py`：
```python
import time
import requests


def send_lark_text(webhook: str, secret: str, text: str, timeout: int = 10) -> None:
    """推一条纯文本到飞书自定义机器人。失败抛 RuntimeError。"""
    timestamp = int(time.time())
    payload = {
        "timestamp": str(timestamp),
        "sign": lark_sign(secret, timestamp),
        "msg_type": "text",
        "content": {"text": text},
    }
    resp = requests.post(webhook, json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"lark http {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"lark error {data.get('code')}: {data.get('msg')}")
```

- [ ] **Step 3.4: 跑测试确认通过**

Run: `pytest tests/test_send_lark_text.py -v`
Expected: 3 passed

- [ ] **Step 3.5: Commit**

```bash
git add lark.py tests/test_send_lark_text.py
git commit -m "feat(lark): send_lark_text with sign verification"
```

---

## Task 4: RSS 拉取 + 当日条目提取

**Files:**
- Create: `<项目路径>/design-team-ai-daily/rss.py`
- Create: `<项目路径>/design-team-ai-daily/tests/fixtures/juya_sample.xml`
- Create: `<项目路径>/design-team-ai-daily/tests/test_rss.py`

- [ ] **Step 4.1: 抓一份真实 RSS 样本作为 fixture**

```bash
curl -s https://imjuya.github.io/juya-ai-daily/rss.xml > tests/fixtures/juya_sample.xml
```

- [ ] **Step 4.2: 写失败测试**

`tests/test_rss.py`:
```python
from datetime import datetime
import pytz
from rss import extract_today_entry, parse_feed

FIXTURE = "tests/fixtures/juya_sample.xml"


def test_parse_feed_returns_entries():
    entries = parse_feed(open(FIXTURE).read())
    assert len(entries) > 0
    first = entries[0]
    assert "title" in first
    assert "link" in first
    assert "published_dt" in first  # datetime in UTC
    assert "content_html" in first


def test_extract_today_entry_matches_beijing_today():
    xml = open(FIXTURE).read()
    # 伪造"今天"是 fixture 最新那期的日期
    entries = parse_feed(xml)
    latest_pub_beijing = entries[0]["published_dt"].astimezone(pytz.timezone("Asia/Shanghai"))
    fake_today = latest_pub_beijing.date()

    entry = extract_today_entry(xml, today=fake_today)
    assert entry is not None
    assert entry["title"].startswith(fake_today.strftime("%Y-%m-%d"))


def test_extract_today_entry_returns_none_when_no_match():
    xml = open(FIXTURE).read()
    # 2000 年绝不会有条目
    from datetime import date
    entry = extract_today_entry(xml, today=date(2000, 1, 1))
    assert entry is None
```

- [ ] **Step 4.3: 运行测试确认失败**

Run: `pytest tests/test_rss.py -v`
Expected: FAIL

- [ ] **Step 4.4: 实现**

`rss.py`:
```python
from datetime import date, datetime
from typing import Optional

import feedparser
import pytz
import requests

BEIJING = pytz.timezone("Asia/Shanghai")
RSS_URL = "https://imjuya.github.io/juya-ai-daily/rss.xml"


def fetch_rss(url: str = RSS_URL, timeout: int = 20) -> str:
    resp = requests.get(url, timeout=timeout)
    resp.raise_for_status()
    return resp.text


def parse_feed(xml: str) -> list[dict]:
    """返回 entries 列表，按 published 倒序。"""
    feed = feedparser.parse(xml)
    entries = []
    for e in feed.entries:
        pub = datetime(*e.published_parsed[:6], tzinfo=pytz.utc)
        content_html = ""
        if "content" in e and e.content:
            content_html = e.content[0].value
        elif "description" in e:
            content_html = e.description
        entries.append({
            "title": e.title,
            "link": e.link,
            "published_dt": pub,
            "content_html": content_html,
            "description": e.get("description", ""),
        })
    entries.sort(key=lambda x: x["published_dt"], reverse=True)
    return entries


def extract_today_entry(xml: str, today: Optional[date] = None) -> Optional[dict]:
    """返回 published 对应"今天（北京时区）"的条目；没有则 None。"""
    if today is None:
        today = datetime.now(BEIJING).date()
    entries = parse_feed(xml)
    for e in entries:
        pub_beijing = e["published_dt"].astimezone(BEIJING).date()
        if pub_beijing == today:
            return e
    return None
```

- [ ] **Step 4.5: 跑测试确认通过**

Run: `pytest tests/test_rss.py -v`
Expected: 3 passed

- [ ] **Step 4.6: Commit**

```bash
git add rss.py tests/test_rss.py tests/fixtures/juya_sample.xml
git commit -m "feat(rss): fetch and extract today's juya entry in Beijing TZ"
```

---

## Task 5: state.json 读写 `is_pushed_today` / `mark_pushed_today`

**Files:**
- Create: `<项目路径>/design-team-ai-daily/state.py`
- Create: `<项目路径>/design-team-ai-daily/tests/test_state.py`

- [ ] **Step 5.1: 写失败测试**

`tests/test_state.py`:
```python
import json
from datetime import date
from pathlib import Path
from state import is_pushed_today, mark_pushed_today, load_state, bump_failure, reset_failure


def test_is_pushed_today_false_when_null(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 0}))
    assert is_pushed_today(path, today=date(2026, 4, 27)) is False


def test_is_pushed_today_true_when_match(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_pushed_date": "2026-04-27", "consecutive_failures": 0}))
    assert is_pushed_today(path, today=date(2026, 4, 27)) is True


def test_mark_pushed_today_writes_iso_date(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 3}))
    mark_pushed_today(path, today=date(2026, 4, 27))
    data = json.loads(path.read_text())
    assert data["last_pushed_date"] == "2026-04-27"
    assert data["consecutive_failures"] == 0  # 推成功清零


def test_bump_failure_increments(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 2}))
    n = bump_failure(path)
    assert n == 3
    assert json.loads(path.read_text())["consecutive_failures"] == 3


def test_reset_failure(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 5}))
    reset_failure(path)
    assert json.loads(path.read_text())["consecutive_failures"] == 0
```

- [ ] **Step 5.2: 运行测试确认失败**

Run: `pytest tests/test_state.py -v`
Expected: FAIL

- [ ] **Step 5.3: 实现**

`state.py`:
```python
import json
from datetime import date
from pathlib import Path


def load_state(path: Path) -> dict:
    data = json.loads(Path(path).read_text())
    data.setdefault("last_pushed_date", None)
    data.setdefault("consecutive_failures", 0)
    return data


def save_state(path: Path, data: dict) -> None:
    Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")


def is_pushed_today(path: Path, today: date) -> bool:
    data = load_state(path)
    return data["last_pushed_date"] == today.isoformat()


def mark_pushed_today(path: Path, today: date) -> None:
    data = load_state(path)
    data["last_pushed_date"] = today.isoformat()
    data["consecutive_failures"] = 0
    save_state(path, data)


def bump_failure(path: Path) -> int:
    data = load_state(path)
    data["consecutive_failures"] += 1
    save_state(path, data)
    return data["consecutive_failures"]


def reset_failure(path: Path) -> None:
    data = load_state(path)
    data["consecutive_failures"] = 0
    save_state(path, data)
```

- [ ] **Step 5.4: 跑测试确认通过**

Run: `pytest tests/test_state.py -v`
Expected: 5 passed

- [ ] **Step 5.5: Commit**

```bash
git add state.py tests/test_state.py
git commit -m "feat(state): dedup + consecutive-failure counter"
```

---

## Task 6: HTML → 飞书卡片 JSON `parse_entry_to_card`

**Files:**
- Create: `<项目路径>/design-team-ai-daily/lark_card.py`
- Create: `<项目路径>/design-team-ai-daily/tests/test_lark_card.py`

### 6.1 设计说明

juya 一期日报的 HTML 结构（基于 fixture 观察）：封面图 → 概览列表（每条带 "↗ #编号"）→ 分组标题（"## 要闻 / 开发生态 / 前瞻与传闻 / ..."）→ 每条详情段落。

解析策略：**只取概览列表**（一条日报的骨架），因为详情段落太长不适合卡片；用户点"查看完整日报"去看详情。概览中每条带原始链接，足够团队决策是否点开。

分类颜色映射：
```python
CATEGORY_COLORS = {
    "要闻": "red",
    "开发生态": "blue",
    "产品应用": "green",
    "技术与洞察": "yellow",
    "行业动态": "orange",
    "前瞻与传闻": "purple",
}
DEFAULT_COLOR = "grey"
```

- [ ] **Step 6.1: 写失败测试**

`tests/test_lark_card.py`:
```python
from rss import parse_feed
from lark_card import parse_entry_to_card, CATEGORY_COLORS


def load_latest_entry():
    return parse_feed(open("tests/fixtures/juya_sample.xml").read())[0]


def test_card_has_header_with_date():
    entry = load_latest_entry()
    card = parse_entry_to_card(entry)
    assert card["header"]["template"] in ("purple", "blue", "indigo")
    title_text = card["header"]["title"]["content"]
    assert "橘鸦 AI 早报" in title_text
    assert entry["title"] in title_text  # e.g., "2026-04-27"


def test_card_contains_category_sections():
    entry = load_latest_entry()
    card = parse_entry_to_card(entry)
    # 每个分类组应是一个 div 或 markdown 元素
    text_blob = str(card)
    # 至少有一个已知分类出现
    assert any(cat in text_blob for cat in CATEGORY_COLORS)


def test_card_contains_view_full_button():
    entry = load_latest_entry()
    card = parse_entry_to_card(entry)
    actions = [e for e in card["elements"] if e.get("tag") == "action"]
    assert len(actions) >= 1
    buttons = actions[-1]["actions"]
    urls = [b["url"] for b in buttons if "url" in b]
    assert entry["link"] in urls  # "查看完整日报" 按钮指向日报链接


def test_card_has_disclaimer():
    entry = load_latest_entry()
    card = parse_entry_to_card(entry)
    text_blob = str(card)
    assert "juya" in text_blob.lower() or "AI 辅助" in text_blob


def test_card_json_serializable():
    import json
    entry = load_latest_entry()
    card = parse_entry_to_card(entry)
    # 必须能被 json 序列化（飞书 API 要求）
    json.dumps(card)
```

- [ ] **Step 6.2: 运行测试确认失败**

Run: `pytest tests/test_lark_card.py -v`
Expected: FAIL

- [ ] **Step 6.3: 实现**

`lark_card.py`:
```python
import re
from typing import Optional

from bs4 import BeautifulSoup


CATEGORY_COLORS = {
    "要闻": "red",
    "开发生态": "blue",
    "产品应用": "green",
    "技术与洞察": "yellow",
    "行业动态": "orange",
    "前瞻与传闻": "purple",
}
DEFAULT_COLOR = "grey"
CATEGORY_EMOJIS = {
    "要闻": "🔴",
    "开发生态": "🔵",
    "产品应用": "🟢",
    "技术与洞察": "🟡",
    "行业动态": "🟠",
    "前瞻与传闻": "🟣",
}


def _extract_overview_groups(html: str) -> list[dict]:
    """从 juya HTML 里抽出分组 + 每组内的概览条目。

    返回形如：
    [
      {"category": "要闻", "items": [{"title": "...", "url": "..."}, ...]},
      ...
    ]
    只取概览部分（每条带 "↗" 或 "#编号"），不取后面的详情段落。
    """
    soup = BeautifulSoup(html, "html.parser")

    groups: list[dict] = []
    current: Optional[dict] = None

    # juya 用 <h2>/<h3> 做分组标题，或者用 <p><strong>...</strong></p>
    # 先尝试所有可能的标题节点
    for node in soup.find_all(["h1", "h2", "h3", "h4", "p", "li", "ul"]):
        text = node.get_text(strip=True)
        # 分组标题判断
        for cat in CATEGORY_COLORS:
            if text == cat or text.startswith(cat + " ") or text.endswith(cat):
                if current:
                    groups.append(current)
                current = {"category": cat, "items": []}
                break
        else:
            # 条目判断：带 "↗" 或 "#数字" 或链接的短行
            if current is not None and node.name in ("li", "p"):
                a = node.find("a")
                if a and a.get("href"):
                    raw = text.rstrip("↗").strip()
                    # 去掉尾部 "#1" 之类
                    cleaned = re.sub(r"\s*#\d+\s*$", "", raw).strip()
                    if cleaned and len(cleaned) < 200:
                        current["items"].append({
                            "title": cleaned,
                            "url": a["href"],
                        })
    if current:
        groups.append(current)

    return [g for g in groups if g["items"]]


def _extract_video_links(description: str, content_html: str) -> dict:
    """提取 B 站 / YouTube 视频链接。"""
    urls = {"bilibili": None, "youtube": None}
    combined = (description or "") + (content_html or "")
    b = re.search(r'https?://[^\s"<>]*bilibili\.com/[^\s"<>]+', combined)
    y = re.search(r'https?://[^\s"<>]*(?:youtube\.com|youtu\.be)/[^\s"<>]+', combined)
    if b:
        urls["bilibili"] = b.group(0)
    if y:
        urls["youtube"] = y.group(0)
    return urls


def parse_entry_to_card(entry: dict) -> dict:
    """把一期 juya 日报转为飞书 interactive 卡片 JSON。"""
    title = entry["title"]  # e.g., "2026-04-27"
    link = entry["link"]
    groups = _extract_overview_groups(entry["content_html"])
    videos = _extract_video_links(entry.get("description", ""), entry["content_html"])

    elements: list[dict] = []

    for g in groups:
        emoji = CATEGORY_EMOJIS.get(g["category"], "⚪")
        md_lines = [f"**{emoji} {g['category']}**"]
        for item in g["items"]:
            md_lines.append(f"• [{item['title']}]({item['url']})")
        elements.append({
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": "\n".join(md_lines),
            },
        })
        elements.append({"tag": "hr"})

    # 去掉最后一个 hr
    if elements and elements[-1].get("tag") == "hr":
        elements.pop()

    # 底部按钮
    buttons = [{
        "tag": "button",
        "text": {"tag": "plain_text", "content": "📖 查看完整日报"},
        "type": "primary",
        "url": link,
    }]
    if videos["bilibili"]:
        buttons.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🎬 B站"},
            "type": "default",
            "url": videos["bilibili"],
        })
    if videos["youtube"]:
        buttons.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🎬 YouTube"},
            "type": "default",
            "url": videos["youtube"],
        })
    elements.append({"tag": "action", "actions": buttons})

    # 免责备注
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "资讯由 juya AI 辅助生成，可能存在错误，请以原始信息出处为准。",
        }],
    })

    card = {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": "purple",
            "title": {
                "tag": "plain_text",
                "content": f"🤖 橘鸦 AI 早报 · {title}",
            },
        },
        "elements": elements,
    }
    return card
```

- [ ] **Step 6.4: 跑测试确认通过**

Run: `pytest tests/test_lark_card.py -v`
Expected: 5 passed

**如果分组提取失败（groups 为空）**：这说明 juya HTML 结构和预期不同。调整 `_extract_overview_groups` 的节点选择器直到 fixture 能解析出至少 1 个分组 + 1 条新闻。这是**允许迭代**的步骤——目标是 fixture 数据能出卡片，不要求覆盖所有历史结构。

- [ ] **Step 6.5: Commit**

```bash
git add lark_card.py tests/test_lark_card.py
git commit -m "feat(card): parse juya HTML into Lark interactive card"
```

---

## Task 7: 卡片推送 `send_lark_card`

**Files:**
- Modify: `<项目路径>/design-team-ai-daily/lark.py`
- Create: `<项目路径>/design-team-ai-daily/tests/test_send_lark_card.py`

- [ ] **Step 7.1: 写失败测试**

`tests/test_send_lark_card.py`:
```python
import json
import responses
from lark import send_lark_card

WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/xyz"
SECRET = "sec"


@responses.activate
def test_send_lark_card_success():
    responses.add(responses.POST, WEBHOOK, json={"code": 0, "msg": "ok"}, status=200)
    card = {"header": {}, "elements": []}
    send_lark_card(WEBHOOK, SECRET, card)

    body = json.loads(responses.calls[0].request.body)
    assert body["msg_type"] == "interactive"
    assert body["card"] == card
    assert "timestamp" in body and "sign" in body


@responses.activate
def test_send_lark_card_raises_on_error():
    responses.add(responses.POST, WEBHOOK, json={"code": 9499, "msg": "bad card"}, status=200)
    import pytest
    with pytest.raises(RuntimeError, match="bad card"):
        send_lark_card(WEBHOOK, SECRET, {"header": {}, "elements": []})
```

- [ ] **Step 7.2: 跑测试看失败**

Run: `pytest tests/test_send_lark_card.py -v`
Expected: FAIL

- [ ] **Step 7.3: 追加实现到 lark.py**

```python
def send_lark_card(webhook: str, secret: str, card: dict, timeout: int = 10) -> None:
    """推一张 interactive 卡片到飞书。失败抛 RuntimeError。"""
    timestamp = int(time.time())
    payload = {
        "timestamp": str(timestamp),
        "sign": lark_sign(secret, timestamp),
        "msg_type": "interactive",
        "card": card,
    }
    resp = requests.post(webhook, json=payload, timeout=timeout)
    if resp.status_code != 200:
        raise RuntimeError(f"lark http {resp.status_code}: {resp.text[:200]}")
    data = resp.json()
    if data.get("code", 0) != 0:
        raise RuntimeError(f"lark error {data.get('code')}: {data.get('msg')}")
```

- [ ] **Step 7.4: 跑测试确认通过**

Run: `pytest -v`
Expected: 全绿

- [ ] **Step 7.5: Commit**

```bash
git add lark.py tests/test_send_lark_card.py
git commit -m "feat(lark): send_lark_card for interactive messages"
```

---

## Task 8: 主流程 `push.py`

**Files:**
- Create: `<项目路径>/design-team-ai-daily/push.py`
- Create: `<项目路径>/design-team-ai-daily/tests/test_push.py`

### 8.1 行为（对照 spec §6）

```
1. 读环境变量：LARK_WEBHOOK_URL, LARK_WEBHOOK_SECRET, LARK_OPS_WEBHOOK_URL, LARK_OPS_WEBHOOK_SECRET
2. today = 北京时区今天
3. if is_pushed_today(today): log "already pushed"; exit 0
4. xml = fetch_rss()
5. entry = extract_today_entry(xml, today)
6. if entry is None: log "juya not updated yet"; exit 0
7. try:
      card = parse_entry_to_card(entry)
      if card 的 elements 里没有任何分组：
          raise ParseDegradedError  # 触发降级
      send_lark_card(WEBHOOK, SECRET, card)
      mark_pushed_today(today)
      exit 0
   except ParseDegradedError:
      # 降级：推纯文本 + 告警运维群
      text = f"🤖 橘鸦 AI 早报 · {entry['title']}\n（解析降级）\n{entry['link']}"
      send_lark_text(WEBHOOK, SECRET, text)
      mark_pushed_today(today)
      send_lark_text(OPS_URL, OPS_SECRET, f"⚠️ 今日内容解析降级\nrun: {os.environ.get('GITHUB_SERVER_URL','')}/{os.environ.get('GITHUB_REPOSITORY','')}/actions/runs/{os.environ.get('GITHUB_RUN_ID','')}")
      exit 0
   except Exception as e:
      n = bump_failure()
      log(f"push failed ({n}): {e}")
      if n >= 3:
          try:
              send_lark_text(OPS_URL, OPS_SECRET, f"⚠️ 今日推送连续 {n} 次失败: {e}")
              reset_failure()  # 告警后重置，避免每次轮询都再告警
          except Exception:
              pass
      exit 1  # Actions 标红
```

- [ ] **Step 8.1: 写失败测试（主要覆盖几个关键分支）**

`tests/test_push.py`:
```python
import json
import os
from datetime import date
from unittest.mock import patch

import pytest

import push


ENV = {
    "LARK_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/main",
    "LARK_WEBHOOK_SECRET": "s1",
    "LARK_OPS_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/ops",
    "LARK_OPS_WEBHOOK_SECRET": "s2",
}


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 0}))
    monkeypatch.setattr(push, "STATE_PATH", p)
    return p


def test_skip_when_already_pushed_today(state_path, monkeypatch):
    state_path.write_text(json.dumps({"last_pushed_date": "2026-04-27", "consecutive_failures": 0}))
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))
    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0


def test_skip_when_juya_not_updated(state_path, monkeypatch):
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    monkeypatch.setattr(push, "extract_today_entry", lambda xml, today: None)
    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0
    assert json.loads(state_path.read_text())["last_pushed_date"] is None  # 未推


def test_happy_path_pushes_and_marks(state_path, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    monkeypatch.setattr(push, "extract_today_entry",
                        lambda xml, today: {"title": "2026-04-27", "link": "http://x", "content_html": "", "description": ""})
    monkeypatch.setattr(push, "parse_entry_to_card",
                        lambda e: {"header": {}, "elements": [{"tag": "div", "text": {"content": "要闻"}}]})
    monkeypatch.setattr(push, "send_lark_card",
                        lambda url, secret, card: sent.append(("card", url)))
    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0
    assert sent == [("card", ENV["LARK_WEBHOOK_URL"])]
    assert json.loads(state_path.read_text())["last_pushed_date"] == "2026-04-27"


def test_failure_bumps_and_alerts_at_three(state_path, monkeypatch):
    state_path.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 2}))
    sent = []
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    monkeypatch.setattr(push, "extract_today_entry",
                        lambda xml, today: {"title": "2026-04-27", "link": "http://x", "content_html": "", "description": ""})
    monkeypatch.setattr(push, "parse_entry_to_card",
                        lambda e: {"header": {}, "elements": [{"tag": "div"}]})

    def boom(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(push, "send_lark_card", boom)
    monkeypatch.setattr(push, "send_lark_text",
                        lambda url, secret, text: sent.append(("text", url, text)))

    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 1
    # 告警应发到运维群
    assert any(s[1] == ENV["LARK_OPS_WEBHOOK_URL"] for s in sent)
    # 告警后 counter 重置
    assert json.loads(state_path.read_text())["consecutive_failures"] == 0


def test_degraded_parse_falls_back_to_text(state_path, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    monkeypatch.setattr(push, "extract_today_entry",
                        lambda xml, today: {"title": "2026-04-27", "link": "http://x", "content_html": "", "description": ""})
    # 返回空分组卡片 → 触发降级
    monkeypatch.setattr(push, "parse_entry_to_card",
                        lambda e: {"header": {}, "elements": [{"tag": "note"}]})
    monkeypatch.setattr(push, "send_lark_text",
                        lambda url, secret, text: sent.append((url, text)))
    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0
    urls = [s[0] for s in sent]
    # 主群收到纯文本，运维群收到降级告警
    assert ENV["LARK_WEBHOOK_URL"] in urls
    assert ENV["LARK_OPS_WEBHOOK_URL"] in urls
    assert json.loads(state_path.read_text())["last_pushed_date"] == "2026-04-27"
```

- [ ] **Step 8.2: 跑测试确认失败**

Run: `pytest tests/test_push.py -v`
Expected: FAIL（push 模块不存在）

- [ ] **Step 8.3: 实现 push.py**

`push.py`:
```python
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytz

from lark import send_lark_card, send_lark_text
from lark_card import parse_entry_to_card
from rss import extract_today_entry, fetch_rss
from state import (
    bump_failure,
    is_pushed_today,
    mark_pushed_today,
    reset_failure,
)

BEIJING = pytz.timezone("Asia/Shanghai")
STATE_PATH = Path(__file__).parent / "state.json"


def _today() -> date:
    return datetime.now(BEIJING).date()


def _card_has_content(card: dict) -> bool:
    """卡片里有任何 lark_md/div 带非空内容 → 正常；只有 note → 视为解析失败。"""
    for e in card.get("elements", []):
        if e.get("tag") == "div":
            content = e.get("text", {}).get("content", "")
            if content.strip():
                return True
    return False


def _actions_run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "")
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if server and repo and run_id:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return "(local run)"


def main() -> int:
    webhook = os.environ["LARK_WEBHOOK_URL"]
    secret = os.environ["LARK_WEBHOOK_SECRET"]
    ops_webhook = os.environ["LARK_OPS_WEBHOOK_URL"]
    ops_secret = os.environ["LARK_OPS_WEBHOOK_SECRET"]

    today = _today()

    if is_pushed_today(STATE_PATH, today):
        print(f"[skip] already pushed today ({today})")
        return 0

    xml = fetch_rss()
    entry = extract_today_entry(xml, today=today)
    if entry is None:
        print(f"[skip] juya not updated yet for {today}")
        return 0

    try:
        card = parse_entry_to_card(entry)
        if not _card_has_content(card):
            # 降级：纯文本
            text = (
                f"🤖 橘鸦 AI 早报 · {entry['title']}\n"
                f"（内容解析降级，请点击原文查看）\n"
                f"{entry['link']}"
            )
            send_lark_text(webhook, secret, text)
            mark_pushed_today(STATE_PATH, today)
            try:
                send_lark_text(
                    ops_webhook, ops_secret,
                    f"⚠️ 今日内容解析降级\nrun: {_actions_run_url()}",
                )
            except Exception as ops_e:
                print(f"[warn] ops alert failed: {ops_e}")
            print(f"[ok] pushed (degraded) {today}")
            return 0

        send_lark_card(webhook, secret, card)
        mark_pushed_today(STATE_PATH, today)
        print(f"[ok] pushed {today}")
        return 0

    except Exception as e:
        n = bump_failure(STATE_PATH)
        print(f"[fail] push attempt failed ({n}/3): {e}", file=sys.stderr)
        if n >= 3:
            try:
                send_lark_text(
                    ops_webhook, ops_secret,
                    f"⚠️ 今日推送连续 {n} 次失败\n错误：{e}\nrun: {_actions_run_url()}",
                )
                reset_failure(STATE_PATH)
            except Exception as ops_e:
                print(f"[warn] ops alert failed: {ops_e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 8.4: 跑测试确认通过**

Run: `pytest tests/test_push.py -v`
Expected: 5 passed

- [ ] **Step 8.5: 跑全部测试**

Run: `pytest -v`
Expected: 全绿（约 20+ 个测试）

- [ ] **Step 8.6: Commit**

```bash
git add push.py tests/test_push.py
git commit -m "feat(push): main flow with dedup, degraded fallback, failure alerts"
```

---

## Task 9: GitHub Actions workflow

**Files:**
- Create: `<项目路径>/design-team-ai-daily/.github/workflows/push.yml`

### 9.1 要点

- 6 个 cron 时间点（UTC）：01:01, 01:31, 02:01, 02:31, 03:01, 03:31
- 需要写权限（commit state.json 回仓库）
- 失败（exit 1）让 Actions 标红
- 加 `workflow_dispatch` 方便手动触发

- [ ] **Step 9.1: 写 workflow**

`.github/workflows/push.yml`:
```yaml
name: daily-ai-news-push
on:
  schedule:
    # 北京时间 09:01 / 09:31 / 10:01 / 10:31 / 11:01 / 11:31
    - cron: '1,31 1-3 * * *'
  workflow_dispatch: {}

permissions:
  contents: write   # commit state.json

jobs:
  push:
    runs-on: ubuntu-latest
    timeout-minutes: 5
    concurrency:
      group: daily-ai-news-push   # 防两个轮询同时跑
      cancel-in-progress: false
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: pip

      - run: pip install -r requirements.txt

      - run: python push.py
        env:
          LARK_WEBHOOK_URL: ${{ secrets.LARK_WEBHOOK_URL }}
          LARK_WEBHOOK_SECRET: ${{ secrets.LARK_WEBHOOK_SECRET }}
          LARK_OPS_WEBHOOK_URL: ${{ secrets.LARK_OPS_WEBHOOK_URL }}
          LARK_OPS_WEBHOOK_SECRET: ${{ secrets.LARK_OPS_WEBHOOK_SECRET }}

      - name: commit state.json if changed
        if: always()   # 即使 push.py 失败也要提交失败计数
        run: |
          if ! git diff --quiet state.json; then
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add state.json
            git commit -m "chore(state): update push state [skip ci]"
            git push
          fi
```

- [ ] **Step 9.2: 本地 dry-run 验证 YAML 语法**

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/push.yml'))" && echo "YAML OK"
```
Expected: "YAML OK"

- [ ] **Step 9.3: Commit**

```bash
git add .github/workflows/push.yml
git commit -m "ci: GitHub Actions cron workflow for 6x/day polling"
```

---

## Task 10: README 运维手册

**Files:**
- Create: `<项目路径>/design-team-ai-daily/README.md`

- [ ] **Step 10.1: 写 README**

内容包含：
- 项目简介（一句话）
- 架构图（简化版）
- 4 个 Secrets 说明（名字、在哪拿、怎么设）
- 运行时行为表（对照 spec §6）
- 日常运维：怎么换群 / 改时间 / 看日志 / 手动触发
- 故障排查：早报没到怎么办（5 步自查）

```markdown
# design-team-ai-daily

每日把 [橘鸦 AI 早报](https://imjuya.github.io/juya-ai-daily/) 自动推送到设计团队飞书群。

## 架构

GitHub Actions 每天北京时间 09:01/09:31/10:01/10:31/11:01/11:31 各跑一次 `push.py`，
拉 juya RSS → 如果当日有新日报且今天还没推过 → 格式化为飞书卡片 → 推送 → 更新 `state.json`。

## 部署

### 1. 飞书机器人

在**设计团队飞书群**里：
群设置 → 群机器人 → 添加机器人 → **自定义机器人**。
**必须开启"签名校验"**。保存得到：
- `Webhook URL`（形如 `https://open.feishu.cn/open-apis/bot/v2/hook/xxx`）
- `签名 Secret`

在**另一个运维群（或你自己和机器人的私聊）**重复一次，得到第二对。

### 2. GitHub Secrets

仓库 Settings → Secrets and variables → Actions → New repository secret，添加 4 个：

| Secret 名 | 值 |
|---|---|
| `LARK_WEBHOOK_URL` | 设计团队群 webhook |
| `LARK_WEBHOOK_SECRET` | 设计团队群签名 secret |
| `LARK_OPS_WEBHOOK_URL` | 运维群 webhook |
| `LARK_OPS_WEBHOOK_SECRET` | 运维群签名 secret |

或用 `gh` CLI：
```bash
gh secret set LARK_WEBHOOK_URL -b "https://..."
gh secret set LARK_WEBHOOK_SECRET -b "xxx"
gh secret set LARK_OPS_WEBHOOK_URL -b "https://..."
gh secret set LARK_OPS_WEBHOOK_SECRET -b "xxx"
```

### 3. 首次验证

仓库 Actions → daily-ai-news-push → Run workflow → main → Run。
如果 juya 今天的日报已发布，飞书群应在 10 秒内收到卡片。

## 运维

### 换群
重新建一个飞书机器人，更新 `LARK_WEBHOOK_URL` 和 `LARK_WEBHOOK_SECRET`。

### 改推送时间
编辑 `.github/workflows/push.yml` 的 cron。注意 GitHub Actions 用 UTC，北京时间减 8 小时。

### 看日志
仓库 Actions → 选一次 run → 看 `push.py` 的 stdout。正常情况应看到：
- `[ok] pushed 2026-04-27`（成功）
- `[skip] already pushed today`（当日已推）
- `[skip] juya not updated yet`（juya 还没发）

### 早报没到怎么办

1. **看 Actions 是否在跑**：仓库 Actions 页，今天有没有 run。没有 → GitHub Actions 被关了，去 Settings 打开。
2. **看 run 是否报错**：点进最新 run，如果红叉，看 stderr。
3. **自己试 juya 是否更新**：浏览器打开 https://imjuya.github.io/juya-ai-daily/rss.xml 看最上面一条是不是今天的。不是 → juya 今天没发，等。
4. **测 webhook 是否有效**：手动触发 workflow（workflow_dispatch），看是否到群。
5. **还不行**：`git log state.json` 看最后一次成功推送是哪天，对照 Actions 历史找断点。

## 开发

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -v
```
```

- [ ] **Step 10.2: Commit**

```bash
git add README.md
git commit -m "docs: deployment and ops guide"
```

---

## Task 11: daily-ai-news skill

**Files:**
- Create: `<你的用户目录>/.claude/skills/daily-ai-news/SKILL.md`

### 11.1 skill 性质

这是**辅助工具 skill**（不是 discipline skill），目的：当用户说"/daily-ai-news xxx"时，Claude 知道怎么做对应的运维动作。不走 writing-skills 的 TDD 压测流程（那是给纪律类 skill 用的）。

- [ ] **Step 11.1: 确保目录存在**

```bash
mkdir -p <你的用户目录>/.claude/skills/daily-ai-news
```

- [ ] **Step 11.2: 写 SKILL.md**

```markdown
---
name: daily-ai-news
description: Use when the user wants to set up, test, configure, or troubleshoot the design-team-ai-daily push system — a GitHub-Actions-based daily Lark push of juya AI news to a design team group. Triggers on phrases like "/daily-ai-news setup", "早报没到", "换个飞书群", "改推送时间", "手动推一次测试".
---

# Daily AI News Skill

## Overview

辅助运维 [design-team-ai-daily](file://<项目路径>/design-team-ai-daily) 这个项目。项目本身的推送逻辑跑在 GitHub Actions 上，与 Claude 无关；skill 的作用是帮用户搭建、配置、排障。

**Project home:** `<项目路径>/design-team-ai-daily`
**GitHub repo:** `<你的用户名>/design-team-ai-daily` (private)

## When to Use

| 用户说 | 对应动作 |
|---|---|
| `/daily-ai-news setup`、"帮我搭早报系统" | 走 Setup 流程 |
| `/daily-ai-news test`、"手动推一次" | Test 流程 |
| `/daily-ai-news status`、"最近推送情况" | Status 流程 |
| `/daily-ai-news change-time`、"改推送时间" | Change Time 流程 |
| `/daily-ai-news change-group`、"换飞书群" | Change Group 流程 |
| "早报没到"、"今天没收到推送" | Troubleshoot 流程 |

## Setup 流程

1. 确认前置：用户有 `gh` CLI 登录、飞书群管理员权限
2. 在项目目录：`cd <项目路径>/design-team-ai-daily`
3. 引导用户去飞书拿 2 对 webhook + secret（设计群 + 运维群），**开启签名校验**
4. 用 `gh repo create <你的用户名>/design-team-ai-daily --private --source=. --push` 建仓库并推
5. 用 `gh secret set` 设置 4 个密钥（`LARK_WEBHOOK_URL` / `LARK_WEBHOOK_SECRET` / `LARK_OPS_WEBHOOK_URL` / `LARK_OPS_WEBHOOK_SECRET`）
6. `gh workflow run daily-ai-news-push.yml` 手动触发一次
7. `gh run watch` 看实时日志
8. 确认飞书群收到卡片（或 juya 今天还没发的话收到 "[skip] juya not updated yet" 日志）

**安全红线（来自用户 CLAUDE.md）**：密钥从用户口头或剪贴板获得，**绝不进 commit、绝不进日志、绝不回显完整值**。`gh secret set` 输入时提示用户直接粘贴。

## Test 流程

"强制推一次"意味着：绕过 `is_pushed_today` 检查，而且推到**运维群**而不是正式群，避免打扰。

1. `cd <项目路径>/design-team-ai-daily`
2. 临时把 state.json 的 `last_pushed_date` 改成 null（或用环境变量覆盖 webhook 指向运维群）
3. 本地跑 `LARK_WEBHOOK_URL=$LARK_OPS_WEBHOOK_URL LARK_WEBHOOK_SECRET=$LARK_OPS_WEBHOOK_SECRET LARK_OPS_WEBHOOK_URL=... LARK_OPS_WEBHOOK_SECRET=... python push.py`
4. 或用 `gh workflow run` + 一个临时 input 参数（未来扩展）

**注意**：测试完**恢复 state.json**，不要污染真实推送历史。

## Status 流程

1. `gh run list --workflow=daily-ai-news-push.yml --limit 20` 看最近 20 次
2. `git log --follow state.json | head -30` 看 state 变化史（等于"哪些天真的推了"）
3. 对比"应该推的天数"和"实际推的天数"，列出缺失

## Change Time / Change Group 流程

- Change Time：编辑 `.github/workflows/push.yml` 的 `cron`，**必须先转换北京时间→UTC**（减 8 小时）；改完 commit + push
- Change Group：指导用户在新群建机器人，更新对应 secret（`gh secret set`），**旧 webhook 在飞书端删掉**防止泄露

## Troubleshoot 流程

按 README 的 5 步自查顺序，但由 Claude 主动去查：

1. `gh run list --workflow=daily-ai-news-push.yml --limit 5` —— 最近 5 次是否在跑、是否成功
2. 如果最新 run 失败：`gh run view <id> --log-failed` 看失败日志
3. `curl -s https://imjuya.github.io/juya-ai-daily/rss.xml | head -30` —— juya 自己是否更新了今天
4. 如果 juya 更新了但 Actions 没推：触发一次 `gh workflow run` 看现场
5. 如果还失败：读 `push.py` 日志定位哪一步（网络 / 签名 / 解析）

## Red Flags

- ❌ 直接把 webhook URL 或 secret 写进代码、commit、日志、Claude 对话的明文
- ❌ 未经用户确认就 `git push --force` 或 `gh secret delete`
- ❌ 测试时推到正式群（一定用运维群或临时 webhook）
- ❌ 不核对北京/UTC 时差就改 cron
```

- [ ] **Step 11.3: 验证 skill 可被 Claude Code 识别**

```bash
ls -la <你的用户目录>/.claude/skills/daily-ai-news/
head -5 <你的用户目录>/.claude/skills/daily-ai-news/SKILL.md
```
Expected: 文件存在，frontmatter 正确

- [ ] **Step 11.4: Commit（skill 不在项目仓库里，在 ~/.claude，单独不提交或按用户 .claude git 习惯处理）**

如果用户 `~/.claude` 是 git 管理的，提交到那边；否则留在本地即可。检查：
```bash
cd <你的用户目录>/.claude && git rev-parse --is-inside-work-tree 2>/dev/null && echo "is_git" || echo "not_git"
```

---

## Task 12: 端到端冒烟测试（人工）

**Files:** N/A（运行时验证）

- [ ] **Step 12.1: 本地跑一次 `push.py` 打向运维群**

```bash
cd <项目路径>/design-team-ai-daily
source .venv/bin/activate
export LARK_WEBHOOK_URL="<运维群 webhook>"        # 故意指向运维群，别骚扰设计团队
export LARK_WEBHOOK_SECRET="<运维群 secret>"
export LARK_OPS_WEBHOOK_URL="<运维群 webhook>"
export LARK_OPS_WEBHOOK_SECRET="<运维群 secret>"
# 清空 state 保证本次会推
python -c "import json; open('state.json','w').write(json.dumps({'last_pushed_date':None,'consecutive_failures':0}))"
python push.py
```
Expected stdout: `[ok] pushed 2026-04-27` 或 `[skip] juya not updated yet`（若 juya 今天还没发）

Expected 运维群：收到卡片或什么都没收到（skip 情况）

- [ ] **Step 12.2: 恢复 state.json**

```bash
python -c "import json; open('state.json','w').write(json.dumps({'last_pushed_date':None,'consecutive_failures':0}))"
git checkout state.json  # 若有 commit
```

- [ ] **Step 12.3: 在 GitHub Actions 手动触发一次**

```bash
gh workflow run daily-ai-news-push.yml
gh run watch
```
Expected: 运行成功，运维群收到卡片（如果 today 有新日报且之前未推）

- [ ] **Step 12.4: 在设计群**（由用户确认，Claude 不自动推）

告知用户："准备好把正式 webhook 替换为**设计团队群**吗？确认后我用 `gh secret set LARK_WEBHOOK_URL` 和 `LARK_WEBHOOK_SECRET` 更新，下一个 cron tick 就会推到正式群。"

**不要未经确认就切到正式群**（红线：未经确认的公开发布）。

- [ ] **Step 12.5: 最终 commit（如有 state 变更）**

```bash
cd <项目路径>/design-team-ai-daily
git status
# 如 state.json 变了，commit；否则跳过
```

---

## 自审结果

**Spec 覆盖检查**：
- §1 目标 → Task 8 (main flow)
- §2 非目标 → 未实现项自然不出现 ✓
- §3 决策记录 → 全部通过 Task 1-9 落地 ✓
- §4 架构 → Task 9 (workflow) + Task 8 (push.py)
- §5 仓库结构 → Task 1/8/9/10 逐一建立
- §6 行为规则 → Task 8 test_push.py 覆盖所有分支
- §7 卡片样式 → Task 6
- §7.2 降级 → Task 8 + `test_degraded_parse_falls_back_to_text`
- §8 密钥 → Task 9 secrets + Task 10 README + Task 11 skill
- §9 skill 角色 → Task 11
- §10 成功指标 → Task 12 冒烟 + 上线后观察
- §11 未来扩展 → 明确不做 ✓
- §12 风险 → README §故障排查 + Task 8 降级逻辑

**占位符扫描**：无 TBD / TODO / 占位。

**类型一致性**：`STATE_PATH`、`state.json` schema、`entry` dict keys（title/link/published_dt/content_html/description）在所有任务间一致。
