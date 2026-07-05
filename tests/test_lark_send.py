"""补充测试：lark.send_lark_text / send_lark_card / _post_json / lark_sign 错误分支。

原 test_send_lark_text.py 覆盖了成功路径、HTTP 500、code != 0 三种情况；
test_send_lark_card.py 覆盖了成功和 code != 0。这里补齐：

  * send_lark_text: HTTP 非 200 的其他状态码（4xx/5xx）、非 JSON 响应体
  * send_lark_card: HTTP 非 200、非 JSON 响应体
  * _post_json 内部: code != 0 但响应体不是 dict（例如响应体是字符串）
  * lark_sign: 入参非法（secret 为空、timestamp 非数字）
  * webhook 为空 / 非 http(s):// → ValueError
"""

import json

import pytest
import responses
from lark import (
    _post_json,
    lark_sign,
    send_lark_card,
    send_lark_text,
)


WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/test"
CARD = {"header": {"title": {"tag": "plain_text", "content": "t"}},
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "x"}}]}


# ---------------------------------------------------------------------------
# HTTP 非 200
# ---------------------------------------------------------------------------

@responses.activate
def test_send_lark_text_http_400_raises():
    """客户端 4xx 也应抛 RuntimeError。"""
    responses.add(responses.POST, WEBHOOK, status=400, body="bad request")
    with pytest.raises(RuntimeError):
        send_lark_text(WEBHOOK, "secret", "hi")


@responses.activate
def test_send_lark_card_http_404_raises():
    responses.add(responses.POST, WEBHOOK, status=404, body="")
    with pytest.raises(RuntimeError):
        send_lark_card(WEBHOOK, "secret", CARD)


# ---------------------------------------------------------------------------
# code != 0
# ---------------------------------------------------------------------------

@responses.activate
def test_send_lark_text_nonzero_code_raises_with_msg():
    """业务 code != 0 时的错误信息应包含 code/msg。"""
    responses.add(
        responses.POST, WEBHOOK, status=200,
        json={"code": 19021, "msg": "sign check failed"},
    )
    with pytest.raises(RuntimeError) as exc_info:
        send_lark_text(WEBHOOK, "secret", "hi")
    assert "19021" in str(exc_info.value)


@responses.activate
def test_send_lark_card_nonzero_code_raises():
    responses.add(
        responses.POST, WEBHOOK, status=200,
        json={"code": 9499, "msg": "card rejected"},
    )
    with pytest.raises(RuntimeError):
        send_lark_card(WEBHOOK, "secret", CARD)


# ---------------------------------------------------------------------------
# HTTP 200 但 body 不是合法 JSON
# ---------------------------------------------------------------------------

@responses.activate
def test_send_lark_text_non_json_body_raises():
    """上游网关代理返回 200 但 body 是 HTML —— 应识别成错误而不是静默。"""
    responses.add(
        responses.POST, WEBHOOK, status=200,
        body="<html>upstream error</html>",
        content_type="text/html",
    )
    with pytest.raises(RuntimeError):
        send_lark_text(WEBHOOK, "secret", "hi")


# ---------------------------------------------------------------------------
# _post_json: code 字段缺失
# ---------------------------------------------------------------------------

@responses.activate
def test_post_json_missing_code_field_treated_as_failure():
    """响应体是 dict 但缺少 code 字段 → 视为失败（防畸形响应静默通过）。

    飞书 webhook 成功响应固定为 {"code": 0, "msg": "ok"}。
    缺少 code 字段说明响应非标准（网关错误页/代理劫持等），应报错。
    """
    responses.add(responses.POST, WEBHOOK, status=200, json={"msg": "ok"})
    with pytest.raises(RuntimeError):
        _post_json(WEBHOOK, {"msg_type": "text"}, 5)


# ---------------------------------------------------------------------------
# 入参合法性
# ---------------------------------------------------------------------------

def test_lark_sign_rejects_empty_secret():
    with pytest.raises(ValueError):
        lark_sign("", 1700000000)


def test_lark_sign_rejects_non_numeric_timestamp():
    with pytest.raises(TypeError):
        lark_sign("secret", "not-a-number")


def test_send_lark_text_rejects_empty_text():
    """空字符串 / 全空白不应被发送出去。"""
    with pytest.raises(ValueError):
        send_lark_text(WEBHOOK, "secret", "   ")


def test_send_lark_card_rejects_non_dict_card():
    with pytest.raises((ValueError, TypeError)):
        send_lark_card(WEBHOOK, "secret", "not a dict")  # type: ignore[arg-type]


def test_send_lark_card_rejects_empty_card():
    with pytest.raises(ValueError):
        send_lark_card(WEBHOOK, "secret", {})


def test_send_lark_text_rejects_invalid_webhook():
    """webhook 不以 http(s):// 开头 → ValueError。"""
    with pytest.raises(ValueError):
        send_lark_text("file:///etc/passwd", "s", "hi")


def test_send_lark_text_rejects_empty_webhook():
    with pytest.raises(ValueError):
        send_lark_text("", "s", "hi")


# ---------------------------------------------------------------------------
# 基本契约：成功路径会携带 sign 字段发送 JSON
# ---------------------------------------------------------------------------

@responses.activate
def test_send_lark_text_sends_json_with_sign():
    responses.add(responses.POST, WEBHOOK, status=200, json={"code": 0, "msg": "ok"})
    send_lark_text(WEBHOOK, "secret", "hello")
    body = json.loads(responses.calls[0].request.body)
    assert body["msg_type"] == "text"
    assert body["content"] == {"text": "hello"}
    assert "sign" in body and body["sign"]  # 非空字符串
