"""每日推送主流程。

顺序：aihot 先，juya 后。两个源独立去重/告警。
"""
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytz

from aihot import AIHOT_BASE_URL, daily_date, fetch_daily, has_content, total_items
from aihot_card import parse_daily_to_card
from lark import send_lark_card, send_lark_text
from lark_card import parse_entry_to_card
from rss import extract_today_entry, fetch_rss
from state import (
    aihot_silent_days, bump_aihot_failure, bump_failure,
    get_last_aihot_entry_date, get_last_juya_entry_date,
    is_aihot_pushed_today, is_pushed_today,
    juya_silent_days,
    mark_aihot_dead_alerted, mark_aihot_pushed_today,
    mark_juya_dead_alerted, mark_pushed_today,
    record_aihot_entry_date, record_juya_entry_date,
    reset_aihot_failure, reset_failure,
    should_alert_aihot_dead, should_alert_juya_dead,
)

BEIJING = pytz.timezone("Asia/Shanghai")
STATE_PATH = Path(__file__).parent / "state.json"
DEAD_THRESHOLD = 3

REQUIRED_ENVS = ["LARK_WEBHOOK_URL", "LARK_WEBHOOK_SECRET",
                  "LARK_OPS_WEBHOOK_URL", "LARK_OPS_WEBHOOK_SECRET"]


def _log(msg: str, err: bool = False) -> None:
    print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def _today() -> date:
    override = os.environ.get("PUSH_TARGET_DATE", "").strip()
    if override:
        try:
            return datetime.strptime(override, "%Y-%m-%d").date()
        except ValueError as e:
            _log(f"[error] PUSH_TARGET_DATE 非法: {e}", err=True)
            sys.exit(2)
    return datetime.now(BEIJING).date()


def _is_backfill() -> bool:
    return bool(os.environ.get("PUSH_TARGET_DATE", "").strip())


def _check_env() -> None:
    missing = [k for k in REQUIRED_ENVS if not os.environ.get(k)]
    if missing:
        _log(f"[error] 缺少环境变量: {', '.join(missing)}", err=True)
        sys.exit(2)


def _alert(ops_webhook: str, ops_secret: str, text: str) -> None:
    try:
        send_lark_text(ops_webhook, ops_secret, text)
    except Exception as e:
        _log(f"[warn] ops alert failed: {e}", err=True)


def _push_juya(webhook: str, secret: str, ops_webhook: str, ops_secret: str,
               today: date, backfill: bool) -> bool:
    """推送 juya，返回 True=正常结束，False=失败"""
    # 去重
    if not backfill and is_pushed_today(STATE_PATH, today):
        _log(f"[juya] [skip] already pushed today ({today})")
        return True
    if backfill and today == datetime.now(BEIJING).date() and is_pushed_today(STATE_PATH, today):
        _log("[juya] [skip] backfill 今天已推送")
        return True

    # 拉取
    try:
        entry = extract_today_entry(fetch_rss(), today=today)
    except Exception as e:
        _log(f"[juya] [warn] fetch failed: {e}", err=True)
        if backfill:
            return False
        n = bump_failure(STATE_PATH)
        if n >= 3:
            _alert(ops_webhook, ops_secret, f"⚠️ juya 连续 {n} 次拉取失败\n错误: {e}")
            reset_failure(STATE_PATH)
        return False

    # 无内容
    if entry is None:
        _log(f"[juya] [skip] not updated for {today}")
        if not backfill:
            silent = juya_silent_days(STATE_PATH, today)
            if silent and silent >= DEAD_THRESHOLD and should_alert_juya_dead(STATE_PATH, today):
                last = get_last_juya_entry_date(STATE_PATH)
                _alert(ops_webhook, ops_secret,
                       f"⚠️ juya 连续 {silent} 天未更新（最后: {last}）\nhttps://daily.juya.uk/")
                mark_juya_dead_alerted(STATE_PATH, today)
        return True

    # 记录日期
    pub_dt = entry.get("published_dt")
    if isinstance(pub_dt, datetime) and not backfill:
        record_juya_entry_date(STATE_PATH, pub_dt.astimezone(BEIJING).date())

    # 渲染推送
    try:
        card = parse_entry_to_card(entry)
        if card is None:
            title = entry.get("title") or "<untitled>"
            link = entry.get("link") or "#"
            send_lark_text(webhook, secret, f"🤖 橘鸦 AI 早报 · {title}\n（解析降级）\n{link}")
            if not backfill:
                mark_pushed_today(STATE_PATH, today)
            _alert(ops_webhook, ops_secret, "⚠️ juya 内容解析降级")
            _log(f"[juya] [ok] pushed (degraded) {today}")
            return True

        send_lark_card(webhook, secret, card)
        if not backfill:
            mark_pushed_today(STATE_PATH, today)
        _log(f"[juya] [ok] pushed {today}")
        return True

    except Exception as e:
        if backfill:
            _log(f"[juya] [fail] backfill: {e}", err=True)
            return False
        n = bump_failure(STATE_PATH)
        _log(f"[juya] [fail] ({n}/3): {e}", err=True)
        if n >= 3:
            _alert(ops_webhook, ops_secret, f"⚠️ juya 推送连续 {n} 次失败\n错误: {e}")
            reset_failure(STATE_PATH)
        return False


