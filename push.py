"""每日推送主流程。

顺序：
  1. 推 juya 日报（橘鸦 AI 早报）
  2. 推 aihot 日报（AI HOT 日报）

两个流程相互独立：
  - 各自维护 pushed_date（不重复）
  - 各自维护 consecutive_failures（独立告警）
  - 各自维护 last_entry_date（独立停更告警）
  - 一个失败不影响另一个

启动方式：
  - 正常：`python push.py` → 推"今天"
  - backfill：`PUSH_TARGET_DATE=2026-06-13 python push.py` → 推指定日期
    （用于补发，不会写入 pushed_date，可反复跑）
"""
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytz

from aihot import (
    AIHOT_BASE_URL,
    daily_date,
    fetch_daily,
    has_content as aihot_has_content,
    total_items,
)
from aihot_card import parse_daily_to_card as aihot_to_card
from lark import send_lark_card, send_lark_text
from lark_card import parse_entry_to_card
from rss import extract_today_entry, fetch_rss
from state import (
    aihot_silent_days,
    bump_aihot_failure,
    bump_failure,
    get_last_aihot_entry_date,
    get_last_juya_entry_date,
    is_aihot_pushed_today,
    is_pushed_today,
    juya_silent_days,
    mark_aihot_dead_alerted,
    mark_aihot_pushed_today,
    mark_juya_dead_alerted,
    mark_pushed_today,
    record_aihot_entry_date,
    record_juya_entry_date,
    reset_aihot_failure,
    reset_failure,
    should_alert_aihot_dead,
    should_alert_juya_dead,
)

DEAD_THRESHOLD_DAYS = 3

BEIJING = pytz.timezone("Asia/Shanghai")
STATE_PATH = Path(__file__).parent / "state.json"

REQUIRED_ENVS = [
    "LARK_WEBHOOK_URL",
    "LARK_WEBHOOK_SECRET",
    "LARK_OPS_WEBHOOK_URL",
    "LARK_OPS_WEBHOOK_SECRET",
]


def _log(msg: str, *, err: bool = False) -> None:
    print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def _today() -> date:
    """返回"今天"。PUSH_TARGET_DATE 可覆盖（用于 backfill）。"""
    override = os.environ.get("PUSH_TARGET_DATE", "").strip()
    if override:
        try:
            return datetime.strptime(override, "%Y-%m-%d").date()
        except ValueError as exc:
            _log(f"[error] PUSH_TARGET_DATE={override!r} 非法：{exc}", err=True)
            sys.exit(2)
    return datetime.now(BEIJING).date()


def _is_backfill() -> bool:
    return bool(os.environ.get("PUSH_TARGET_DATE", "").strip())


def _check_env() -> None:
    missing = [k for k in REQUIRED_ENVS if not os.environ.get(k)]
    if missing:
        _log(f"[error] 缺少必需环境变量：{', '.join(missing)}", err=True)
        sys.exit(2)


# ———————————— 推送单个源的通用骨架 ———————————— #


def _alert_ops(ops_webhook: str, ops_secret: str, text: str) -> None:
    """运维告警通道；失败自己吞掉。"""
    try:
        send_lark_text(ops_webhook, ops_secret, text)
    except Exception as exc:
        _log(f"[warn] ops alert failed: {exc}", err=True)


# ———————————— juya 推送流程 ———————————— #


