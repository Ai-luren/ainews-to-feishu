"""follow-builders 推文 → 飞书卡片渲染（中英双语）。

排版结构与 juya/aihot 卡片一致：
- 每条推文一个 div + hr 分隔
- 底部 action 按钮
- note 声明来源
"""
from typing import Any, Dict, List

from card_utils import _escape_md, _safe_url, _truncate


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
        handle = _escape_md(tweet.get("handle", ""))
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

        # 中文翻译（比较 raw 版本决定是否显示，避免 escape 后的误判）
        raw_zh = tweet.get("text_zh", "")
        raw_en = tweet.get("text", "")
        if raw_zh and raw_zh != raw_en:
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
