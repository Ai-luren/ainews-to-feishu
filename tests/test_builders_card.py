"""builders_card.render_card 单元测试。

测试覆盖：
- 基本渲染（header、elements 结构）
- bio 中英双语回退
- 推文文本中英双语
- URL 安全校验
- markdown 转义
- 截断行为
- 空数据边界
"""
from datetime import date

from builders_card import render_card


def _make_tweet(**overrides):
    """构造测试用推文数据。"""
    base = {
        "name": "Test Person",
        "handle": "testhandle",
        "bio": "AI researcher at TestLab",
        "bio_zh": "TestLab 的 AI 研究员",
        "text": "Just published a new paper on transformers!",
        "text_zh": "刚发表了一篇关于 Transformer 的新论文！",
        "url": "https://x.com/testhandle/status/123",
        "likes": 100,
        "retweets": 20,
        "engagement": 120,
    }
    base.update(overrides)
    return base


def _make_daily(tweets=None, **overrides):
    base = {
        "tweets": tweets if tweets is not None else [_make_tweet()],
        "total_builders": 1,
        "date": date(2026, 6, 24),
    }
    base.update(overrides)
    return base


# ———————————— 基本结构 ———————————— #


def test_render_card_basic_structure():
    """测试卡片基本结构：header + elements。"""
    card = render_card(_make_daily())
    assert card["header"]["template"] == "purple"
    assert "AI 大佬动态" in card["header"]["title"]["content"]
    assert card["config"]["wide_screen_mode"] is True
    assert isinstance(card["elements"], list)
    assert len(card["elements"]) >= 3  # 概览 + 推文 + 按钮 + note


def test_render_card_header_date():
    """测试 header 包含日期。"""
    daily = _make_daily(date=date(2026, 6, 24))
    card = render_card(daily)
    assert "2026-06-24" in card["header"]["title"]["content"]


def test_render_card_overview_line():
    """测试概览行显示推文数和 builder 数。"""
    tweets = [_make_tweet(), _make_tweet(name="Person 2", handle="p2")]
    daily = _make_daily(tweets=tweets, total_builders=2)
    card = render_card(daily)
    overview = card["elements"][0]["text"]["content"]
    assert "2 条热门推文" in overview
    assert "2 位 AI builder" in overview


# ———————————— 推文渲染 ———————————— #


def test_render_card_tweet_bilingual():
    """测试推文中英双语显示。"""
    card = render_card(_make_daily())
    # 找到推文 div（概览之后第一个 div）
    tweet_div = card["elements"][1]["text"]["content"]
    assert "Test Person" in tweet_div
    assert "@testhandle" in tweet_div
    assert "🇨🇳" in tweet_div
    assert "刚发表了一篇" in tweet_div
    assert "🇺🇸" in tweet_div
    assert "Just published" in tweet_div


def test_render_card_bio_chinese_preferred():
    """测试 bio 优先显示中文翻译。"""
    card = render_card(_make_daily())
    tweet_div = card["elements"][1]["text"]["content"]
    assert "TestLab 的 AI 研究员" in tweet_div


def test_render_card_bio_fallback_to_english():
    """测试 bio_zh 缺失时回退到英文。"""
    tweet = _make_tweet(bio_zh="")
    card = render_card(_make_daily(tweets=[tweet]))
    tweet_div = card["elements"][1]["text"]["content"]
    assert "AI researcher at TestLab" in tweet_div


def test_render_card_engagement_stats():
    """测试互动数据显示。"""
    card = render_card(_make_daily())
    tweet_div = card["elements"][1]["text"]["content"]
    assert "❤️ 100" in tweet_div
    assert "🔁 20" in tweet_div


def test_render_card_original_link():
    """测试原文链接。"""
    card = render_card(_make_daily())
    tweet_div = card["elements"][1]["text"]["content"]
    assert "https://x.com/testhandle/status/123" in tweet_div


# ———————————— 安全 ———————————— #


