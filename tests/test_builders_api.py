"""builders.fetch_feed API 网络层测试 + 纯函数测试。

用 responses 库 mock follow-builders feed（GitHub raw URL），覆盖：
- fetch_feed 正常返回 / 非 dict 响应
- _parse_date ISO 时间戳 → 北京时间 date（含跨天场景）
- has_content 有推文 / 空推文 / None 值
- get_top_tweets 按互动量排序 / limit 截断
- _batch_translate 用 mock _translate 避免真实网络请求
"""

from datetime import date

import pytest
import responses

import builders
from builders import (
    FEED_URL,
    _batch_translate,
    _parse_date,
    fetch_feed,
    get_top_tweets,
    has_content,
)


def _make_feed(**overrides):
    """构造合法的 builders feed 响应体。"""
    base = {
        "generatedAt": "2026-07-01T00:30:00.000Z",
        "x": [
            {
                "name": "Test Person",
                "handle": "testhandle",
                "bio": "AI researcher",
                "tweets": [
                    {"text": "hello world", "url": "https://x.com/t/1",
                     "likes": 100, "retweets": 20},
                ],
            },
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# fetch_feed: 正常路径
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_feed_returns_dict():
    """正常返回 dict。"""
    responses.add(responses.GET, FEED_URL, status=200, json=_make_feed())
    result = fetch_feed()
    assert isinstance(result, dict)
    assert "x" in result


# ---------------------------------------------------------------------------
# fetch_feed: 非 dict 响应
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_feed_non_dict_raises_value_error():
    """响应非 dict（如 JSON 数组）→ 抛 ValueError。"""
    responses.add(responses.GET, FEED_URL, status=200, json=[1, 2, 3])
    with pytest.raises(ValueError, match="非 dict"):
        fetch_feed()


# ---------------------------------------------------------------------------
# _parse_date: ISO 时间戳 → 北京时间 date
# ---------------------------------------------------------------------------

def test_parse_date_valid_iso():
    """正常 ISO 时间戳 → 北京日期。

    2026-07-01T00:30:00Z → 北京 2026-07-01 08:30 → date 2026-07-01
    """
    assert _parse_date("2026-07-01T00:30:00.000Z") == date(2026, 7, 1)


def test_parse_date_utc_crosses_day():
    """UTC 16:00 → 北京次日 00:00 → 日期进一天。

    2026-07-01T16:00:00Z → 北京 2026-07-02 00:00 → date 2026-07-02
    """
    assert _parse_date("2026-07-01T16:00:00.000Z") == date(2026, 7, 2)


def test_parse_date_malformed():
    """畸形时间戳 → None。"""
    assert _parse_date("not-a-date") is None


def test_parse_date_empty_string():
    """空字符串 → None。"""
    assert _parse_date("") is None


def test_parse_date_none():
    """None → None。"""
    assert _parse_date(None) is None


# ---------------------------------------------------------------------------
# has_content: 有推文 / 空推文 / None
# ---------------------------------------------------------------------------

def test_has_content_with_tweets():
    """有推文 → True。"""
    feed = {"x": [{"tweets": [{"text": "hi"}]}]}
    assert has_content(feed) is True


def test_has_content_empty_tweets():
    """空推文列表 → False。"""
    feed = {"x": [{"tweets": []}]}
    assert has_content(feed) is False


def test_has_content_none_value():
    """x 值为 None → False。"""
    assert has_content({"x": None}) is False


def test_has_content_empty_dict():
    """空 dict → False。"""
    assert has_content({}) is False


def test_has_content_empty_builders_list():
    """空 builders 列表 → False。"""
    assert has_content({"x": []}) is False


# ---------------------------------------------------------------------------
# get_top_tweets: 按互动量排序 / limit 截断
# ---------------------------------------------------------------------------

def test_get_top_tweets_sorted_by_engagement():
    """按互动量（likes + retweets）降序排列。"""
    feed = {
        "x": [
            {"name": "A", "handle": "a", "bio": "",
             "tweets": [
                 {"text": "t1", "url": "u1", "likes": 10, "retweets": 5},    # 15
                 {"text": "t2", "url": "u2", "likes": 50, "retweets": 50},   # 100
             ]},
            {"name": "B", "handle": "b", "bio": "",
             "tweets": [
                 {"text": "t3", "url": "u3", "likes": 150, "retweets": 50},  # 200
             ]},
        ]
    }
    tweets = get_top_tweets(feed)
    engagements = [t["engagement"] for t in tweets]
    assert engagements == [200, 100, 15]


def test_get_top_tweets_engagement_field_correct():
    """每条推文的 engagement = likes + retweets。"""
    feed = {
        "x": [
            {"name": "A", "handle": "a", "bio": "",
             "tweets": [
                 {"text": "t1", "url": "u1", "likes": 30, "retweets": 70},
             ]},
        ]
    }
    tweets = get_top_tweets(feed)
    assert tweets[0]["engagement"] == 100
    assert tweets[0]["likes"] == 30
    assert tweets[0]["retweets"] == 70


def test_get_top_tweets_limit_truncation():
    """limit 截断：只返回前 N 条。"""
    feed = {
        "x": [
            {"name": "A", "handle": "a", "bio": "",
             "tweets": [
                 {"text": f"t{i}", "url": f"u{i}", "likes": 100 - i, "retweets": 0}
                 for i in range(20)
             ]},
        ]
    }
    tweets = get_top_tweets(feed, limit=5)
    assert len(tweets) == 5
    # 应取互动量最高的 5 条（降序）
    engagements = [t["engagement"] for t in tweets]
    assert engagements == sorted(engagements, reverse=True)
    assert engagements[0] == 100  # likes=100, retweets=0 → engagement=100


def test_get_top_tweets_default_limit():
    """默认 limit=MAX_TWEETS（10）。"""
    feed = {
        "x": [
            {"name": "A", "handle": "a", "bio": "",
             "tweets": [
                 {"text": f"t{i}", "url": f"u{i}", "likes": 100 - i, "retweets": 0}
                 for i in range(20)
             ]},
        ]
    }
    tweets = get_top_tweets(feed)
    assert len(tweets) == builders.MAX_TWEETS


def test_get_top_tweets_empty_feed():
    """空 feed → 空列表。"""
    assert get_top_tweets({"x": []}) == []


def test_get_top_tweets_preserves_builder_info():
    """推文保留 builder 的 name/handle/bio 信息。"""
    feed = {
        "x": [
            {"name": "Test Person", "handle": "testhandle", "bio": "AI researcher",
             "tweets": [
                 {"text": "hello", "url": "u1", "likes": 10, "retweets": 5},
             ]},
        ]
    }
    tweets = get_top_tweets(feed)
    assert tweets[0]["name"] == "Test Person"
    assert tweets[0]["handle"] == "testhandle"
    assert tweets[0]["bio"] == "AI researcher"


# ---------------------------------------------------------------------------
# _batch_translate: mock _translate 避免真实网络请求
# ---------------------------------------------------------------------------

def test_batch_translate_with_mocked_translate(monkeypatch):
    """_batch_translate 用线程池并发翻译，mock _translate 避免真实网络。"""
    def mock_translate(text):
        return f"[译]{text}"

    monkeypatch.setattr(builders, "_translate", mock_translate)
    result = _batch_translate(["hello", "world"])
    assert result == ["[译]hello", "[译]world"]


def test_batch_translate_empty_list():
    """空列表输入返回空列表。"""
    assert _batch_translate([]) == []


def test_batch_translate_preserves_order(monkeypatch):
    """并发执行后结果顺序与输入一致。"""
    def mock_translate(text):
        # 模拟不同耗时的翻译，验证顺序不乱
        return text.upper()

    monkeypatch.setattr(builders, "_translate", mock_translate)
    texts = [f"item_{i}" for i in range(10)]
    result = _batch_translate(texts)
    assert result == [t.upper() for t in texts]


def test_batch_translate_translate_failure_fallback(monkeypatch):
    """单条翻译异常 → 保持原文兜底。"""
    def mock_translate(text):
        if text == "fail":
            raise RuntimeError("translate error")
        return f"[译]{text}"

    monkeypatch.setattr(builders, "_translate", mock_translate)
    result = _batch_translate(["ok", "fail", "good"])
    assert result == ["[译]ok", "fail", "[译]good"]
