"""follow-builders 推文 → 飞书卡片渲染（中英双语）。

排版结构与 juya/aihot 卡片一致：
- 每条推文一个 div + hr 分隔
- 底部 action 按钮
- note 声明来源
"""
from typing import Any, Dict, List, Optional

from builders import fetch_daily


def _s(v) -> str:
    """把任意值安全转成字符串。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return str(v)
    except Exception:
        return ""


def _safe_url(url: str) -> str:
    """校验 URL scheme，只允许 http/https。"""
    url = _s(url).strip()
    if url.startswith(("http://", "https://")):
        return url
    return "#"


def _escape_md(text: str) -> str:
    """转义 markdown 特殊字符。"""
    return _s(text).replace("[", "\\[").replace("]", "\\]").replace("(", "\\(").replace(")", "\\)")


def _truncate(text: str, max_len: int = 120) -> str:
    text = _s(text)
    return text[:max_len] + "…" if len(text) > max_len else text


def render_card(daily: dict) -> dict:
    """把 follow-builders 数据渲染成飞书互动卡片 JSON。

    排版与 juya/aihot 一致：div + hr 分段，action 按钮，note 声明。
    """
    tweets = daily.get("tweets", [])
    total_builders = daily.get("total_builders", 0)
    feed_date = daily.get("date")

    date_str = feed_date.strftime("%Y-%m-%d") if feed_date else "今日"
    header_title = f"🌐 AI 大佬动态 · {date_str}"

    elements: List[Dict[str, Any]] = []

    # 概览行
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"**{len(tweets)} 条热门推文 · 来自 {total_builders} 位 AI builder**"},
    })

    # 每条推文一个 div，hr 分隔
    for i, tweet in enumerate(tweets):
        if i > 0:
            elements.append({"tag": "hr"})

        name = _escape_md(tweet.get("name", ""))
        handle = tweet.get("handle", "")
        bio_zh = _escape_md(_truncate(tweet.get("bio_zh", ""), 80))
        bio_en = _escape_md(_truncate(tweet.get("bio", ""), 80))
        text_en = _escape_md(_truncate(tweet.get("text", ""), 200))
        text_zh = _escape_md(_truncate(tweet.get("text_zh", ""), 200))
        url = _safe_url(tweet.get("url"))
        likes = tweet.get("likes", 0)
        retweets = tweet.get("retweets", 0)

        md_lines = [f"**{name}** @{handle}"]

        # 人物简介（中文翻译优先，无翻译则显示英文原文）
        bio_display = bio_zh if bio_zh and bio_zh != bio_en else bio_en
        if bio_display:
            md_lines.append(f"  {bio_display}")

        # 中文翻译
        if text_zh and text_zh != tweet.get("text", ""):
            md_lines.append(f"  🇨🇳 {text_zh}")

        # 英文原文
        md_lines.append(f"  🇺🇸 {text_en}")

        # 互动数据 + 原文链接
        md_lines.append(f"  ❤️ {likes}  🔁 {retweets}  [↗ 原文]({url})")

        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "\n".join(md_lines)},
        })

    # 底部按钮（与 juya/aihot 一致）
    elements.append({
        "tag": "action",
        "actions": [{
            "tag": "button",
            "text": {"tag": "plain_text", "content": "📦 查看 follow-builders"},
            "type": "primary",
            "url": "https://github.com/zarazhangrui/follow-builders",
        }],
    })

    # 底部声明（与 juya/aihot 一致）
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "内容来自 follow-builders，中文由 Google Translate 翻译，可能存在偏差。",
        }],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": header_title},
            "template": "purple",
        },
        "elements": elements,
    }


def build_card_payload(daily: dict) -> dict:
    """构建飞书 webhook 消息体。"""
    return {"msg_type": "interactive", "card": render_card(daily)}


def parse_entry_to_card() -> Optional[dict]:
    """一站式：拉取 + 渲染。失败返回 None。"""
    daily = fetch_daily()
    if not daily or not daily.get("tweets"):
        return None
    return build_card_payload(daily)
