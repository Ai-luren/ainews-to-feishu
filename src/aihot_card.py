"""把 aihot daily 渲染成飞书卡片。

结构差异（跟 lark_card.py 一样的区别：
- juya: RSS 的 HTML 中需要解析 HTML → sections 提取
- aihot: 直接是 JSON sections[] → 不用 HTML 解析
- aihot 还有 lead（导语）+ flashes（快讯）
- 每条条目有 title/summary/sourceName/sourceUrl 四个字段
"""
from typing import Any, Dict, List, Mapping, Optional

from card_utils import _escape_md, _safe_url, _s, _truncate


# aihot section label → 飞书卡片 header 颜色映射。
# 跟 juya 不同：aihot 的 section label 是中文且固定。
_AIHOT_HEADER_TEMPLATE: Dict[str, str] = {
    "模型发布/更新": "blue",
    "产品发布/更新": "turquoise",
    "行业动态": "yellow",
    "论文研究": "purple",
    "技巧与观点": "green",
}
_DEFAULT_HEADER_TEMPLATE = "purple"


def parse_daily_to_card(daily: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """把 aihot daily（/api/public/daily 返回值）渲染为飞书卡片。

    无条目（sections 为空或所有 section 都空）时返回 None
    None，给调用方降级到纯文本推送。
    """
    if not daily or not isinstance(daily, dict):
        return None

    sections = daily.get("sections") or []
    if not isinstance(sections, list):
        return None

    # 扁平汇总
    flat: List[Dict[str, Any]] = []
    for section in sections:
        label = _s(section.get("label")) or "未分类"
        items = section.get("items") or []
        if not items:
            continue
        clean = []
        for item in items:
            title = _s(item.get("title"))
            url = _s(item.get("sourceUrl"))
            summary = _s(item.get("summary"))
            source = _s(item.get("sourceName"))
            if not title or not url:
                continue
            clean.append({"title": title, "url": url, "summary": summary, "source": source})
        if clean:
            flat.append({"category": label, "items": clean})
    if not flat:
        return None

    date_str = _s(daily.get("date")) or "<untitled>"

    # lead 导语
    lead = daily.get("lead") or {}
    lead_title = _s(lead.get("title")) or ""
    lead_paragraph = _s(lead.get("leadParagraph")) or ""

    # flashes 快讯
    flashes = daily.get("flashes") or []
    if not isinstance(flashes, list):
        flashes = []

    elements: List[Dict[str, Any]] = []

    # 导语
    if lead_title or lead_paragraph:
        lead_md = []
        if lead_title:
            lead_md.append(f"**{_escape_md(_truncate(lead_title, 150))}**")
        if lead_paragraph:
            lead_md.append(_escape_md(_truncate(lead_paragraph, 300)))
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(lead_md)}})

    # 主体 sections
    for group in flat:
        if elements:  # 不是第一个 group 之前加 hr 分隔
            elements.append({"tag": "hr"})
        md_lines = [f"**{_escape_md(group['category'])}**"]
        for item in group["items"]:
            line = f"• [{_escape_md(_truncate(item['title'], 100))}]({_safe_url(item['url'])})"
            md_lines.append(line)
            if item.get("summary"):
                md_lines.append(f"  {_escape_md(_truncate(item['summary'], 120))}")
            if item.get("source"):
                md_lines.append(f"  — {_escape_md(item['source'])}")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(md_lines)}})

    # 快讯（如有）
    if flashes:
        if elements:
            elements.append({"tag": "hr"})
        flash_lines = ["**快讯**"]
        for f in flashes[:10]:  # 最多 10 条
            flash_title = _s(f.get("title"))
            flash_url = _s(f.get("sourceUrl"))
            if not flash_title or not flash_url:
                continue
            flash_lines.append(f"• [{_escape_md(_truncate(flash_title, 150))}]({_safe_url(flash_url)})")
        if len(flash_lines) > 1:
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(flash_lines)}})

    # 底部按钮
    buttons: List[Dict[str, Any]] = [{
        "tag": "button",
        "text": {"tag": "plain_text", "content": "🔥 查看完整日报"},
        "type": "primary",
        "url": "https://aihot.virxact.com/",
    }]

    elements.append({"tag": "action", "actions": buttons})
    elements.append({"tag": "note", "elements": [{
        "tag": "plain_text",
        "content": "资讯由 AI HOT 整理，摘要由 AI 生成，可能存在错误，请以原始信息出处为准。",
    }]})

    header_template = _AIHOT_HEADER_TEMPLATE.get(
        (flat[0].get("category", "") or ""), _DEFAULT_HEADER_TEMPLATE
    )
    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": header_template,
            "title": {"tag": "plain_text", "content": f"🔥 AI HOT 日报 · {date_str}"},
        },
        "elements": elements,
    }
