"""补充测试：rss.fetch_rss 网络错误、_DEAD_RSS_URLS 回退、extract_today_entry 标题日期回退。

这些场景在原 test_rss.py 中未被覆盖——原文件只走了 fixture XML 的 parse_feed 与
published 北京日期匹配路径。
"""

import importlib
import os as _os
from datetime import date

import pytest
import responses

import rss
from rss import (
    _DEAD_RSS_URLS,
    _RSS_URL_DEFAULT,
    extract_today_entry,
    fetch_rss,
    get_effective_rss_url,
)


# ---------------------------------------------------------------------------
# fetch_rss: HTTP 404 / 500 / 响应过大 / 连接异常 / 成功
# ---------------------------------------------------------------------------

@responses.activate
def test_fetch_rss_raises_on_http_404():
    """404 应当抛 HTTPError（由 raise_for_status 触发）。"""
    responses.add(
        responses.GET, "http://example.invalid/rss.xml", status=404, body="not found",
    )
    with pytest.raises(Exception):  # HTTPError
        fetch_rss(url="http://example.invalid/rss.xml", timeout=1)


@responses.activate
def test_fetch_rss_raises_on_http_500():
    """服务端 5xx 应当抛 HTTPError。"""
    responses.add(
        responses.GET, "http://example.invalid/rss.xml", status=500, body="boom",
    )
    with pytest.raises(Exception):
        fetch_rss(url="http://example.invalid/rss.xml", timeout=1)


@responses.activate
def test_fetch_rss_raises_on_oversized_body():
    """响应体超过 MAX_RSS_BYTES 应被显式拒绝（拒绝劫持流量）。"""
    body = b"x" * (rss.MAX_RSS_BYTES + 1)
    responses.add(
        responses.GET, "http://example.invalid/rss.xml", status=200, body=body,
        content_type="application/rss+xml",
    )
    with pytest.raises(RuntimeError, match="过大"):
        fetch_rss(url="http://example.invalid/rss.xml", timeout=1)


def test_fetch_rss_raises_on_connect_timeout(monkeypatch):
    """DNS 失败 / connect 超时会走 requests.ConnectionError，应当冒泡抛错。

    （由 push.main() 的外层 try/except 统一 bump failure，不会直接崩进程。）
    """
    import requests as _requests

    class _FakeSession:
        def get(self, *a, **kw):
            raise _requests.ConnectionError("DNS failure")

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    monkeypatch.setattr(rss, "_session_with_retries", _FakeSession)
    with pytest.raises(_requests.ConnectionError):
        fetch_rss(url="http://will-never-resolve.invalid/rss.xml", timeout=1)


@responses.activate
def test_fetch_rss_returns_bytes_on_success():
    """成功路径：返回 bytes（基本契约）。"""
    responses.add(
        responses.GET, "http://example.invalid/rss.xml", status=200, body=b"<rss/>",
        content_type="application/rss+xml",
    )
    got = fetch_rss(url="http://example.invalid/rss.xml", timeout=1)
    assert got == b"<rss/>"


@responses.activate
def test_fetch_rss_rejects_html_content_type():
    """HTTP 200 但返回 HTML（运营商劫持错误页）应被拒绝，不静默当"无条目"。

    回归 P1-5：feedparser 解析 HTML 会得到空 entries，
    原先会被静默当作"今日无条目"跳过推送。
    """
    responses.add(
        responses.GET, "http://example.invalid/rss.xml",
        status=200, body=b"<html><body>error</body></html>",
        content_type="text/html; charset=utf-8",
    )
    with pytest.raises(RuntimeError, match="非 XML"):
        fetch_rss(url="http://example.invalid/rss.xml", timeout=1)


# ---------------------------------------------------------------------------
# _DEAD_RSS_URLS: 配置了旧地址时应强制回退到默认
# ---------------------------------------------------------------------------

