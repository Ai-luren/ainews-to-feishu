from lark import lark_sign


def test_lark_sign_known_vector():
    # Known vector: timestamp=1609459200, secret="test_secret"
    # Algorithm (per Feishu official): key=f"{timestamp}\n{secret}", msg=empty, HMAC-SHA256 -> base64
    result = lark_sign("test_secret", 1609459200)
    assert result == "qVbqb8D2J+M/bRkXvbE6oxwqeW951L1/HLlrNo1pY0g="


def test_lark_sign_returns_base64_str():
    result = lark_sign("any_secret", 1700000000)
    assert isinstance(result, str)
    assert "\n" not in result and " " not in result
