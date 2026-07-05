"""飞书 webhook 频率限制（code=11232）重试逻辑测试。

lark._post_json 在遇到 code=11232 时会等待 30 秒后重试，最多重试 2 次
（总共 3 次请求）。这里覆盖三条路径：

  * 第一次 11232、第二次 code=0 → 成功（mock time.sleep 避免真等 30 秒）
  * 连续 3 次 11232 → 抛 RuntimeError
  * 非 11232 的错误码（例如 9499）不触发重试，立刻抛错

风格参考 tests/test_lark_send.py：用 responses mock HTTP，用
unittest.mock.patch mock time.sleep。
"""
from unittest.mock import patch

import pytest
import responses

from lark import _post_json


WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/ratelimit"
PAYLOAD = {"msg_type": "text", "content": {"text": "hi"}}


# ---------------------------------------------------------------------------
# 11232 后重试成功
# ---------------------------------------------------------------------------

@responses.activate
def test_rate_limit_then_success():
    """第一次返回 11232、第二次返回 code=0 → 整体成功，且确实等待过 30 秒。"""
    responses.add(
        responses.POST, WEBHOOK, status=200,
        json={"code": 11232, "msg": "frequency limited"},
    )
    responses.add(
        responses.POST, WEBHOOK, status=200,
        json={"code": 0, "msg": "ok"},
    )

    sleeps = []
    with patch("lark.time.sleep", lambda s: sleeps.append(s)):
        data = _post_json(WEBHOOK, PAYLOAD, 5)

    assert data == {"code": 0, "msg": "ok"}
    # 只重试了一次 → 只 sleep 一次，时长等于 _RATE_LIMIT_WAIT
    assert sleeps == [30]
    # 一共发了两次请求
    assert len(responses.calls) == 2


# ---------------------------------------------------------------------------
# 连续 3 次 11232 → RuntimeError
# ---------------------------------------------------------------------------

@responses.activate
def test_rate_limit_exhausts_retries_raises():
    """连续 3 次 11232（首次 + 2 次重试）→ 抛 RuntimeError，且 sleep 2 次。"""
    # _RATE_LIMIT_RETRIES = 2，所以总共最多 3 次请求
    for _ in range(3):
        responses.add(
            responses.POST, WEBHOOK, status=200,
            json={"code": 11232, "msg": "frequency limited"},
        )

    sleeps = []
    with patch("lark.time.sleep", lambda s: sleeps.append(s)):
        with pytest.raises(RuntimeError):
            _post_json(WEBHOOK, PAYLOAD, 5)

    # 重试 2 次 → sleep 2 次
    assert sleeps == [30, 30]
    # 3 次请求都打到了 webhook
    assert len(responses.calls) == 3


# ---------------------------------------------------------------------------
# 非 11232 错误码不触发重试
# ---------------------------------------------------------------------------

@responses.activate
def test_non_rate_limit_error_does_not_retry():
    """code=9499（卡片被拒）等非频率限制错误应立刻抛错，不重试、不 sleep。"""
    responses.add(
        responses.POST, WEBHOOK, status=200,
        json={"code": 9499, "msg": "card rejected"},
    )

    sleeps = []
    with patch("lark.time.sleep", lambda s: sleeps.append(s)):
        with pytest.raises(RuntimeError) as exc_info:
            _post_json(WEBHOOK, PAYLOAD, 5)

    # 错误信息包含 9499
    assert "9499" in str(exc_info.value)
    # 没有 sleep
    assert sleeps == []
    # 只发了一次请求
    assert len(responses.calls) == 1
