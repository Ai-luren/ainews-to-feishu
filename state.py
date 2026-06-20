"""推送状态管理。

2026-06-15 后系统同时维护 juya 和 aihot 两个独立推送流程，
状态字段按"源"拆分，互不影响。

state.json 结构（由 load_state 自动 setdefault，无需手动初始化）：
{
  "juya_pushed_date": "2026-06-14",        # juya 最后一次推送日期
  "juya_failures": 0,                       # juya 连续失败次数
  "last_juya_entry_date": "2026-06-14",     # juya feed 最新一期日期
  "juya_dead_alerted_on": null,             # juya 停更告警发过的日期
  "juya_degraded_alerted_on": null,         # juya 降级告警发过的日期

  "aihot_pushed_date": "2026-06-14",        # aihot 最后一次推送日期
  "aihot_failures": 0,                      # aihot 连续失败次数
  "last_aihot_entry_date": "2026-06-14",    # aihot 最新一期日期
  "aihot_dead_alerted_on": null,            # aihot 停更告警发过的日期

  # 兼容旧版（tests/test_state.py 仍在读写；新代码不使用）
  "last_pushed_date": null,
  "consecutive_failures": 0,
}
"""
import json
import os
import tempfile
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional


def load_state(path: Path) -> Dict[str, Any]:
    """加载 state.json。空文件 / 格式错误 / 非 dict / 不存在时回退到空 dict。

    所有已知字段都会 setdefault，所以任何"老的 state.json"读出来都有完整键。
    """
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raw = ""
    except OSError as e:
        print(f"[warn] state.json 读失败：{e}", flush=True)
        raw = ""

    if not raw.strip():
        data: Dict[str, Any] = {}
    else:
        try:
            data = json.loads(raw)
            if not isinstance(data, dict):
                print(f"[warn] state.json 顶层不是 dict（是 {type(data).__name__}），重置",
                      flush=True)
                data = {}
        except (json.JSONDecodeError, ValueError) as e:
            print(f"[warn] state.json 解析失败：{e}", flush=True)
            data = {}

    # juya
    data.setdefault("juya_pushed_date", None)
    data.setdefault("juya_failures", 0)
    data.setdefault("last_juya_entry_date", None)
    data.setdefault("juya_dead_alerted_on", None)
    data.setdefault("juya_degraded_alerted_on", None)
    # aihot
    data.setdefault("aihot_pushed_date", None)
    data.setdefault("aihot_failures", 0)
    data.setdefault("last_aihot_entry_date", None)
    data.setdefault("aihot_dead_alerted_on", None)
    # 兼容旧字段
    data.setdefault("last_pushed_date", None)
    data.setdefault("consecutive_failures", 0)
    return data


