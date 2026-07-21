import re
from typing import Any, Dict, List, Mapping, Optional

from bs4 import BeautifulSoup

from card_utils import _escape_md, _safe_url, _s


JUYA_HEADER_TEMPLATE = "orange"

# juya 已知分类名，测试里用来遍历断言
CATEGORY_COLORS = (
    "要闻", "大模型与基础模型", "应用与产品", "研究与论文",
    "政策与行业动态", "开源与工程", "硬件与芯片", "产品发布",
    "安全与对齐", "人物与公司",
)


def _extract_overview_groups(html: str) -> List[Dict[str, Any]]:
    """从 juya HTML 摘要区抽出「分类 → 条目列表」的结构。"""
    if not html or not isinstance(html, str):
        return []

    soup = BeautifulSoup(html, "html.parser")
    groups: List[Dict[str, Any]] = []
    current: Optional[Dict[str, Any]] = None

    for node in soup.find_all(["h2", "h3", "p", "li"]):
        try:
            text = node.get_text(strip=True) or ""
        except (TypeError, AttributeError):
            continue

        if node.name == "h2":
            # <h2> 是详情区标题；"概览"这个 wrapper 跳过，其他 <h2> 终止
            if text == "概览":
                continue
            break

        if node.name == "h3" and text:
            if current and current["items"]:
                groups.append(current)
            current = {"category": text, "items": []}
            continue

        if current is not None and node.name in ("li", "p"):
            # 找"↗"跳转链；没找到则回退到最后一个 <a>
            all_links = node.find_all("a")
            target_a = next((a for a in all_links if (a.get_text(strip=True) or "") == "↗"), None)
            if target_a is None and all_links:
                target_a = all_links[-1]

            href = _s(target_a.get("href")) if target_a is not None else ""
            if not href:
                continue

            raw = re.sub(r"\s*#\d+\s*$", "", text).strip()
            cleaned = raw.rstrip("↗").strip()
            if cleaned.startswith(("http://", "https://")) or not cleaned:
                continue
            if len(cleaned) >= 200:
                print(f"[warn] 标题过长：{len(cleaned)} 字，截断", flush=True)
                cleaned = cleaned[:197] + "..."

            current["items"].append({"title": cleaned, "url": href})

    if current and current["items"]:
        groups.append(current)
    return groups


def _extract_video_links(description: str, content_html: str) -> Dict[str, Optional[str]]:
    urls: Dict[str, Optional[str]] = {"bilibili": None, "youtube": None}
    combined = f"{_s(description)}\n{_s(content_html)}"
    if not combined.strip():
        return urls
    b = re.search(r"https?://[^\s\"<>]*bilibili\.com/[^\s\"<>]+", combined)
    y = re.search(r"https?://[^\s\"<>]*(?:youtube\.com|youtu\.be)/[^\s\"<>]+", combined)
    if b:
        urls["bilibili"] = b.group(0)
    if y:
        urls["youtube"] = y.group(0)
    return urls


def parse_entry_to_card(entry: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
    """把 juya entry 渲染成飞书卡片。概览区解析不到分组时返回 None。"""
    if not entry or not isinstance(entry, dict):
        return None

    # feedparser 返回的 HTML 在 content[0].value 里，不是 content_html 字段
    content_html = _s(entry.get("content_html"))
    if not content_html:
        # 尝试从 content 列表获取
        content_list = entry.get("content")
        if content_list and isinstance(content_list, (list, tuple)) and len(content_list) > 0:
            first = content_list[0]
            if isinstance(first, dict):
                content_html = _s(first.get("value"))
    
    groups = _extract_overview_groups(content_html) if content_html else []
    if not groups:
        return None

    title = _s(entry.get("title")) or "<untitled>"
    link = _safe_url(entry.get("link"))
    videos = _extract_video_links(_s(entry.get("description")), content_html)

    elements: List[Dict[str, Any]] = []
    for i, g in enumerate(groups):
        if i > 0:
            elements.append({"tag": "hr"})
        md_lines = [f"**{g['category']}**"]
        for item in g["items"]:
            url = _safe_url(item.get("url"))
            md_lines.append(f"• [{_escape_md(item.get('title'))}]({url})")
        elements.append({"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(md_lines)}})

    buttons: List[Dict[str, Any]] = [{
        "tag": "button",
        "text": {"tag": "plain_text", "content": "📖 查看完整日报"},
        "type": "primary",
        "url": link,
    }]
    if videos.get("bilibili"):
        buttons.append({
            "tag": "button",
            "text": {"tag": "plain_text", "content": "🎬 B站"},
            "type": "default",
            "url": _safe_url(videos["bilibili"]),
        })
    elements.append({"tag": "action", "actions": buttons})
    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "资讯由 juya AI 辅助生成，可能存在错误，请以原始信息出处为准。",
        }],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "template": JUYA_HEADER_TEMPLATE,
            "title": {"tag": "plain_text", "content": f"🤖 橘鸦 AI 早报 · {title}"},
        },
        "elements": elements,
    }
