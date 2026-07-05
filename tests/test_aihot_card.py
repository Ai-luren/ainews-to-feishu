"""aihot_card.parse_daily_to_card 单元测试。

测试覆盖：
- 基本渲染（header、elements 结构）
- section 分组
- 导语渲染
- 快讯渲染
- URL 安全校验
- markdown 转义
- 截断行为
- 空数据边界
"""
from datetime import date

from aihot_card import parse_daily_to_card


def _make_item(**overrides):
    base = {
        "title": "Test News Item",
        "sourceUrl": "https://example.com/news/1",
        "summary": "This is a test summary",
        "sourceName": "TestSource",
    }
    base.update(overrides)
    return base


def _make_daily(**overrides):
    base = {
        "date": "2026-06-24",
        "sections": [
            {"label": "大模型", "items": [_make_item()]},
        ],
        "flashes": [],
        "lead": None,
    }
    base.update(overrides)
    return base


# ———————————— 基本结构 ———————————— #


def test_parse_daily_basic_structure():
    """测试卡片基本结构。"""
    card = parse_daily_to_card(_make_daily())
    assert card is not None
    assert card["config"]["wide_screen_mode"] is True
    assert isinstance(card["elements"], list)
    assert len(card["elements"]) >= 1


def test_parse_daily_header_date():
    """测试 header 包含日期。"""
    card = parse_daily_to_card(_make_daily(date="2026-06-24"))
    assert card is not None
    assert "2026-06-24" in card["header"]["title"]["content"]


def test_parse_daily_header_template():
    """测试 header 颜色模板。

    _make_daily() 的首个 section label 是 "大模型"，而 aihot_card 的
    _AIHOT_HEADER_TEMPLATE 里没有 "大模型" 这一键（只有"模型发布/更新"等），
    因此走 _DEFAULT_HEADER_TEMPLATE = "purple" 兜底。这里改成精确值断言，
    避免宽泛集合断言掩盖映射逻辑回归。
    """
    card = parse_daily_to_card(_make_daily())
    assert card is not None
    assert card["header"]["template"] == "purple"


# ———————————— Section 渲染 ———————————— #


def test_parse_daily_section_label():
    """测试 section 标签显示。"""
    card = parse_daily_to_card(_make_daily())
    assert card is not None
    all_text = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e.get("tag") == "div"
    )
    assert "大模型" in all_text


def test_parse_daily_item_title():
    """测试条目标题显示。"""
    card = parse_daily_to_card(_make_daily())
    assert card is not None
    all_text = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e.get("tag") == "div"
    )
    assert "Test News Item" in all_text


def test_parse_daily_item_summary():
    """测试条目摘要显示。"""
    card = parse_daily_to_card(_make_daily())
    assert card is not None
    all_text = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e.get("tag") == "div"
    )
    assert "test summary" in all_text


def test_parse_daily_item_source():
    """测试条目来源显示。"""
    card = parse_daily_to_card(_make_daily())
    assert card is not None
    all_text = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e.get("tag") == "div"
    )
    assert "TestSource" in all_text


# ———————————— 导语 ———————————— #


def test_parse_daily_lead_title():
    """测试导语标题显示。"""
    daily = _make_daily(lead={"title": "今日导语", "leadParagraph": "这是导语内容"})
    card = parse_daily_to_card(daily)
    assert card is not None
    all_text = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e.get("tag") == "div"
    )
    assert "今日导语" in all_text
    assert "这是导语内容" in all_text


def test_parse_daily_no_lead():
    """测试无导语时不崩溃。"""
    card = parse_daily_to_card(_make_daily(lead=None))
    assert card is not None


# ———————————— 快讯 ———————————— #


def test_parse_daily_flash():
    """测试快讯渲染。"""
    daily = _make_daily(flashes=[
        {"title": "快讯标题", "sourceUrl": "https://example.com/flash/1"},
    ])
    card = parse_daily_to_card(daily)
    assert card is not None
    all_text = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e.get("tag") == "div"
    )
    assert "快讯标题" in all_text
    assert "https://example.com/flash/1" in all_text


def test_parse_daily_flash_url_safe():
    """测试快讯 URL 安全校验。"""
    daily = _make_daily(flashes=[
        {"title": "快讯", "sourceUrl": "javascript:alert(1)"},
    ])
    card = parse_daily_to_card(daily)
    assert card is not None
    all_text = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e.get("tag") == "div"
    )
    assert "javascript:" not in all_text


# ———————————— 安全 ———————————— #


def test_parse_daily_javascript_url_blocked():
    """测试 javascript: URL 被替换为 #。"""
    daily = _make_daily(sections=[
        {"label": "测试", "items": [_make_item(sourceUrl="javascript:alert(1)")]},
    ])
    card = parse_daily_to_card(daily)
    assert card is not None
    all_text = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e.get("tag") == "div"
    )
    assert "javascript:" not in all_text


def test_parse_daily_markdown_injection_escaped():
    """测试标题中的 markdown 特殊字符被转义。"""
    daily = _make_daily(sections=[
        {"label": "测试", "items": [_make_item(title="Hello [evil](http://evil.com)")]},
    ])
    card = parse_daily_to_card(daily)
    assert card is not None
    all_text = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e.get("tag") == "div"
    )
    assert "\\[evil\\]" in all_text


# ———————————— 截断 ———————————— #


def test_parse_daily_long_title_truncated():
    """测试超长标题被截断。"""
    daily = _make_daily(sections=[
        {"label": "测试", "items": [_make_item(title="A" * 200)]},
    ])
    card = parse_daily_to_card(daily)
    assert card is not None
    all_text = " ".join(
        e.get("text", {}).get("content", "")
        for e in card["elements"]
        if e.get("tag") == "div"
    )
    assert "…" in all_text


# ———————————— 底部元素 ———————————— #


def test_parse_daily_has_button():
    """测试底部有 action 按钮。"""
    card = parse_daily_to_card(_make_daily())
    assert card is not None
    actions = [e for e in card["elements"] if e.get("tag") == "action"]
    assert len(actions) == 1


def test_parse_daily_has_note():
    """测试底部有 note 声明。"""
    card = parse_daily_to_card(_make_daily())
    assert card is not None
    notes = [e for e in card["elements"] if e.get("tag") == "note"]
    assert len(notes) == 1


# ———————————— 边界 ———————————— #


def test_parse_daily_empty_sections():
    """测试空 sections 返回 None（无内容可渲染）。"""
    assert parse_daily_to_card(_make_daily(sections=[])) is None


def test_parse_daily_none_input():
    """测试 None 输入返回 None。"""
    assert parse_daily_to_card(None) is None


def test_parse_daily_empty_dict():
    """测试空 dict 输入返回 None（无 sections）。"""
    assert parse_daily_to_card({}) is None