def test_dead_rss_url_forces_fallback_to_default(monkeypatch, capsys):
    """RSS_URL 指向 _DEAD_RSS_URLS 时，实际生效地址应为默认地址，并打印 warning。"""
    for dead in _DEAD_RSS_URLS:
        monkeypatch.setitem(_os.environ, "RSS_URL", dead)
        importlib.reload(rss)
        assert rss.RSS_URL == _RSS_URL_DEFAULT, (
            f"{dead} 应被回退到默认地址"
        )
        captured = capsys.readouterr()
        assert dead in captured.out or "废弃" in captured.out or "回退" in captured.out

    # 清理：重新设回默认值（让后续测试不受影响
    monkeypatch.delenv("RSS_URL", raising=False)
    importlib.reload(rss)


def test_get_effective_rss_url_matches_module_constant():
    """辅助函数 get_effective_rss_url 应返回与 RSS_URL 一致的值。"""
    assert get_effective_rss_url() == rss.RSS_URL


# ---------------------------------------------------------------------------
# extract_today_entry: 标题日期回退
# ---------------------------------------------------------------------------

RSS_TEMPLATE = """<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0">
  <channel>
    <title>fixture</title>
    <link>http://example.invalid/</link>
    <description>fixture</description>
    {entries}
  </channel>
</rss>
"""


def _item(title: str, pubdate_utc: str, link: str = "http://example.invalid/") -> str:
    return (
        "<item>"
        f"<title>{title}</title>"
        f"<link>{link}</link>"
        f"<pubDate>{pubdate_utc}</pubDate>"
        "<description><![CDATA[<p>hi</p>]]></description>"
        "</item>"
    )


def test_extract_today_entry_title_fallback_when_published_mismatch():
    """条目 published 日期不等于 today，但标题里明确写着 today → 应通过标题
    日期回退匹配命中。"""
    xml = RSS_TEMPLATE.format(
        entries=_item("2026-04-27 backfill", "Sun, 26 Apr 2026 23:02:00 +0000")
    )
    # Sun, 26 Apr 2026 23:02 UTC → 北京 2026-04-27 07:02 → published 北京日期 = 04-27，
    # 其实本例会走 published 路径命中；故意用更早的 published 试试让它走标题匹配路径：
    xml_pub_on_diff_day = RSS_TEMPLATE.format(
        entries=_item("2026-04-27 backfill", "Sat, 25 Apr 2026 20:00:00 +0000")
    )
    # 2026-04-25 20:00 UTC → 北京 2026-04-26 04:00 → published 北京日期 = 04-26；
    # 但标题写的是 04-27 → 必须走标题回退才会命中。
    entry = extract_today_entry(xml_pub_on_diff_day, today=date(2026, 4, 27))
    assert entry is not None
    assert "2026-04-27 backfill" in entry["title"]


def test_extract_today_entry_returns_none_when_both_paths_miss():
    """published 与标题都匹配不上 → 返回 None。"""
    xml = RSS_TEMPLATE.format(
        entries=_item("2026-04-20 old", "Mon, 20 Apr 2026 00:00:00 +0000")
    )
    assert extract_today_entry(xml, today=date(2026, 4, 27)) is None


def test_extract_today_entry_invalid_title_date_still_safe():
    """标题里写了畸形的 YYYY-MM-DD（比如 2026-02-30）→ 不崩，继续回退或返回 None。"""
    xml = RSS_TEMPLATE.format(
        entries=_item("2026-02-30 bad-date", "Mon, 27 Apr 2026 00:00:00 +0000")
    )
    entry = extract_today_entry(xml, today=date(2026, 4, 27))
    # published 北京日期 = 04-27，仍然能通过 published 分支命中——核心断言是"不会崩"。
    assert entry is not None


def test_extract_today_entry_default_today_uses_beijing_now():
    """today=None 时会根据系统时间推导；这里只验证不抛异常。"""
    xml = RSS_TEMPLATE.format(
        entries=_item("2099-01-01 far-future", "Fri, 01 Jan 2099 00:00:00 +0000")
    )
    got = extract_today_entry(xml)
    assert got is None or isinstance(got, dict)
