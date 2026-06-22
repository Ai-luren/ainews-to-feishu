"""follow-builders X/Twitter feed 抓取 + Google 翻译。

从 follow-builders 仓库拉取每日 AI 大佬推文 feed，
按互动量排序取 Top N，翻译成中文，返回结构化数据。
"""
import logging
from datetime import date, datetime
from typing import List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

FEED_URL = (
    "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-x.json"
)
USER_AGENT = "ainews-to-feishu/1.0 (+https://github.com/Ai-luren/ainews-to-feishu)"
MAX_TWEETS = 10  # 只取互动量最高的 10 条

_log = logging.getLogger(__name__)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    retry = Retry(total=3, backoff_factor=0.5,
                  status_forcelist=(429, 500, 502, 503, 504),
                  allowed_methods=frozenset(["GET"]))
    s.mount("https://", HTTPAdapter(max_retries=retry))
    s.mount("http://", HTTPAdapter(max_retries=retry))
    return s


def _translate(text: str) -> str:
    """用 Google Translate 免费接口翻译英文→中文。失败时返回原文。"""
    if not text or not text.strip():
        return text
    # Google Translate 免费端点（不需要 API key）
    url = "https://translate.googleapis.com/translate_a/single"
    params = {
        "client": "gtx",
        "sl": "en",
        "tl": "zh-CN",
        "dt": "t",
        "q": text[:4800],  # 限制长度
    }
    try:
        resp = requests.get(url, params=params, timeout=(5, 15),
                            headers={"User-Agent": USER_AGENT})
        if resp.status_code != 200:
            return text
        data = resp.json()
        # Google Translate 返回嵌套数组，翻译结果在 [0][i][0]
        translated = "".join(part[0] for part in data[0] if part[0])
        return translated or text
    except Exception:
        return text


def _batch_translate(texts: List[str]) -> List[str]:
    """批量翻译，逐条调用（Google 免费接口不支持批量）。"""
    return [_translate(t) for t in texts]


def fetch_feed() -> dict:
    """拉取 follow-builders X/Twitter feed JSON。"""
    s = _session()
    resp = s.get(FEED_URL, timeout=(5, 30))
    resp.raise_for_status()
    return resp.json()


def has_content(feed_data: dict) -> bool:
    """检查 feed 是否有推文内容。"""
    builders = feed_data.get("x", [])
    if not builders:
        return False
    return any(b.get("tweets") for b in builders)


def _parse_date(generated_at: str) -> Optional[date]:
    """解析 feed 的 generatedAt 时间戳。"""
    if not generated_at:
        return None
    try:
        # 格式: 2026-06-22T08:29:37.749Z
        return datetime.fromisoformat(
            generated_at.replace("Z", "+00:00")
        ).date()
    except (ValueError, TypeError):
        return None


def get_top_tweets(feed_data: dict, limit: int = MAX_TWEETS) -> list:
    """按互动量（likes + retweets）排序，取 Top N 推文。"""
    all_tweets = []
    for builder in feed_data.get("x", []):
        name = builder.get("name", "")
        handle = builder.get("handle", "")
        bio = builder.get("bio", "")
        for tweet in builder.get("tweets", []):
            engagement = tweet.get("likes", 0) + tweet.get("retweets", 0)
            all_tweets.append({
                "name": name,
                "handle": handle,
                "bio": bio,
                "text": tweet.get("text", ""),
                "url": tweet.get("url", ""),
                "likes": tweet.get("likes", 0),
                "retweets": tweet.get("retweets", 0),
                "engagement": engagement,
            })
    all_tweets.sort(key=lambda x: x["engagement"], reverse=True)
    return all_tweets[:limit]


def fetch_daily() -> Optional[dict]:
    """拉取 feed + 翻译，返回结构化数据。失败返回 None。"""
    data = fetch_feed()
    if not has_content(data):
        return None

    tweets = get_top_tweets(data)

    # 批量翻译推文文本
    texts_zh = _batch_translate([t["text"] for t in tweets])
    for i, tweet in enumerate(tweets):
        tweet["text_zh"] = texts_zh[i]

    # 翻译 bio（按 handle 去重，避免同一人多次翻译）
    unique_bios = {}
    for t in tweets:
        h = t["handle"]
        if h and t.get("bio") and h not in unique_bios:
            unique_bios[h] = t["bio"]
    translated_bios = {h: _translate(b) for h, b in unique_bios.items()}
    for tweet in tweets:
        h = tweet["handle"]
        if h in translated_bios:
            tweet["bio_zh"] = translated_bios[h]

    return {
        "date": _parse_date(data.get("generatedAt")),
        "generated_at": data.get("generatedAt", ""),
        "tweets": tweets,
        "total_builders": len(data.get("x", [])),
    }
