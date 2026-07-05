"""卡片渲染共用工具函数。

三个卡片渲染模块（lark_card / aihot_card / builders_card）共享的安全工具：
- _s: 安全字符串转换
- _safe_url: URL scheme 白名单校验
- _escape_md: markdown 特殊字符转义
- _truncate: 超长截断 + 省略号
"""
from typing import Any


def _s(v: Any) -> str:
    """把任意值安全转成字符串；None / 空串统一落在默认值。"""
    if v is None:
        return ""
    if isinstance(v, str):
        return v
    try:
        return str(v)
    except Exception:
        return ""


def _safe_url(url: str) -> str:
    """校验 URL scheme，只允许 http/https，防止 javascript:/data: 注入。"""
    url = _s(url).strip()
    if url.startswith(("http://", "https://")):
        return url
    return "#"


def _escape_md(text: str) -> str:
    """转义飞书 lark_md 特殊字符，防止排版劫持。

    转义字符：[]()*`>~-
    - []() 防止链接劫持
    - * 防止粗体 **text**
    - ` 防止代码块
    - > 防止引用块
    - ~ 防止删除线 ~~text~~
    - _ 防止斜体 _text_
    """
    s = _s(text)
    for ch in ("[", "]", "(", ")", "*", "`", ">", "~", "_"):
        s = s.replace(ch, "\\" + ch)
    return s


def _truncate(text: str, limit: int) -> str:
    """超长截断并加省略号，截断后总长度 = limit（含省略号）。"""
    text = _s(text)
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"
