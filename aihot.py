"""aihot.virxact.com 日报拉取与解析。

对应 juya 的 rss.py。结构差异：
- juya: RSS XML → 解析 HTML 内容提取分类 + 条目
- aihot: REST API JSON → 原生就是 sections[] + items[]，无需 HTML 解析

调用者：push.py（主流程）和 aihot_card.py（渲染卡片）。
"""
import json
from datetime import date, datetime
from typing import Any, Dict, List, Optional

import pytz
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BEIJING = pytz.timezone("Asia/Shanghai")

AIHOT_BASE_URL = "https://aihot.virxact.com"
AIHOT_DAILY_ENDPOINT = f"{AIHOT_BASE_URL}/api/public/daily"
AIHOT_DAILIES_ENDPOINT = f"{AIHOT_BASE_URL}/api/public/dailies"

# aihot API 对 User-Agent 敏感，默认 curl UA 会被 403。
# 必须用浏览器 UA，跟 SKILL.md 里保持一致。
_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 "
    "Safari/537.36 aihot-skill/0.2.0"
)

_HTTP_TIMEOUT = (5, 20)  # connect, read
_MAX_RESPONSE_BYTES = 1 * 1024 * 1024  # 1MB — 日报 json 约 20-50KB


def _session_with_retries() -> requests.Session:
    """对 5xx / 连接错误做 3 次指数退避重试。"""
    s = requests.Session()
    s.headers["User-Agent"] = _UA
    retry = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset(["GET", "HEAD"]),
        raise_on_status=False,
    )
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def fetch_daily(target_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """拉取 aihot 日报。

    - target_date=None: 拉最新一期（/api/public/daily）
    - target_date=date: 拉指定日期（/api/public/daily/YYYY-MM-DD）
    返回解析后的 dict，结构见 aihot SKILL.md 的 "返回数据形态"。
    找不到对应日期条目 → 返回 None。
    """
    if target_date is not None:
        url = f"{AIHOT_DAILY_ENDPOINT}/{target_date.isoformat()}"
    else:
        url = AIHOT_DAILY_ENDPOINT

    with _session_with_retries() as s:
        resp = s.get(url, timeout=_HTTP_TIMEOUT)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()

    if len(resp.content) > _MAX_RESPONSE_BYTES:
        raise RuntimeError(
            f"aihot daily 响应过大（{len(resp.content)} bytes，"
            f"上限 {_MAX_RESPONSE_BYTES}）"
        )

    data = resp.json()
    # 基本结构完整性检查
    if not isinstance(data, dict):
        raise ValueError(f"aihot daily 响应顶层不是 dict: {type(data).__name__}")
    if "date" not in data or "sections" not in data:
        raise ValueError(
            f"aihot daily 缺少关键字段: {list(data.keys())}"
        )
    if not isinstance(data["sections"], list):
        raise ValueError(
            f"aihot daily sections 不是 list: {type(data['sections']).__name__}"
        )
    return data


def total_items(daily: Dict[str, Any]) -> int:
    """统计日报里的总条目数，用于判断"日报是否空"。"""
    if not daily or not daily.get("sections"):
        return 0
    return sum(len(s.get("items", [])) for s in daily["sections"])


def daily_date(daily: Dict[str, Any]) -> Optional[date]:
    """从日报响应里拿日期字段。"""
    d = daily.get("date") if isinstance(daily, dict) else None
    if not d:
        return None
    try:
        return date.fromisoformat(str(d))
    except ValueError:
        return None


def has_content(daily: Optional[Dict[str, Any]]) -> bool:
    """这个日报有没有实际内容。"""
    return bool(daily) and total_items(daily) > 0


# —— 给 tests/ 或者调试用的便捷函数 ——


def get_effective_base_url() -> str:
    return AIHOT_BASE_URL
