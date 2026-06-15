"""aihot 状态函数测试。"""
import json
from datetime import date
from pathlib import Path

import pytest

from state import (
    aihot_silent_days,
    bump_aihot_failure,
    get_last_aihot_entry_date,
    is_aihot_pushed_today,
    mark_aihot_dead_alerted,
    mark_aihot_pushed_today,
    record_aihot_entry_date,
    reset_aihot_failure,
    should_alert_aihot_dead,
)


@pytest.fixture
def state_path(tmp_path: Path) -> Path:
    return tmp_path / "state.json"


def test_is_aihot_pushed_today_false_initial(state_path: Path):
    """初始状态未推送。"""
    assert not is_aihot_pushed_today(state_path, date(2026, 6, 15))


def test_mark_aihot_pushed_today(state_path: Path):
    """标记推送后能正确读取。"""
    today = date(2026, 6, 15)
    mark_aihot_pushed_today(state_path, today)
    assert is_aihot_pushed_today(state_path, today)
    # 其他日期不算
    assert not is_aihot_pushed_today(state_path, date(2026, 6, 14))


def test_aihot_failure_count(state_path: Path):
    """失败计数独立累加。"""
    n1 = bump_aihot_failure(state_path)
    assert n1 == 1
    n2 = bump_aihot_failure(state_path)
    assert n2 == 2
    reset_aihot_failure(state_path)
    data = json.loads(state_path.read_text())
    assert data["aihot_failures"] == 0


def test_aihot_entry_date(state_path: Path):
    """记录 aihot 条目日期。"""
    record_aihot_entry_date(state_path, date(2026, 6, 15))
    assert get_last_aihot_entry_date(state_path) == date(2026, 6, 15)


def test_aihot_silent_days(state_path: Path):
    """计算 aihot 停更天数。"""
    record_aihot_entry_date(state_path, date(2026, 6, 10))
    silent = aihot_silent_days(state_path, date(2026, 6, 15))
    assert silent == 5


def test_aihot_dead_alert(state_path: Path):
    """aihot 停更告警去重。"""
    today = date(2026, 6, 15)
    # 第一次需要告警
    assert should_alert_aihot_dead(state_path, today)
    # 标记已告警
    mark_aihot_dead_alerted(state_path, today)
    # 同一天不再告警
    assert not should_alert_aihot_dead(state_path, today)
    # 第二天又需要告警
    assert should_alert_aihot_dead(state_path, date(2026, 6, 16))


def test_aihot_state_independent_from_juya(state_path: Path):
    """aihot 和 juya 状态独立。"""
    today = date(2026, 6, 15)

    # 标记 juya 推送
    from state import mark_pushed_today, is_pushed_today
    mark_pushed_today(state_path, today)
    assert is_pushed_today(state_path, today)

    # aihot 未推送
    assert not is_aihot_pushed_today(state_path, today)

    # 标记 aihot 推送
    mark_aihot_pushed_today(state_path, today)
    assert is_aihot_pushed_today(state_path, today)

    # 两者独立
    data = json.loads(state_path.read_text())
    assert data["juya_pushed_date"] == today.isoformat()
    assert data["aihot_pushed_date"] == today.isoformat()


def test_record_aihot_entry_clears_dead_alert(state_path: Path):
    """aihot 恢复更新后清除停更告警标记。"""
    today = date(2026, 6, 15)
    mark_aihot_dead_alerted(state_path, today)

    # 记录新条目
    record_aihot_entry_date(state_path, date(2026, 6, 16))

    data = json.loads(state_path.read_text())
    assert data["aihot_dead_alerted_on"] is None
