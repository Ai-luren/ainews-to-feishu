import json
from datetime import date
from state import (
    is_pushed_today,
    mark_pushed_today,
    bump_failure,
    reset_failure,
)


def test_is_pushed_today_false_when_null(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 0}))
    assert is_pushed_today(path, today=date(2026, 4, 27)) is False


def test_is_pushed_today_true_when_match(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_pushed_date": "2026-04-27", "consecutive_failures": 0}))
    assert is_pushed_today(path, today=date(2026, 4, 27)) is True


def test_mark_pushed_today_writes_iso_date(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 3}))
    mark_pushed_today(path, today=date(2026, 4, 27))
    data = json.loads(path.read_text())
    assert data["last_pushed_date"] == "2026-04-27"
    assert data["consecutive_failures"] == 0  # 推成功清零


def test_bump_failure_increments(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 2}))
    n = bump_failure(path)
    assert n == 3
    assert json.loads(path.read_text())["consecutive_failures"] == 3


def test_reset_failure(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"last_pushed_date": None, "consecutive_failures": 5}))
    reset_failure(path)
    assert json.loads(path.read_text())["consecutive_failures"] == 0
