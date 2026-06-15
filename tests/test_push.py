import json
import os
from datetime import date, datetime
from unittest.mock import patch

import pytest
import pytz

import push


# 所有测试里的伪 entry 都用这个发布时间——反正测试里实际日期由 _today monkeypatch 控制
FAKE_PUB = datetime(2026, 4, 27, 1, 0, tzinfo=pytz.utc)


ENV = {
    "LARK_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/main",
    "LARK_WEBHOOK_SECRET": "s1",
    "LARK_OPS_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/ops",
    "LARK_OPS_WEBHOOK_SECRET": "s2",
}


@pytest.fixture(autouse=True)
def _block_aihot_flow(monkeypatch):
    """juya 测试不想关心 aihot 流程——把它短路，永远返回"正常结束"。
    避免 aihot 的 fetch_daily 产生真实网络请求，也避免它污染 sent/state 断言。"""
    monkeypatch.setattr(push, "_push_aihot",
                        lambda *a, **kw: True)


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 0}))
    monkeypatch.setattr(push, "STATE_PATH", p)
    return p


def test_skip_when_already_pushed_today(state_path, monkeypatch):
    state_path.write_text(json.dumps({"last_pushed_date": "2026-04-27", "consecutive_failures": 0}))
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))
    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0


def test_skip_when_juya_not_updated(state_path, monkeypatch):
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    monkeypatch.setattr(push, "extract_today_entry", lambda xml, today: None)
    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0
    assert json.loads(state_path.read_text())["last_pushed_date"] is None


def test_happy_path_pushes_and_marks(state_path, monkeypatch):
    sent = []
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    monkeypatch.setattr(
        push, "extract_today_entry",
        lambda xml, today: {"title": "2026-04-27", "link": "http://x", "content_html": "", "description": "", "published_dt": FAKE_PUB},
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
    monkeypatch.setattr(push, "send_lark_card",
                        lambda url, secret, card: sent.append(("card", url)))
    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0
    assert sent == [("card", ENV["LARK_WEBHOOK_URL"])]
    assert json.loads(state_path.read_text())["last_pushed_date"] == "2026-04-27"


def test_failure_bumps_and_alerts_at_three(state_path, monkeypatch):
    state_path.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 2}))
    sent = []
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    monkeypatch.setattr(
        push, "extract_today_entry",
        lambda xml, today: {"title": "2026-04-27", "link": "http://x", "content_html": "", "description": "", "published_dt": FAKE_PUB},
    )
    monkeypatch.setattr(
        push, "parse_entry_to_card",
        lambda e: {"header": {}, "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "x"}}]},
    )

    def boom(*a, **kw):
        raise RuntimeError("network down")
    monkeypatch.setattr(push, "send_lark_card", boom)
    monkeypatch.setattr(push, "send_lark_text",
                        lambda url, secret, text: sent.append(("text", url, text)))

    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 1
    assert any(s[1] == ENV["LARK_OPS_WEBHOOK_URL"] for s in sent)
    assert json.loads(state_path.read_text())["consecutive_failures"] == 0


def test_degraded_parse_falls_back_to_text(state_path, monkeypatch):
    """parse_entry_to_card 返回 None → 降级为纯文本 + 运维群告警。"""
    sent = []
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    # 伪造一个带 published_dt 的 entry（push.py 会 astimezone 打日志）
    import pytz as _pytz
    from datetime import datetime as _dt
    fake_pub = _dt(2026, 4, 27, 1, 0, tzinfo=_pytz.utc)
    monkeypatch.setattr(
        push, "extract_today_entry",
        lambda xml, today: {
            "title": "2026-04-27", "link": "http://x",
            "content_html": "", "description": "",
            "published_dt": fake_pub,
        },
    )
    # 新语义：parse_entry_to_card 返回 None 表示"解析不出分组，请降级"
    monkeypatch.setattr(push, "parse_entry_to_card", lambda e: None)
    monkeypatch.setattr(push, "send_lark_text",
                        lambda url, secret, text: sent.append((url, text)))
    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0
    urls = [s[0] for s in sent]
    assert ENV["LARK_WEBHOOK_URL"] in urls     # 主群收降级文本
    assert ENV["LARK_OPS_WEBHOOK_URL"] in urls  # 运维群收告警
    assert json.loads(state_path.read_text())["last_pushed_date"] == "2026-04-27"


def test_backfill_refuses_to_duplicate_today(state_path, monkeypatch):
    """防手误：backfill 目标是今天、且今天已推过 → 拒绝重推。"""
    sent = []
    real_today = date(2026, 4, 27)
    state_path.write_text(json.dumps({
        "last_pushed_date": real_today.isoformat(),
        "consecutive_failures": 0,
    }))
    monkeypatch.setattr(push, "_today", lambda: real_today)
    monkeypatch.setattr(push, "_is_backfill", lambda: True)
    monkeypatch.setattr(
        "push.datetime",
        type("FakeDateTime", (), {
            "now": staticmethod(lambda tz=None: datetime(2026, 4, 27, 10, 0, tzinfo=pytz.timezone("Asia/Shanghai"))),
            "strptime": datetime.strptime,
        }),
    )
    # 这些应该都不被调用
    monkeypatch.setattr(push, "fetch_rss", lambda: (_ for _ in ()).throw(AssertionError("should not fetch")))
    monkeypatch.setattr(push, "send_lark_card", lambda *a: sent.append(a))

    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0
    assert sent == []  # 没有重推


def test_juya_dead_alerts_after_3_silent_days(state_path, monkeypatch):
    """juya 连续 3 天无更新 → 告警到运维群，一天最多一次。"""
    # state 里记录"juya 最后一期是 4 天前"
    state_path.write_text(json.dumps({
        "last_pushed_date": "2026-04-24",
        "consecutive_failures": 0,
        "last_juya_entry_date": "2026-04-24",
        "juya_dead_alerted_on": None,
    }))
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 28))
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    monkeypatch.setattr(push, "extract_today_entry", lambda xml, today: None)

    ops_alerts = []
    monkeypatch.setattr(push, "send_lark_text",
                        lambda url, secret, text: ops_alerts.append((url, text)))

    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0
    # 运维群收到 juya-dead 告警
    assert len(ops_alerts) == 1
    assert ops_alerts[0][0] == ENV["LARK_OPS_WEBHOOK_URL"]
    assert "juya 连续 4 天未更新" in ops_alerts[0][1]
    assert "2026-04-24" in ops_alerts[0][1]
    # state 记录已告警
    assert json.loads(state_path.read_text())["juya_dead_alerted_on"] == "2026-04-28"


