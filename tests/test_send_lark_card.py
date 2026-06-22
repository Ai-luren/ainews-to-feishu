import json
import responses
from lark import send_lark_card

WEBHOOK = "https://open.feishu.cn/open-apis/bot/v2/hook/xyz"
SECRET = "sec"


@responses.activate
def test_send_lark_card_success():
    responses.add(responses.POST, WEBHOOK, json={"code": 0, "msg": "ok"}, status=200)
    card = {"header": {}, "elements": []}
    send_lark_card(WEBHOOK, SECRET, card)

    body = json.loads(responses.calls[0].request.body)
    assert body["msg_type"] == "interactive"
    assert body["card"] == card
    assert "timestamp" in body and "sign" in body


@responses.activate
def test_send_lark_card_raises_on_error():
    responses.add(responses.POST, WEBHOOK, json={"code": 9499, "msg": "bad card"}, status=200)
    import pytest
    with pytest.raises(RuntimeError, match="bad card"):
        send_lark_card(WEBHOOK, SECRET, {"header": {}, "elements": []})