def save_state(path: Path, data: Dict[str, Any]) -> None:
    """原子写入：先写临时文件，再用 os.replace 交换，保证不会半截写入。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    fd, tmp_path = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(serialized)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# ———————————— 通用工具（两个源共用）——————————— #


def _is_pushed(path: Path, key: str, today: date) -> bool:
    """读取 pushed_date；同时兼容旧字段 last_pushed_date（juya 专用）。"""
    data = load_state(path)
    if data.get(key) == today.isoformat():
        return True
    # 向后兼容：旧 state.json 可能只有 last_pushed_date
    if key == "juya_pushed_date" and data.get("last_pushed_date") == today.isoformat():
        return True
    return False


def _bump_failure_read(path: Path, key: str) -> int:
    """读 failures；兼容旧字段 consecutive_failures（juya 专用）。"""
    data = load_state(path)
    try:
        n = int(data.get(key, 0))
    except (TypeError, ValueError):
        n = 0
    if n == 0 and key == "juya_failures":
        try:
            n = int(data.get("consecutive_failures", 0))
        except (TypeError, ValueError):
            n = 0
    return n


def _mark_pushed(path: Path, pushed_key: str, failures_key: str, today: date) -> None:
    data = load_state(path)
    data[pushed_key] = today.isoformat()
    data[failures_key] = 0
    # 写回兼容旧字段（给 test_state.py 用；新代码不会依赖）
    if pushed_key == "juya_pushed_date":
        data["last_pushed_date"] = today.isoformat()
        data["consecutive_failures"] = 0
    save_state(path, data)


def _bump_failure(path: Path, key: str) -> int:
    n = _bump_failure_read(path, key) + 1
    data = load_state(path)
    data[key] = n
    # 写回兼容旧字段
    if key == "juya_failures":
        data["consecutive_failures"] = n
    save_state(path, data)
    return n


def _reset_failure(path: Path, key: str) -> None:
    data = load_state(path)
    data[key] = 0
    if key == "juya_failures":
        data["consecutive_failures"] = 0
    save_state(path, data)


def _record_entry_date(path: Path, key: str, entry_date: date) -> None:
    data = load_state(path)
    data[key] = entry_date.isoformat()
    save_state(path, data)


def _get_last_entry_date(path: Path, key: str) -> Optional[date]:
    data = load_state(path)
    d = data.get(key)
    if not d:
        return None
    try:
        return date.fromisoformat(str(d))
    except ValueError:
        return None


def _should_alert_dead(path: Path, alerted_key: str, today: date) -> bool:
    data = load_state(path)
    return data.get(alerted_key) != today.isoformat()


def _mark_dead_alerted(path: Path, alerted_key: str, today: date) -> None:
    data = load_state(path)
    data[alerted_key] = today.isoformat()
    save_state(path, data)


# ———————————— juya 专用（保持旧 API 兼容）——————————— #


def is_pushed_today(path: Path, today: date) -> bool:
    """juya 是否已推送过今天（旧 API 名，测试依赖）。"""
    return _is_pushed(path, "juya_pushed_date", today)


def mark_pushed_today(path: Path, today: date) -> None:
    """juya 标记已推送（旧 API 名，测试依赖，兼写旧字段）。"""
    _mark_pushed(path, "juya_pushed_date", "juya_failures", today)


def bump_failure(path: Path) -> int:
    """juya 失败 +1（旧 API 名，测试依赖，兼写旧字段）。"""
    return _bump_failure(path, "juya_failures")


def reset_failure(path: Path) -> None:
    """juya 清零失败（旧 API 名，测试依赖，兼写旧字段）。"""
    _reset_failure(path, "juya_failures")


def record_juya_entry_date(path: Path, entry_date: date) -> None:
    data = load_state(path)
    data["last_juya_entry_date"] = entry_date.isoformat()
    # 源头恢复 → 清除"已告警过"标记，下次再停更时能重新告警
    data["juya_dead_alerted_on"] = None
    save_state(path, data)


def get_last_juya_entry_date(path: Path) -> Optional[date]:
    return _get_last_entry_date(path, "last_juya_entry_date")


def juya_silent_days(path: Path, today: date) -> Optional[int]:
    last = get_last_juya_entry_date(path)
    if last is None:
        return None
    return max((today - last).days, 0)


def should_alert_juya_dead(path: Path, today: date) -> bool:
    return _should_alert_dead(path, "juya_dead_alerted_on", today)


def mark_juya_dead_alerted(path: Path, today: date) -> None:
    _mark_dead_alerted(path, "juya_dead_alerted_on", today)


def should_alert_juya_degraded(path: Path, today: date) -> bool:
    """今天是否还没发过 juya 降级告警（避免重复告警）。"""
    data = load_state(path)
    return data.get("juya_degraded_alerted_on") != today.isoformat()


def mark_juya_degraded_alerted(path: Path, today: date) -> None:
    data = load_state(path)
    data["juya_degraded_alerted_on"] = today.isoformat()
    save_state(path, data)


# ———————————— aihot 专用（新增）——————————— #


def is_aihot_pushed_today(path: Path, today: date) -> bool:
    return _is_pushed(path, "aihot_pushed_date", today)


def mark_aihot_pushed_today(path: Path, today: date) -> None:
    _mark_pushed(path, "aihot_pushed_date", "aihot_failures", today)


def bump_aihot_failure(path: Path) -> int:
    return _bump_failure(path, "aihot_failures")


def reset_aihot_failure(path: Path) -> None:
    _reset_failure(path, "aihot_failures")


def record_aihot_entry_date(path: Path, entry_date: date) -> None:
    data = load_state(path)
    data["last_aihot_entry_date"] = entry_date.isoformat()
    data["aihot_dead_alerted_on"] = None
    save_state(path, data)


def get_last_aihot_entry_date(path: Path) -> Optional[date]:
    return _get_last_entry_date(path, "last_aihot_entry_date")


def aihot_silent_days(path: Path, today: date) -> Optional[int]:
    last = get_last_aihot_entry_date(path)
    if last is None:
        return None
    return max((today - last).days, 0)


def should_alert_aihot_dead(path: Path, today: date) -> bool:
    return _should_alert_dead(path, "aihot_dead_alerted_on", today)


def mark_aihot_dead_alerted(path: Path, today: date) -> None:
    _mark_dead_alerted(path, "aihot_dead_alerted_on", today)