def _push_aihot(webhook: str, secret: str, ops_webhook: str, ops_secret: str,
                today: date, backfill: bool) -> bool:
    """推送 aihot，返回 True=正常结束，False=失败"""
    # 去重
    if not backfill and is_aihot_pushed_today(STATE_PATH, today):
        _log(f"[aihot] [skip] already pushed today ({today})")
        return True
    if backfill and today == datetime.now(BEIJING).date() and is_aihot_pushed_today(STATE_PATH, today):
        _log("[aihot] [skip] backfill 今天已推送")
        return True

    # 拉取
    try:
        daily = fetch_daily(today)
    except Exception as e:
        _log(f"[aihot] [warn] fetch failed: {e}", err=True)
        if backfill:
            return False
        n = bump_aihot_failure(STATE_PATH)
        if n >= 3:
            _alert(ops_webhook, ops_secret, f"⚠️ aihot 连续 {n} 次拉取失败\n错误: {e}")
            reset_aihot_failure(STATE_PATH)
        return False

    # 无内容时尝试最新一期
    if not has_content(daily):
        try:
            daily = fetch_daily()
        except Exception:
            daily = None

    if not has_content(daily):
        _log(f"[aihot] [skip] no content for {today}")
        if not backfill:
            silent = aihot_silent_days(STATE_PATH, today)
            if silent and silent >= DEAD_THRESHOLD and should_alert_aihot_dead(STATE_PATH, today):
                last = get_last_aihot_entry_date(STATE_PATH)
                _alert(ops_webhook, ops_secret,
                       f"⚠️ aihot 连续 {silent} 天未更新（最后: {last}）\n{AIHOT_BASE_URL}/")
                mark_aihot_dead_alerted(STATE_PATH, today)
        return True

    # 记录日期
    entry_date = daily_date(daily)
    if entry_date and not backfill:
        record_aihot_entry_date(STATE_PATH, entry_date)

    # 渲染推送
    try:
        card = parse_daily_to_card(daily)
        if card is None:
            d = daily_date(daily) or today
            send_lark_text(webhook, secret, f"🔥 AI HOT 日报 · {d}\n（解析降级）\n{AIHOT_BASE_URL}/")
            if not backfill:
                mark_aihot_pushed_today(STATE_PATH, today)
            _alert(ops_webhook, ops_secret, "⚠️ aihot 内容解析降级")
            _log(f"[aihot] [ok] pushed (degraded) {today}")
            return True

        send_lark_card(webhook, secret, card)
        if not backfill:
            mark_aihot_pushed_today(STATE_PATH, today)
        _log(f"[aihot] [ok] pushed {today} ({total_items(daily)} 条)")
        return True

    except Exception as e:
        if backfill:
            _log(f"[aihot] [fail] backfill: {e}", err=True)
            return False
        n = bump_aihot_failure(STATE_PATH)
        _log(f"[aihot] [fail] ({n}/3): {e}", err=True)
        if n >= 3:
            _alert(ops_webhook, ops_secret, f"⚠️ aihot 推送连续 {n} 次失败\n错误: {e}")
            reset_aihot_failure(STATE_PATH)
        return False


def main() -> int:
    _check_env()
    webhook = os.environ["LARK_WEBHOOK_URL"]
    secret = os.environ["LARK_WEBHOOK_SECRET"]
    ops_webhook = os.environ["LARK_OPS_WEBHOOK_URL"]
    ops_secret = os.environ["LARK_OPS_WEBHOOK_SECRET"]

    today = _today()
    backfill = _is_backfill()
    _log(f"[meta] today={today} backfill={backfill}")

    aihot_ok = _push_aihot(webhook, secret, ops_webhook, ops_secret, today, backfill)
    juya_ok = _push_juya(webhook, secret, ops_webhook, ops_secret, today, backfill)

    if aihot_ok and juya_ok:
        _log("[meta] all completed")
        return 0
    _log("[meta] some failed", err=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
