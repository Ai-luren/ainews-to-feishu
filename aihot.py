"""aihot.virxact.com 日报拉取。"""
from datetime import date
from typing import Any, Dict, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

AIHOT_BASE_URL = "https://aihot.virxact.com"
_DAILY_URL = f"{AIHOT_BASE_URL}/api/public/daily"

_UA = "Mozilla/5.0 aihot-skill/0.2.0"
_TIMEOUT = (5, 20)
_MAX_BYTES = 1024 * 1024


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = _UA
    retry = Retry(total=3, backoff_factor=0.5,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(["GET"]))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    return s


def fetch_daily(target_date: Optional[date] = None) -> Optional[Dict[str, Any]]:
    """拉取 aihot 日报。target_date=None 时拉最新一期。

    404 处理策略：
    - 有 target_date 的 404 = 该日期无内容，返回 None（正常状态）
    - 无 target_date 的 404 = API 端点不可用，抛异常（走失败计数）
    """
    url = f"{_DAILY_URL}/{target_date}" if target_date else _DAILY_URL
    with _session() as s:
        resp = s.get(url, timeout=_TIMEOUT)
        if resp.status_code == 404:
            if target_date is not None:
                # 指定日期无内容 — 正常状态
                return None
            # 最新一期都 404 → API 端点异常
            raise RuntimeError(f"aihot API 返回 404（端点可能已变更）: {url}")
        resp.raise_for_status()

    if len(resp.content) > _MAX_BYTES:
        raise RuntimeError(f"响应过大: {len(resp.content)} bytes")

    data = resp.json()
    if not isinstance(data, dict) or "date" not in data or "sections" not in data:
        raise ValueError(f"响应结构异常: {list(data.keys())}")
    return data


def total_items(daily: Dict[str, Any]) -> int:
    if not daily or not daily.get("sections"):
        return 0
    return sum(len(s.get("items", [])) for s in daily["sections"])


def daily_date(daily: Dict[str, Any]) -> Optional[date]:
    d = daily.get("date") if isinstance(daily, dict) else None
    if not d:
        return None
    try:
        return date.fromisoformat(str(d))
    except ValueError:
        return None


def has_content(daily: Optional[Dict[str, Any]]) -> bool:
    return bool(daily) and total_items(daily) > 0
