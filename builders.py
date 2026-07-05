"""follow-builders X/Twitter feed 抓取 + Google 翻译。

从 follow-builders 仓库拉取每日 AI 大佬推文 feed，
按互动量排序取 Top N，翻译成中文，返回结构化数据。
"""
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime
from typing import List, Optional

import pytz
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

BEIJING = pytz.timezone("Asia/Shanghai")

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
    """批量翻译，用线程池并发以控制总时长。

    Google 免费接口不支持批量，逐条调用但并发执行。
    10 条推文 + 10 个 bio = 20 次请求，串行最坏 20×15s=300s
    可能超过 GitHub Actions 超时，因此改用 max_workers=5 并发。

    保护策略（接口签名与返回顺序保持不变）：
    - 总时长超过 120 秒后，剩余未完成的翻译走原文兜底；
    - 单条翻译异常或 30 秒超时，走原文兜底；
    - results 预初始化为原文，成功的覆盖，失败的保持原文。
    """
    if not texts:
        return []
    # 默认兜底为原文，保证返回长度与输入一致、顺序不乱
    results = list(texts)
    start = time.time()
    with ThreadPoolExecutor(max_workers=5) as executor:
        future_to_idx = {
            executor.submit(_translate, t): i
            for i, t in enumerate(texts)
        }
        for future in as_completed(future_to_idx):
            idx = future_to_idx[future]
            # 总时长保护：超过 120 秒，剩余走原文（results 已初始化为原文）
            if time.time() - start > 120:
                continue
            try:
                results[idx] = future.result(timeout=30)
            except Exception:
                # 单条超时或异常，保持原文兜底
                pass
    return results


def fetch_feed() -> dict:
    """拉取 follow-builders X/Twitter feed JSON。

    添加时间戳查询参数绕过 GitHub raw CDN 缓存（最长缓存 5 分钟），
    确保每次拉取都能获取最新内容。否则 cron 窗口最后一轮（15:30）
    可能拿到 5 分钟前的缓存，导致 feed 日期还是昨天而跳过推送。
    """
    s = _session()
    url = f"{FEED_URL}?t={int(time.time())}"
    resp = s.get(url, timeout=(5, 30))
    resp.raise_for_status()
    data = resp.json()
    # 防御：resp.json() 可能返回 list/str 等，后续 data.get() 会抛 AttributeError
    if not isinstance(data, dict):
        raise ValueError(f"feed 返回非 dict: {type(data).__name__}")
    return data


def has_content(feed_data: dict) -> bool:
    """检查 feed 是否有推文内容。"""
    builders = feed_data.get("x", [])
    if not builders:
        return False
    return any(b.get("tweets") for b in builders)


def _parse_date(generated_at: str) -> Optional[date]:
    """解析 feed 的 generatedAt 时间戳，返回北京日期。"""
    if not generated_at:
        return None
    try:
        # 格式: 2026-06-22T08:29:37.749Z
        dt = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        # 转成北京时间再取日期，防止凌晨更新时 UTC 日期比北京日期少一天
        return dt.astimezone(BEIJING).date()
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
    # bio 也走并发翻译，避免串行超时
    bio_texts = list(unique_bios.values())
    bio_translations = _batch_translate(bio_texts)
    translated_bios = dict(zip(unique_bios.keys(), bio_translations))
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
