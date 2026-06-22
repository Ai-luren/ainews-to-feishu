"""补充测试：state.load_state 兜底场景 + juya 死亡检测相关函数。

原 test_state.py 只覆盖了 is_pushed_today / mark_pushed_today / bump_failure / reset_failure
四个主流程函数；未覆盖：
  - load_state: 空文件 / 坏 JSON / 非 dict / 文件不存在
  - save_state: 原子写入契约
  - record_juya_entry_date / get_last_juya_entry_date / juya_silent_days
  - should_alert_juya_dead / mark_juya_dead_alerted
"""

import json
from datetime import date
from pathlib import Path

from state import (
    get_last_juya_entry_date,
    is_pushed_today,
    juya_silent_days,
    load_state,
    mark_juya_dead_alerted,
    mark_pushed_today,
    record_juya_entry_date,
    reset_failure,
    save_state,
    should_alert_juya_dead,
)


# ---------------------------------------------------------------------------
# load_state: 各种兜底场景
# ---------------------------------------------------------------------------

def test_load_state_empty_file_returns_defaults(tmp_path):
    """空文件 → 返回带默认字段的 dict，不抛异常。"""
    p = tmp_path / "state.json"
    p.write_text("")
    data = load_state(p)
    assert isinstance(data, dict)
    assert data["last_pushed_date"] is None
    assert data["consecutive_failures"] == 0
    assert data["last_juya_entry_date"] is None
    assert data["juya_dead_alerted_on"] is None


def test_load_state_whitespace_only_file(tmp_path):
    """仅包含空白的文件——与空文件等价处理。"""
    p = tmp_path / "state.json"
    p.write_text("   \n\t\n")
    data = load_state(p)
    assert isinstance(data, dict)
    assert data["consecutive_failures"] == 0


def test_load_state_invalid_json_returns_defaults(tmp_path):
    """内容不是合法 JSON → 回退空 dict 并补默认字段。"""
    p = tmp_path / "state.json"
    p.write_text("{ not valid json here")
    data = load_state(p)
    assert isinstance(data, dict)
    assert data["last_pushed_date"] is None


def test_load_state_non_dict_json_returns_defaults(tmp_path):
    """JSON 顶层是 list / int / string 而不是 dict → 回退空 dict。"""
    p = tmp_path / "state.json"
    for bad in ["[1, 2, 3]", "\"hello\"", "42", "null", "true"]:
        p.write_text(bad)
        data = load_state(p)
        assert isinstance(data, dict), f"类型为 {bad!r} 时也应回退 dict"
        assert data["consecutive_failures"] == 0


def test_load_state_missing_file_returns_defaults(tmp_path):
    """文件不存在 → 行为与空文件一致（不抛 FileNotFoundError）。"""
    p = tmp_path / "does-not-exist.json"
    data = load_state(p)
    assert isinstance(data, dict)
    assert data["last_pushed_date"] is None


def test_load_state_preserves_existing_fields(tmp_path):
    """合法 dict JSON → 字段被保留，缺失字段用默认值补齐。"""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_pushed_date": "2026-04-27", "extra": "ok"}))
    data = load_state(p)
    assert data["last_pushed_date"] == "2026-04-27"
    assert data["consecutive_failures"] == 0   # 缺失 → 默认 0
    assert data["last_juya_entry_date"] is None
    assert data["juya_dead_alerted_on"] is None
    assert data["extra"] == "ok"               # 已有字段保留


# ---------------------------------------------------------------------------
# save_state: 原子写入契约
# ---------------------------------------------------------------------------

def test_save_state_writes_valid_json(tmp_path):
    p = tmp_path / "state.json"
    save_state(p, {"last_pushed_date": "2026-04-27", "consecutive_failures": 7})
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["last_pushed_date"] == "2026-04-27"
    assert data["consecutive_failures"] == 7


def test_save_state_creates_parent_dir(tmp_path):
    """父目录不存在时应被自动创建（state.py 内部 mkdir(parents=True)）。"""
    p = tmp_path / "nested" / "state.json"
    save_state(p, {"last_pushed_date": None, "consecutive_failures": 0})
    assert p.exists()


# ---------------------------------------------------------------------------
# juya 源死亡检测相关辅助函数
# ---------------------------------------------------------------------------

def test_record_and_get_last_juya_entry_date(tmp_path):
    """record_juya_entry_date 应写入 ISO 日期；get_last 返回 date 对象。"""
    p = tmp_path / "state.json"
    p.write_text("{}")
    record_juya_entry_date(p, date(2026, 4, 27))
    assert get_last_juya_entry_date(p) == date(2026, 4, 27)


def test_record_juya_entry_date_resets_dead_alert_flag(tmp_path):
    """源头恢复（有新条目）时应把"已告警过"标记清除，否则再停更时不会再告警。"""
    p = tmp_path / "state.json"
    p.write_text(json.dumps({
        "juya_dead_alerted_on": "2026-04-20",
    }))
    record_juya_entry_date(p, date(2026, 4, 27))
    data = json.loads(p.read_text())
    assert data["juya_dead_alerted_on"] is None


def test_get_last_juya_entry_date_returns_none_when_unset(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{}")
    assert get_last_juya_entry_date(p) is None


def test_get_last_juya_entry_date_returns_none_when_invalid(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_juya_entry_date": "not-a-date"}))
    assert get_last_juya_entry_date(p) is None


def test_juya_silent_days_computes_delta(tmp_path):
    p = tmp_path / "state.json"
    p.write_text(json.dumps({"last_juya_entry_date": "2026-04-20"}))
    assert juya_silent_days(p, today=date(2026, 4, 27)) == 7


def test_juya_silent_days_returns_none_when_never_observed(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{}")
    assert juya_silent_days(p, today=date(2026, 4, 27)) is None


def test_should_alert_and_mark_juya_dead_alerted(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{}")
    today = date(2026, 4, 27)
    assert should_alert_juya_dead(p, today) is True
    mark_juya_dead_alerted(p, today)
    assert should_alert_juya_dead(p, today) is False   # 同一天不再告警
    assert should_alert_juya_dead(p, date(2026, 4, 28)) is True  # 第二天可以再次告警
