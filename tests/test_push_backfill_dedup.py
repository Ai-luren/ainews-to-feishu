"""backfill 历史日期去重测试。

push.py 的 _push_juya 在 backfill 成功后会调用 mark_pushed_today 记录
当天已推。再次 backfill 同一天会被 is_pushed_today 拦截而 skip，
但不会影响其他日期的 backfill。

覆盖两条路径：
  * backfill 2026-04-15 成功 → 再 backfill 2026-04-15 → skip（不重发、不 fetch）
  * backfill 2026-04-15 不影响 backfill 2026-04-16（两天各自成功推送一次）

参考 tests/test_push.py 的 fixture 风格，mock fetch_rss /
extract_today_entry / parse_entry_to_card / send_lark_card。
"""
import json
import os
from datetime import datetime
from unittest.mock import patch

import pytest
import pytz

import push


# 测试用的发布时间，实际日期由 PUSH_TARGET_DATE 控制
FAKE_PUB = datetime(2026, 4, 15, 1, 0, tzinfo=pytz.utc)


ENV = {
    "LARK_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/main",
    "LARK_WEBHOOK_SECRET": "s1",
    "LARK_OPS_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/ops",
    "LARK_OPS_WEBHOOK_SECRET": "s2",
    "PUSH_MODE": "morning",
}


@pytest.fixture(autouse=True)
def _block_aihot_and_builders(monkeypatch):
    """juya backfill 测试不关心 aihot/builders 流程——短路为"正常结束"，
    避免真实网络请求污染 sent/state 断言。"""
    monkeypatch.setattr(push, "_push_aihot", lambda *a, **kw: True)
    monkeypatch.setattr(push, "_push_builders", lambda *a, **kw: True)


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    """隔离 state.json，避免污染仓库里的真实状态。"""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 0}))
    monkeypatch.setattr(push, "STATE_PATH", p)
    return p


def _wire_juya_happy_path(monkeypatch, sent, fetch_calls):
    """把 juya 拉取/解析/发送链路 mock 成 happy path，并记录发送和 fetch 调用。"""
    monkeypatch.setattr(
        push, "fetch_rss",
        lambda: fetch_calls.append("fetch") or "<rss/>",
    )
    monkeypatch.setattr(
        push, "extract_today_entry",
        lambda xml, today: {
            "title": str(today),
            "link": "http://x",
            "content_html": "",
            "description": "",
            "published_dt": FAKE_PUB,
        },
    )
    monkeypatch.setattr(
        push, "parse_entry_to_card",
        lambda e: {
            "header": {},
            "elements": [
                {"tag": "div", "text": {"tag": "lark_md", "content": "**🔴 要闻**\n• test"}}
            ],
        },
    )
    monkeypatch.setattr(
        push, "send_lark_card",
        lambda url, secret, card: sent.append((url, card)),
    )


# ---------------------------------------------------------------------------
# 同一天重复 backfill → 第二次 skip
# ---------------------------------------------------------------------------

def test_backfill_same_day_twice_second_skips(state_path, monkeypatch):
    """backfill 2026-04-15 成功推送后，再次 backfill 2026-04-15 → skip。"""
    sent = []
    fetch_calls = []
    _wire_juya_happy_path(monkeypatch, sent, fetch_calls)

    env = {**ENV, "PUSH_TARGET_DATE": "2026-04-15"}

    # 第一次 backfill → 应成功推送
    with patch.dict(os.environ, env):
        rc1 = push.main()
    assert rc1 == 0
    assert len(sent) == 1
    assert sent[0][0] == ENV["LARK_WEBHOOK_URL"]
    # state 记录 04-15 已推
    assert json.loads(state_path.read_text())["last_pushed_date"] == "2026-04-15"

    # 第二次 backfill 同一天 → 被 is_pushed_today 拦截，不重发
    with patch.dict(os.environ, env):
        rc2 = push.main()
    assert rc2 == 0
    # 发送次数没有增加
    assert len(sent) == 1
    # fetch_rss 也只被调用一次（去重在 fetch 之前拦截）
    assert fetch_calls == ["fetch"]


# ---------------------------------------------------------------------------
# 不同日期 backfill 互不影响
# ---------------------------------------------------------------------------

def test_backfill_different_day_not_affected(state_path, monkeypatch):
    """backfill 2026-04-15 不影响 backfill 2026-04-16：两天各自成功推送一次。"""
    sent = []
    fetch_calls = []
    _wire_juya_happy_path(monkeypatch, sent, fetch_calls)

    # 先 backfill 04-15
    with patch.dict(os.environ, {**ENV, "PUSH_TARGET_DATE": "2026-04-15"}):
        rc1 = push.main()
    assert rc1 == 0
    assert len(sent) == 1
    assert json.loads(state_path.read_text())["last_pushed_date"] == "2026-04-15"

    # 再 backfill 04-16 → 不被 04-15 的记录拦截，应成功推送
    with patch.dict(os.environ, {**ENV, "PUSH_TARGET_DATE": "2026-04-16"}):
        rc2 = push.main()
    assert rc2 == 0
    # 两天各推一次
    assert len(sent) == 2
    # 两次都打到主群 webhook
    assert all(s[0] == ENV["LARK_WEBHOOK_URL"] for s in sent)
    # state 现在记录的是 04-16（最后一次 backfill 的日期）
    assert json.loads(state_path.read_text())["last_pushed_date"] == "2026-04-16"
    # fetch_rss 被调用两次（两天各拉一次）
    assert fetch_calls == ["fetch", "fetch"]