def _push_juya(
    webhook: str,
    secret: str,
    ops_webhook: str,
    ops_secret: str,
    today: date,
    backfill: bool,
) -> bool:
    """返回 True 表示"本流程正常结束"（无论是否实际推送过），False 则失败。"""
    # 去重
    if backfill and today == datetime.now(BEIJING).date() \
            and is_pushed_today(STATE_PATH, today):
        _log(f"[juya] [skip] backfill 目标就是今天且已推送：{today}")
        return True
    if not backfill and is_pushed_today(STATE_PATH, today):
        _log(f"[juya] [skip] already pushed today ({today})")
        return True

    # 1. 拉 RSS
    try:
        entry = extract_today_entry(fetch_rss(), today=today)
    except Exception as exc:
        _log(f"[juya] [warn] fetch/parse failed: {exc}", err=True)
        if backfill:
            return False
        n = bump_failure(STATE_PATH)
        if n >= 3:
            try:
                _alert_ops(
                    ops_webhook, ops_secret,
                    f"⚠️ juya feed 拉取/解析连续 {n} 次失败\n"
                    f"错误：{exc}\n"
                    f"触发日期：{today}",
                )
            finally:
                try:
                    reset_failure(STATE_PATH)
                except Exception:
                    pass
        return False

    # 2. 今天有没有条目
    if entry is None:
        _log(f"[juya] [skip] juya not updated for {today}")
        if not backfill:
            silent = juya_silent_days(STATE_PATH, today)
            if silent is not None and silent >= DEAD_THRESHOLD_DAYS \
                    and should_alert_juya_dead(STATE_PATH, today):
                last_entry = get_last_juya_entry_date(STATE_PATH)
                try:
                    _alert_ops(
                        ops_webhook, ops_secret,
                        f"⚠️ juya 已连续 {silent} 天未更新（最后一期：{last_entry}）\n"
                        f"请人工确认：https://daily.juya.uk/",
                    )
                finally:
                    try:
                        mark_juya_dead_alerted(STATE_PATH, today)
                    except Exception:
                        pass
        return True

    # 3. 有条目 — 记一下 juya 最新条目日期
    pub_dt = entry.get("published_dt")
    if isinstance(pub_dt, datetime) and not backfill:
        record_juya_entry_date(STATE_PATH, pub_dt.astimezone(BEIJING).date())

    # 4. 渲染 + 推送
    try:
        card = parse_entry_to_card(entry)
        if card is None:
            fallback_title = entry.get("title") or "<untitled>"
            fallback_link = entry.get("link") or "<no link>"
            text = (
                f"🤖 橘鸦 AI 早报 · {fallback_title}\n"
                f"（内容解析降级，请点击原文查看）\n{fallback_link}"
            )
            send_lark_text(webhook, secret, text)
            if not backfill:
                mark_pushed_today(STATE_PATH, today)
            _alert_ops(ops_webhook, ops_secret, f"⚠️ juya 今日内容解析降级")
            _log(f"[juya] [ok] pushed (degraded) {today}")
            return True

        send_lark_card(webhook, secret, card)
        if not backfill:
            mark_pushed_today(STATE_PATH, today)
        _log(f"[juya] [ok] pushed {today}")
        return True

    except Exception as exc:
        if backfill:
            _log(f"[juya] [fail] backfill push failed: {exc}", err=True)
            return False
        n = bump_failure(STATE_PATH)
        _log(f"[juya] [fail] push attempt failed ({n}/3): {exc}", err=True)
        if n >= 3:
            try:
                _alert_ops(
                    ops_webhook, ops_secret,
                    f"⚠️ juya 今日推送连续 {n} 次失败\n错误：{exc}",
                )
            finally:
                try:
                    reset_failure(STATE_PATH)
                except Exception:
                    pass
        return False


# ———————————— aihot 推送流程 ———————————— #


