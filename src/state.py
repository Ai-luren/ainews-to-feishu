"""推送状态管理。

三个源（juya / aihot / builders）共享通用状态逻辑，
通过 _Source 类封装字段名差异，旧函数名保留为兼容别名。

state.json 结构（由 load_state 自动 setdefault，无需手动初始化）：
{
  "juya_pushed_date": "2026-06-14",
  "juya_failures": 0,
  "last_juya_entry_date": "2026-06-14",
  "juya_dead_alerted_on": null,
  "juya_degraded_alerted_on": null,

  "aihot_pushed_date": "2026-06-14",
  "aihot_failures": 0,
  "last_aihot_entry_date": "2026-06-14",
  "aihot_dead_alerted_on": null,

  "builders_pushed_date": "2026-06-14",
  "builders_failures": 0,
  "last_builders_entry_date": "2026-06-14",
  "builders_dead_alerted_on": null,

  # 兼容旧版（tests/test_state.py 仍在读写；新代码不使用）
  "last_pushed_date": null,
  "consecutive_failures": 0,
}
"""
import fcntl
import json
import os
import tempfile
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Any, Dict, Optional


@contextmanager
def _state_lock(path: Path):
    """排他文件锁，防止多个进程并发 read-modify-write state.json 丢失更新。

    cron-job.org 每 30 分钟触发一次，若某次执行 >30 分钟（翻译慢），
    下一次 cron 可能并发启动。不加锁会导致：
    - 失败计数丢失（两进程都读到 failures=1，都写 2，应为 3）
    - pushed_date 被覆盖，导致重复推送
    """
    lock_path = Path(path).parent / f".{Path(path).name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "w") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


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
    # builders
    data.setdefault("builders_pushed_date", None)
    data.setdefault("builders_failures", 0)
    data.setdefault("last_builders_entry_date", None)
    data.setdefault("builders_dead_alerted_on", None)
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


# ———————————— 通用工具（所有源共用）——————————— #


def _is_pushed(path: Path, key: str, today: date) -> bool:
    """读取 pushed_date；同时兼容旧字段 last_pushed_date（juya 专用）。"""
    data = load_state(path)
    if data.get(key) == today.isoformat():
        return True
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
    with _state_lock(path):
        data = load_state(path)
        data[pushed_key] = today.isoformat()
        data[failures_key] = 0
        if pushed_key == "juya_pushed_date":
            data["last_pushed_date"] = today.isoformat()
            data["consecutive_failures"] = 0
        save_state(path, data)


def _bump_failure(path: Path, key: str) -> int:
    with _state_lock(path):
        n = _bump_failure_read(path, key) + 1
        data = load_state(path)
        data[key] = n
        if key == "juya_failures":
            data["consecutive_failures"] = n
        save_state(path, data)
    return n


def _reset_failure(path: Path, key: str) -> None:
    with _state_lock(path):
        data = load_state(path)
        data[key] = 0
        if key == "juya_failures":
            data["consecutive_failures"] = 0
        save_state(path, data)


def _record_entry_date(path: Path, entry_date_key: str, dead_key: str, entry_date: date) -> None:
    with _state_lock(path):
        data = load_state(path)
        data[entry_date_key] = entry_date.isoformat()
        data[dead_key] = None  # 源头恢复 → 清除"已告警过"标记
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
    with _state_lock(path):
        data = load_state(path)
        data[alerted_key] = today.isoformat()
        save_state(path, data)


# ———————————— _Source 类：封装字段名差异 —————————— #