def test_juya_dead_alert_only_once_per_day(state_path, monkeypatch):
    """同一天第二次轮询不重发告警。"""
    state_path.write_text(json.dumps({
        "last_pushed_date": "2026-04-24",
        "consecutive_failures": 0,
        "last_juya_entry_date": "2026-04-24",
        "juya_dead_alerted_on": "2026-04-28",  # 今天已告警过
    }))
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 28))
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    monkeypatch.setattr(push, "extract_today_entry", lambda xml, today: None)

    ops_alerts = []
    monkeypatch.setattr(push, "send_lark_text",
                        lambda url, secret, text: ops_alerts.append((url, text)))

    with patch.dict(os.environ, ENV):
        rc = push.main()
    assert rc == 0
    assert ops_alerts == []  # 不重复告警


def test_integration_fixture_to_card_to_send(state_path, monkeypatch):
    """端到端契约测试：真 fixture → 真 parse_feed → 真 parse_entry_to_card → mock send。

    只 mock 网络调用（fetch_rss 和 send_lark_card），其他走真实链路，
    确保 push.py 和 lark_card.py / rss.py 的接口契约不会悄悄漂移。"""
    from pathlib import Path
    fixture_xml = Path("tests/fixtures/juya_sample.xml").read_text()

    # fetch_rss 返回真 XML，其余真链路走到底
    monkeypatch.setattr(push, "fetch_rss", lambda: fixture_xml)
    monkeypatch.setattr(push, "_today", lambda: date(2026, 4, 27))

    captured: dict = {}
    def capture_card(url, secret, card):
        captured["url"] = url
        captured["card"] = card
    monkeypatch.setattr(push, "send_lark_card", capture_card)

    with patch.dict(os.environ, ENV):
        rc = push.main()

    assert rc == 0
    assert captured["url"] == ENV["LARK_WEBHOOK_URL"]
    # 卡片必须包含今天的日期、header、至少 1 个 div（概览分组）
    card = captured["card"]
    assert "2026-04-27" in card["header"]["title"]["content"]
    divs = [e for e in card["elements"] if e.get("tag") == "div"]
    assert len(divs) >= 1, "integration: 至少应有一个概览分组 div"
    # state 被标记
    assert json.loads(state_path.read_text())["last_pushed_date"] == "2026-04-27"