def _push_aihot(
    webhook: str,
    secret: str,
    ops_webhook: str,
    ops_secret: str,
    today: date,
    backfill: bool,
) -> bool:
    """返回 True 表示本流程正常结束，False 表示失败。"""
    # 去重
    if backfill and today == datetime.now(BEIJING).date() \
            and is_aihot_pushed_today(STATE_PATH, today):
        _log(f"[aihot] [skip] backfill 目标就是今天且已推送：{today}")
        return True
    if not backfill and is_aihot_pushed_today(STATE_PATH, today):
        _log(f"[aihot] [skip] already pushed today ({today})")
        return True

    # 1. 拉日报
    try:
        daily = fetch_daily(today)  # /api/public/daily/{YYYY-MM-DD}
    except Exception as exc:
        _log(f"[aihot] [warn] fetch_daily({today}) failed: {exc}", err=True)
        if backfill:
            return False
        n = bump_aihot_failure(STATE_PATH)
        if n >= 3:
            try:
                _alert_ops(
                    ops_webhook, ops_secret,
                    f"⚠️ aihot 日报拉取连续 {n} 次失败\n错误：{exc}",
                )
            finally:
                try:
                    reset_aihot_failure(STATE_PATH)
                except Exception:
                    pass
        return False

    # 2. 指定日期没日报 → 尝试最新一期 fallback
    if not aihot_has_content(daily):
        _log(f"[aihot] [skip] aihot daily not available for {today}, try latest")
        try:
            daily = fetch_daily()  # /api/public/daily → 最新一期
        except Exception as exc:
            _log(f"[aihot] [warn] fetch latest daily also failed: {exc}", err=True)
            daily = None

    if not aihot_has_content(daily):
        _log(f"[aihot] [skip] aihot no content available for {today}")
        if not backfill:
            silent = aihot_silent_days(STATE_PATH, today)
            if silent is not None and silent >= DEAD_THRESHOLD_DAYS \
                    and should_alert_aihot_dead(STATE_PATH, today):
                last_entry = get_last_aihot_entry_date(STATE_PATH)
                try:
                    _alert_ops(
                        ops_webhook, ops_secret,
                        f"⚠️ aihot 已连续 {silent} 天未更新（最后一期：{last_entry}）\n"
                        f"请人工确认：{AIHOT_BASE_URL}/",
                    )
                finally:
                    try:
                        mark_aihot_dead_alerted(STATE_PATH, today)
                    except Exception:
                        pass
        return True

    # 3. 记录最新条目日期
    entry_date = daily_date(daily) if daily else None
    if entry_date is not None and not backfill:
        record_aihot_entry_date(STATE_PATH, entry_date)

    # 4. 渲染 + 推送
    try:
        card = aihot_to_card(daily)
        if card is None:
            d = daily_date(daily) if daily else None
            fallback = (
                f"🔥 AI HOT 日报 · {d or today}\n"
                f"（内容解析降级，请点击原文查看）\n{AIHOT_BASE_URL}/"
            )
            send_lark_text(webhook, secret, fallback)
            if not backfill:
                mark_aihot_pushed_today(STATE_PATH, today)
            _alert_ops(ops_webhook, ops_secret, f"⚠️ aihot 今日内容解析降级")
            _log(f"[aihot] [ok] pushed (degraded) {today}")
            return True

        send_lark_card(webhook, secret, card)
        if not backfill:
            mark_aihot_pushed_today(STATE_PATH, today)
        n = total_items(daily) if daily else 0
        _log(f"[aihot] [ok] pushed {today} ({n} 条)")
        return True

    except Exception as exc:
        if backfill:
            _log(f"[aihot] [fail] backfill push failed: {exc}", err=True)
            return False
        n = bump_aihot_failure(STATE_PATH)
        _log(f"[aihot] [fail] push attempt failed ({n}/3): {exc}", err=True)
        if n >= 3:
            try:
                _alert_ops(
                    ops_webhook, ops_secret,
                    f"⚠️ aihot 今日推送连续 {n} 次失败\n错误：{exc}",
                )
            finally:
                try:
                    reset_aihot_failure(STATE_PATH)
                except Exception:
                    pass
        return False


# ———————————— 入口 ———————————— #


def main() -> int:
    _check_env()
    webhook = os.environ["LARK_WEBHOOK_URL"]
    secret = os.environ["LARK_WEBHOOK_SECRET"]
    ops_webhook = os.environ["LARK_OPS_WEBHOOK_URL"]
    ops_secret = os.environ["LARK_OPS_WEBHOOK_SECRET"]

    today = _today()
    backfill = _is_backfill()

    _log(f"[meta] today={today} backfill={backfill}")

    # 顺序推送：aihot 先，juya 后；互不影响
    aihot_ok = _push_aihot(webhook, secret, ops_webhook, ops_secret, today, backfill)
    juya_ok = _push_juya(webhook, secret, ops_webhook, ops_secret, today, backfill)

    if juya_ok and aihot_ok:
        _log("[meta] all flows completed")
        return 0
    _log("[meta] some flows failed", err=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