class _Source:
    """封装一个推送源的状态字段名，提供统一方法。"""

    def __init__(self, pushed_key: str, failures_key: str,
                 entry_date_key: str, dead_alerted_key: str):
        self.pushed_key = pushed_key
        self.failures_key = failures_key
        self.entry_date_key = entry_date_key
        self.dead_alerted_key = dead_alerted_key

    def is_pushed_today(self, path: Path, today: date) -> bool:
        return _is_pushed(path, self.pushed_key, today)

    def mark_pushed_today(self, path: Path, today: date) -> None:
        _mark_pushed(path, self.pushed_key, self.failures_key, today)

    def bump_failure(self, path: Path) -> int:
        return _bump_failure(path, self.failures_key)

    def reset_failure(self, path: Path) -> None:
        _reset_failure(path, self.failures_key)

    def record_entry_date(self, path: Path, entry_date: date) -> None:
        _record_entry_date(path, self.entry_date_key, self.dead_alerted_key, entry_date)

    def get_last_entry_date(self, path: Path) -> Optional[date]:
        return _get_last_entry_date(path, self.entry_date_key)

    def silent_days(self, path: Path, today: date) -> Optional[int]:
        last = self.get_last_entry_date(path)
        if last is None:
            return None
        return max((today - last).days, 0)

    def should_alert_dead(self, path: Path, today: date) -> bool:
        return _should_alert_dead(path, self.dead_alerted_key, today)

    def mark_dead_alerted(self, path: Path, today: date) -> None:
        _mark_dead_alerted(path, self.dead_alerted_key, today)


# 三个源的实例
_JUYA = _Source("juya_pushed_date", "juya_failures",
                "last_juya_entry_date", "juya_dead_alerted_on")
_AIHOT = _Source("aihot_pushed_date", "aihot_failures",
                 "last_aihot_entry_date", "aihot_dead_alerted_on")
_BUILDERS = _Source("builders_pushed_date", "builders_failures",
                    "last_builders_entry_date", "builders_dead_alerted_on")


# ———————————— 兼容别名（保持旧 API 不变）—————————— #
# juya
is_pushed_today = _JUYA.is_pushed_today
mark_pushed_today = _JUYA.mark_pushed_today
bump_failure = _JUYA.bump_failure
reset_failure = _JUYA.reset_failure
record_juya_entry_date = _JUYA.record_entry_date
get_last_juya_entry_date = _JUYA.get_last_entry_date
juya_silent_days = _JUYA.silent_days
should_alert_juya_dead = _JUYA.should_alert_dead
mark_juya_dead_alerted = _JUYA.mark_dead_alerted

# aihot
is_aihot_pushed_today = _AIHOT.is_pushed_today
mark_aihot_pushed_today = _AIHOT.mark_pushed_today
bump_aihot_failure = _AIHOT.bump_failure
reset_aihot_failure = _AIHOT.reset_failure
record_aihot_entry_date = _AIHOT.record_entry_date
get_last_aihot_entry_date = _AIHOT.get_last_entry_date
aihot_silent_days = _AIHOT.silent_days
should_alert_aihot_dead = _AIHOT.should_alert_dead
mark_aihot_dead_alerted = _AIHOT.mark_dead_alerted

# builders
is_builders_pushed_today = _BUILDERS.is_pushed_today
mark_builders_pushed_today = _BUILDERS.mark_pushed_today
bump_builders_failure = _BUILDERS.bump_failure
reset_builders_failure = _BUILDERS.reset_failure
record_builders_entry_date = _BUILDERS.record_entry_date
get_last_builders_entry_date = _BUILDERS.get_last_entry_date
builders_silent_days = _BUILDERS.silent_days
should_alert_builders_dead = _BUILDERS.should_alert_dead
mark_builders_dead_alerted = _BUILDERS.mark_dead_alerted


# ———————————— juya 专属：降级告警 —————————— #


def should_alert_juya_degraded(path: Path, today: date) -> bool:
    """今天是否还没发过 juya 降级告警（避免重复告警）。"""
    data = load_state(path)
    return data.get("juya_degraded_alerted_on") != today.isoformat()


def mark_juya_degraded_alerted(path: Path, today: date) -> None:
    with _state_lock(path):
        data = load_state(path)
        data["juya_degraded_alerted_on"] = today.isoformat()
        save_state(path, data)
