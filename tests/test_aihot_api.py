"""aihot.fetch_daily API 网络层测试 + 纯函数测试。

用 responses 库 mock aihot API（https://aihot.virxact.com/api/public/daily），
覆盖 fetch_daily 的正常路径、404/401/403 错误分支、响应过大防护、非 dict 响应，
以及 daily_date / has_content / total_items 三个纯函数。
"""

from datetime import date

import pytest
import responses

import aihot
from aihot import (
    _DAILY_URL,
    _MAX_BYTES,
    daily_date,
    fetch_daily,
    has_content,
    total_items,
)


def _make_daily(**overrides):
    """构造合法的 aihot 日报响应体。"""
    base = {
        "date": "2026-07-01",
        "sections": [
            {"label": "大模型", "items": [
                {"title": "test", "sourceUrl": "https://example.com"},
            ]},
        ],
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# fetch_daily: 正常路径
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_daily_with_date_returns_dict():
    """指定日期正常返回 dict。"""
    target = date(2026, 7, 1)
    url = f"{_DAILY_URL}/{target}"
    responses.add(responses.GET, url, status=200, json=_make_daily())
    result = fetch_daily(target)
    assert isinstance(result, dict)
    assert result["date"] == "2026-07-01"


@responses.activate
def test_fetch_daily_no_date_returns_dict():
    """不指定日期拉最新一期，正常返回 dict。"""
    responses.add(responses.GET, _DAILY_URL, status=200, json=_make_daily())
    result = fetch_daily()
    assert isinstance(result, dict)
    assert result["date"] == "2026-07-01"


# ---------------------------------------------------------------------------
# fetch_daily: 404 处理
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_daily_404_with_date_returns_none():
    """指定日期 404 = 该日期无内容，返回 None（正常状态）。"""
    target = date(2026, 7, 1)
    url = f"{_DAILY_URL}/{target}"
    responses.add(responses.GET, url, status=404, body="not found")
    assert fetch_daily(target) is None


@responses.activate
def test_fetch_daily_404_without_date_raises():
    """最新一期 404 = API 端点异常，抛 RuntimeError。"""
    responses.add(responses.GET, _DAILY_URL, status=404, body="not found")
    with pytest.raises(RuntimeError, match="404"):
        fetch_daily()


# ---------------------------------------------------------------------------
# fetch_daily: 401 / 403 鉴权失败（不可自动恢复）
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_daily_403_raises_unrecoverable():
    """403 = IP 被封，不可自动恢复，抛 RuntimeError。"""
    responses.add(responses.GET, _DAILY_URL, status=403, body="forbidden")
    with pytest.raises(RuntimeError, match="不可自动恢复"):
        fetch_daily()


@responses.activate
def test_fetch_daily_401_raises():
    """401 = 鉴权失败，抛 RuntimeError。"""
    responses.add(responses.GET, _DAILY_URL, status=401, body="unauthorized")
    with pytest.raises(RuntimeError, match="401"):
        fetch_daily()


# ---------------------------------------------------------------------------
# fetch_daily: 响应过大防护
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_daily_content_length_too_large_raises(monkeypatch):
    """Content-Length 预检超过 _MAX_BYTES → 拒绝下载，抛 RuntimeError。

    用 monkeypatch 把 _MAX_BYTES 调小到 50，避免在测试里构造 1MB body。
    """
    monkeypatch.setattr(aihot, "_MAX_BYTES", 50)
    # _make_daily() 序列化后 > 50 字节，Content-Length 也会 > 50
    responses.add(responses.GET, _DAILY_URL, status=200, json=_make_daily())
    with pytest.raises(RuntimeError, match="过大"):
        fetch_daily()


@responses.activate
def test_fetch_daily_body_too_large_raises(monkeypatch):
    """实际 body 超过 _MAX_BYTES → 抛 RuntimeError。

    不显式设 Content-Length，让 responses 自动处理。
    如果 responses 设了 CL，则 CL 预检先触发；如果没设，则 resp.content 长度检查触发。
    两条防线都会抛 RuntimeError("过大")。
    """
    monkeypatch.setattr(aihot, "_MAX_BYTES", 50)
    responses.add(responses.GET, _DAILY_URL, status=200, body=b"x" * 100)
    with pytest.raises(RuntimeError, match="过大"):
        fetch_daily()


# ---------------------------------------------------------------------------
# fetch_daily: 非 dict 响应
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_daily_non_dict_raises():
    """响应非 dict（如 JSON 数组）→ 抛错，不能静默通过。

    注意：aihot.py 在构造错误消息时调用 list(data.keys())，
    非 dict 响应必须报 ValueError。
    """
    responses.add(responses.GET, _DAILY_URL, status=200, json=[1, 2, 3])
    with pytest.raises(ValueError, match="非 dict"):
        fetch_daily()


@responses.activate
def test_fetch_daily_dict_missing_keys_raises_value_error():
    """响应是 dict 但缺少 date/sections 字段 → 抛 ValueError。"""
    responses.add(responses.GET, _DAILY_URL, status=200, json={"foo": "bar"})
    with pytest.raises(ValueError, match="响应结构异常"):
        fetch_daily()


# ---------------------------------------------------------------------------
# 纯函数: daily_date
# ---------------------------------------------------------------------------

def test_daily_date_valid():
    """合法日期字符串 → date 对象。"""
    assert daily_date({"date": "2026-07-01"}) == date(2026, 7, 1)


def test_daily_date_missing():
    """缺少 date 字段 → None。"""
    assert daily_date({}) is None


def test_daily_date_invalid():
    """畸形日期 → None。"""
    assert daily_date({"date": "not-a-date"}) is None


def test_daily_date_non_dict():
    """非 dict 输入 → None。"""
    assert daily_date(None) is None


# ---------------------------------------------------------------------------
# 纯函数: total_items
# ---------------------------------------------------------------------------

def test_total_items_normal():
    """多个 section 的 items 数量求和。"""
    daily = {"sections": [{"items": [1, 2]}, {"items": [3]}]}
    assert total_items(daily) == 3


def test_total_items_empty_sections():
    """空 sections → 0。"""
    assert total_items({"sections": []}) == 0


def test_total_items_no_sections_key():
    """无 sections 键 → 0。"""
    assert total_items({}) == 0


def test_total_items_section_without_items():
    """section 缺少 items 键 → 该 section 计 0。"""
    daily = {"sections": [{"items": [1]}, {"label": "no items"}]}
    assert total_items(daily) == 1


# ---------------------------------------------------------------------------
# 纯函数: has_content
# ---------------------------------------------------------------------------

def test_has_content_true():
    """有 items → True。"""
    assert has_content({"sections": [{"items": [1]}]}) is True


def test_has_content_false_empty_sections():
    """空 sections → False。"""
    assert has_content({"sections": []}) is False


def test_has_content_false_none():
    """None → False。"""
    assert has_content(None) is False


def test_has_content_false_empty_dict():
    """空 dict → False。"""
    assert has_content({}) is False
