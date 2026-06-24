import base64
import hashlib
import hmac
import json
import time
from typing import Any, Mapping

import requests

USER_AGENT = "ainews-to-feishu/1.0 (+https://github.com/ainews-to-feishu)"

# 飞书 webhook 频率限制：同一 webhook 1 分钟内最多 5 条消息。
# 超过会返回 code=11232 msg="frequency limited"。
# 限流后等待 30 秒重试，最多重试 2 次。
_RATE_LIMIT_CODE = 11232
_RATE_LIMIT_RETRIES = 2
_RATE_LIMIT_WAIT = 30  # 秒


def _session() -> requests.Session:
    """单次 HTTP session（不做 POST 自动重试，避免非幂等请求重复推送）。"""
    s = requests.Session()
    s.headers["User-Agent"] = USER_AGENT
    return s


def lark_sign(secret: str, timestamp: int) -> str:
    """飞书自定义机器人签名。

    算法（按飞书官方）：key = f"{timestamp}\n{secret}"，msg 为空，HMAC-SHA256 → base64。

    防御：
    - timestamp 必须是整数秒。传 float 会拼出 "1609459200.0" 导致签名失败。
    - secret 为空会退化为固定哈希（不安全），显式拒绝。
    """
    if not isinstance(timestamp, (int, float)):
        raise TypeError(f"timestamp must be int/float, got {type(timestamp).__name__}")
    if not secret:
        raise ValueError("secret must not be empty")
    # 强制整数化，防止误传 time.time()（float）时签名静默出错
    ts_int = int(timestamp)
    key = f"{ts_int}\n{secret}".encode("utf-8")
    digest = hmac.new(
        key=key,
        msg=b"",
        digestmod=hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("utf-8")


def _post_json(webhook: str, payload: Mapping[str, Any], timeout: int) -> Mapping[str, Any]:
    """共用的飞书 webhook POST：处理非 200 / 非 JSON / 业务 code != 0 三种失败。

    遇到频率限制（code=11232）时自动等待 30 秒重试，最多重试 2 次。
    """
    if not webhook or not webhook.startswith(("http://", "https://")):
        raise ValueError(f"invalid webhook (scheme not http/https, got: {webhook[:30]!r}...)")

    for attempt in range(_RATE_LIMIT_RETRIES + 1):
        try:
            with _session() as s:
                resp = s.post(webhook, json=payload, timeout=timeout)
        except UnicodeEncodeError as e:
            # 偶发：requests/urllib3 在处理响应 header 时遇到非 ASCII 字符
            # 重试一次通常能成功
            if attempt < _RATE_LIMIT_RETRIES:
                print(f"[lark] UnicodeEncodeError, 重试 ({attempt+1}/{_RATE_LIMIT_RETRIES}): {e}", flush=True)
                time.sleep(2)
                continue
            raise RuntimeError(f"lark 请求编码错误（重试已用完）: {e}") from e
        if resp.status_code != 200:
            raise RuntimeError(f"lark http {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()
        except json.JSONDecodeError as e:
            raise RuntimeError(f"lark 响应不是 JSON（http 200 但 body={resp.text[:200]!r}）") from e

        if not isinstance(data, dict) or data.get("code", 0) != 0:
            # 频率限制：等待后重试
            if data.get("code") == _RATE_LIMIT_CODE and attempt < _RATE_LIMIT_RETRIES:
                print(f"[lark] 频率限制，{_RATE_LIMIT_WAIT}s 后重试 ({attempt+1}/{_RATE_LIMIT_RETRIES})", flush=True)
                time.sleep(_RATE_LIMIT_WAIT)
                continue
            raise RuntimeError(f"lark error code={data.get('code')} msg={data.get('msg')}")
        return data

    raise RuntimeError("lark 频率限制，重试次数已用完")


def send_lark_text(webhook: str, secret: str, text: str, timeout: int = 10) -> None:
    """推一条纯文本到飞书自定义机器人。失败抛 RuntimeError。"""
    if not isinstance(text, str) or not text.strip():
        raise ValueError("text must be a non-empty string")
    timestamp = int(time.time())
    payload: Mapping[str, Any] = {
        "timestamp": str(timestamp),
        "sign": lark_sign(secret, timestamp),
        "msg_type": "text",
        "content": {"text": text},
    }
    _post_json(webhook, payload, timeout)


def send_lark_card(webhook: str, secret: str, card: Mapping[str, Any], timeout: int = 10) -> None:
    """推一张 interactive 卡片到飞书。失败抛 RuntimeError。"""
    if not isinstance(card, dict) or not card:
        raise ValueError("card must be a non-empty dict")
    timestamp = int(time.time())
    payload: Mapping[str, Any] = {
        "timestamp": str(timestamp),
        "sign": lark_sign(secret, timestamp),
        "msg_type": "interactive",
        "card": card,
    }
    _post_json(webhook, payload, timeout)
