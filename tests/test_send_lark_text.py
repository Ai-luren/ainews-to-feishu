import json
import responses
from lark import send_lark_text

WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/abc"
SECRET = "sec"


@responses.activate
def test_send_lark_text_success():
    responses.add(
        responses.POST,
        WEBHOOK,
        json={"code": 0, "msg": "ok"},
        status=200,
    )
    send_lark_text(WEBHOOK, SECRET, "hello")

    assert len(responses.calls) == 1
    body = json.loads(responses.calls[0].request.body)
    assert body["msg_type"] == "text"
    assert body["content"]["text"] == "hello"
    assert "timestamp" in body
    assert "sign" in body


@responses.activate
def test_send_lark_text_raises_on_lark_error():
    responses.add(
        responses.POST,
        WEBHOOK,
        json={"code": 19021, "msg": "sign verification failed"},
        status=200,
    )
    import pytest
    with pytest.raises(RuntimeError, match="sign verification failed"):
        send_lark_text(WEBHOOK, SECRET, "hello")


@responses.activate
def test_send_lark_text_raises_on_http_error():
    responses.add(
        responses.POST,
        WEBHOOK,
        json={"error": "nope"},
        status=500,
    )
    import pytest
    with pytest.raises(RuntimeError):
        send_lark_text(WEBHOOK, SECRET, "hello")
