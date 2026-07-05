"""push.py 的 all 模式按时间自动分流测试。

push.main() 在 PUSH_MODE=all 且非 backfill 时会按北京时间当前小时分流：
  * hour < 14 → 等效 morning（只推 aihot + juya）
  * hour >= 14 → 保持 all，依次推 aihot + juya + builders
    （去重机制会跳过上午已推的，未推的会补推；
     避免上午 cron 全部失败时下午只推 builders 导致 aihot/juya 当天丢失）

这里覆盖四条路径：
  * all + 13:59（hour=13）→ 路由到 morning
  * all + 14:00（hour=14）→ 保持 all，三个源都调用
  * morning 模式不受时间影响（即使 hour=14 仍推 aihot+juya）
  * builders 模式不受时间影响（即使 hour=13 仍只推 builders）

用 monkeypatch mock push.datetime 控制时间，mock 三个 _push_* 函数记录调用。
风格参考 tests/test_push.py 的 ENV 和 fixture。
"""
import json
import os
from datetime import datetime
from unittest.mock import patch

import pytest
import pytz

import push


BEIJING = pytz.timezone("Asia/Shanghai")


ENV = {
    "LARK_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/main",
    "LARK_WEBHOOK_SECRET": "s1",
    "LARK_OPS_WEBHOOK_URL": "https://open.feishu.cn/open-apis/bot/v2/hook/ops",
    "LARK_OPS_WEBHOOK_SECRET": "s2",
    # all 模式才会触发时间分流；morning/builders 是显式模式
    "PUSH_MODE": "all",
}


@pytest.fixture
def state_path(tmp_path, monkeypatch):
    """隔离 state.json，避免污染仓库里的真实状态。"""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 0}))
    monkeypatch.setattr(push, "STATE_PATH", p)
    return p


def _fake_datetime(hour: int, minute: int = 0):
    """构造一个假的 push.datetime，其 now() 永远返回北京时间 hour:minute。

    strptime 保留真实实现，因为 _today 在 PUSH_TARGET_DATE 非法时会用到。
    """
    fake_now = datetime(2026, 4, 27, hour, minute, tzinfo=BEIJING)
    return type("FakeDT", (), {
        "now": staticmethod(lambda tz=None: fake_now),
        "strptime": staticmethod(datetime.strptime),
    })


def _record_calls(monkeypatch):
    """把三个 _push_* 替换成只记录调用名 + 返回 True 的桩函数。"""
    calls = []
    monkeypatch.setattr(push, "_push_aihot",
                        lambda *a, **kw: calls.append("aihot") or True)
    monkeypatch.setattr(push, "_push_juya",
                        lambda *a, **kw: calls.append("juya") or True)
    monkeypatch.setattr(push, "_push_builders",
                        lambda *a, **kw: calls.append("builders") or True)
    return calls


# ---------------------------------------------------------------------------
# all 模式时间分流
# ---------------------------------------------------------------------------

def test_all_mode_before_14_routes_to_morning(state_path, monkeypatch):
    """all 模式 + 13:59 → 路由到 morning：调用 aihot + juya，不调用 builders。"""
    monkeypatch.setattr(push, "datetime", _fake_datetime(13, 59))
    calls = _record_calls(monkeypatch)

    with patch.dict(os.environ, ENV):
        rc = push.main()

    assert rc == 0
    assert calls == ["aihot", "juya"]


def test_all_mode_at_14_runs_all_three_sources(state_path, monkeypatch):
    """all 模式 + 14:00 → 保持 all：依次调用 aihot + juya + builders。

    下午不再硬切到 builders，而是三个源都跑一遍：
    上午已推过的会被去重 skip，未推的会补推，
    避免上午 cron 全部失败时下午只推 builders 导致 aihot/juya 当天丢失。
    """
    monkeypatch.setattr(push, "datetime", _fake_datetime(14, 0))
    calls = _record_calls(monkeypatch)

    with patch.dict(os.environ, ENV):
        rc = push.main()

    assert rc == 0
    assert calls == ["aihot", "juya", "builders"]


# ---------------------------------------------------------------------------
# 显式模式不受时间影响
# ---------------------------------------------------------------------------

def test_morning_mode_ignores_time(state_path, monkeypatch):
    """morning 模式即使 14:00 也仍推 aihot + juya（不被路由改写）。"""
    monkeypatch.setattr(push, "datetime", _fake_datetime(14, 0))
    calls = _record_calls(monkeypatch)

    with patch.dict(os.environ, {**ENV, "PUSH_MODE": "morning"}):
        rc = push.main()

    assert rc == 0
    assert calls == ["aihot", "juya"]


def test_builders_mode_ignores_time(state_path, monkeypatch):
    """builders 模式即使 13:59 也仍只推 builders（不被路由改写）。"""
    monkeypatch.setattr(push, "datetime", _fake_datetime(13, 59))
    calls = _record_calls(monkeypatch)

    with patch.dict(os.environ, {**ENV, "PUSH_MODE": "builders"}):
        rc = push.main()

    assert rc == 0
    assert calls == ["builders"]
