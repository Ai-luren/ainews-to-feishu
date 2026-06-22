import calendar
import os
import re
from datetime import date, datetime
from typing import List, Optional

import feedparser
import pytz
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BEIJING = pytz.timezone("Asia/Shanghai")

_RSS_URL_DEFAULT = "https://daily.juya.uk/rss.xml"
# 已知已失效/废弃的 RSS 源地址 — 一旦配置到这些地址就强制回退到默认，
# 避免像 imjuya.github.io 那种已失效却没人发现的"静默 404"。
_DEAD_RSS_URLS = {
    "https://imjuya.github.io/juya-ai-daily/rss.xml",
    "http://imjuya.github.io/juya-ai-daily/rss.xml",
}
RSS_URL = os.environ.get("RSS_URL") or _RSS_URL_DEFAULT
if RSS_URL.rstrip("/") in _DEAD_RSS_URLS:
    print(f"[warn] RSS_URL={RSS_URL} 已废弃，回退到 {_RSS_URL_DEFAULT}", flush=True)
    RSS_URL = _RSS_URL_DEFAULT

MAX_RSS_BYTES = 5 * 1024 * 1024      # 5MB — 正常一期 <2MB，超了多半被劫持
USER_AGENT = "design-team-ai-daily/1.0 (+https://github.com/ainews-to-feishu)"
_HTTP_TIMEOUT = (5, 20)               # connect, read


def _session_with_retries() -> requests.Session:
    """对 5xx / 连接错误做 3 次指数退避重试（GET 专用）。"""
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(
        total=3, backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def fetch_rss(url: str = RSS_URL, timeout=_HTTP_TIMEOUT) -> bytes:
    """拉取 RSS feed 的原始 bytes。超限直接抛错，避免 feedparser 吃内存。"""
    if not url or not isinstance(url, str):
        raise ValueError(f"invalid rss url: {url!r}")
    with _session_with_retries() as s:
        resp = s.get(url, timeout=timeout)
    resp.raise_for_status()
    if len(resp.content) > MAX_RSS_BYTES:
        raise RuntimeError(f"RSS 过大（{len(resp.content)} bytes，上限 {MAX_RSS_BYTES}）")
    return resp.content


def parse_feed(xml) -> List[dict]:
    """解析 RSS/Atom 为 entries 列表。published 为 None 的畸形条目直接跳过。"""
    if not xml:
        return []
    feed = feedparser.parse(xml)
    entries: List[dict] = []
    for e in feed.entries:
        if not getattr(e, "published_parsed", None):
            continue
        try:
            pub = datetime.fromtimestamp(calendar.timegm(e.published_parsed), tz=pytz.utc)
        except (OverflowError, ValueError):
            continue
        # 只用 content:encoded（feedparser 的 content 字段）作为 HTML 正文。
        # 不回退到 description —— 那是纯文本，没有 HTML 标签，
        # 会导致 _extract_overview_groups 解析失败 → 降级模式。
        content_html = ""
        if "content" in e and e.content:
            content_html = e.content[0].value or ""
        entries.append({
            "title": getattr(e, "title", "<untitled>") or "<untitled>",
            "link": getattr(e, "link", "") or "",
            "published_dt": pub,
            "content_html": content_html,
            "description": getattr(e, "description", "") or "",
        })
    entries.sort(key=lambda x: x["published_dt"], reverse=True)
    return entries


def _title_to_date(title: str) -> Optional[date]:
    """从标题里提取 YYYY-MM-DD；无法解析时返回 None。"""
    if not title:
        return None
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", title)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    return None


def extract_today_entry(xml, today: Optional[date] = None) -> Optional[dict]:
    """返回对应"今天"的条目。

    匹配策略：先用 published 的北京时区日期匹配；如果没命中，
    再回退到标题里的日期（juya 偶尔会在 UTC 下午发当天的日报，
    按 published 算会错分到第二天）。
    """
    if today is None:
        today = datetime.now(BEIJING).date()
    entries = parse_feed(xml)
    for e in entries:
        if e["published_dt"].astimezone(BEIJING).date() == today:
            return e
    for e in entries:
        if _title_to_date(e["title"]) == today:
            return e
    return None


def get_effective_rss_url() -> str:
    """返回实际生效的 RSS URL（调试用）。"""
    return RSS_URL