def test_render_card_javascript_url_blocked():
    """测试 javascript: URL 被替换为 #。"""
    tweet = _make_tweet(url="javascript:alert(1)")
    card = render_card(_make_daily(tweets=[tweet]))
    tweet_div = card["elements"][1]["text"]["content"]
    assert "javascript:" not in tweet_div
    # 严格断言：原始恶意 payload 必须完全消失，而不是只判断 "#" 出现
    # （"#" 在卡片里本就会出现，弱断言会漏掉 payload 残留）
    assert "javascript:alert(1)" not in tweet_div


def test_render_card_markdown_injection_escaped():
    """测试推文文本中的 markdown 特殊字符被转义。"""
    tweet = _make_tweet(text="Hello [evil](http://evil.com) world")
    card = render_card(_make_daily(tweets=[tweet]))
    tweet_div = card["elements"][1]["text"]["content"]
    assert "\\[evil\\]" in tweet_div


def test_render_card_handle_escaped():
    """测试 handle 中的特殊字符被转义。"""
    tweet = _make_tweet(handle="test[handle]")
    card = render_card(_make_daily(tweets=[tweet]))
    tweet_div = card["elements"][1]["text"]["content"]
    assert "\\[handle\\]" in tweet_div


# ———————————— 截断 ———————————— #


def test_render_card_long_text_truncated():
    """测试超长推文被截断。"""
    tweet = _make_tweet(text="A" * 300)
    card = render_card(_make_daily(tweets=[tweet]))
    tweet_div = card["elements"][1]["text"]["content"]
    assert "…" in tweet_div


def test_render_card_long_bio_truncated():
    """测试超长 bio 被截断。"""
    tweet = _make_tweet(bio="B" * 200, bio_zh="")
    card = render_card(_make_daily(tweets=[tweet]))
    tweet_div = card["elements"][1]["text"]["content"]
    assert "…" in tweet_div


# ———————————— 多推文 ———————————— #


def test_render_card_multiple_tweets_with_hr():
    """测试多条推文之间有 hr 分隔。"""
    tweets = [_make_tweet(), _make_tweet(name="Person 2", handle="p2")]
    card = render_card(_make_daily(tweets=tweets))
    # 找到所有 hr 元素
    hrs = [e for e in card["elements"] if e.get("tag") == "hr"]
    assert len(hrs) == 1  # 两条推文之间 1 个 hr


def test_render_card_single_tweet_no_hr():
    """测试单条推文时没有 hr。"""
    card = render_card(_make_daily())
    hrs = [e for e in card["elements"] if e.get("tag") == "hr"]
    assert len(hrs) == 0


# ———————————— 底部元素 ———————————— #


def test_render_card_has_button():
    """测试底部有 action 按钮。"""
    card = render_card(_make_daily())
    actions = [e for e in card["elements"] if e.get("tag") == "action"]
    assert len(actions) == 1
    button = actions[0]["actions"][0]
    assert button["tag"] == "button"
    assert button["type"] == "primary"
    assert "follow-builders" in button["url"]


def test_render_card_has_note():
    """测试底部有 note 声明。"""
    card = render_card(_make_daily())
    notes = [e for e in card["elements"] if e.get("tag") == "note"]
    assert len(notes) == 1
    note_text = notes[0]["elements"][0]["content"]
    assert "Google Translate" in note_text


# ———————————— 边界 ———————————— #


def test_render_card_empty_tweets():
    """测试空推文列表。"""
    daily = _make_daily(tweets=[], total_builders=0)
    card = render_card(daily)
    assert card["header"]["template"] == "purple"
    overview = card["elements"][0]["text"]["content"]
    assert "0 条热门推文" in overview


def test_render_card_no_bio():
    """测试无 bio 时不崩溃。"""
    tweet = _make_tweet(bio="", bio_zh="")
    card = render_card(_make_daily(tweets=[tweet]))
    tweet_div = card["elements"][1]["text"]["content"]
    assert "Test Person" in tweet_div


def test_render_card_no_text_zh():
    """测试无中文翻译时只显示英文。"""
    tweet = _make_tweet(text_zh="")
    card = render_card(_make_daily(tweets=[tweet]))
    tweet_div = card["elements"][1]["text"]["content"]
    assert "🇺🇸" in tweet_div
    assert "Just published" in tweet_div
