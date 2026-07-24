"""每日推送主流程。

支持 morning / builders / all 三种模式，三个源独立去重和告警。
"""
import os
import sys
from datetime import date, datetime
from pathlib import Path

import pytz

from aihot import AIHOT_BASE_URL, daily_date, fetch_daily, has_content, total_items
from aihot_card import parse_daily_to_card
from builders import fetch_daily as builders_fetch_daily
from builders_card import render_card as builders_render_card
from card_utils import _safe_url
from lark import send_lark_card, send_lark_text
from lark_card import parse_entry_to_card
from rss import extract_today_entry, fetch_rss
from state import (
    aihot_silent_days, bump_aihot_failure, bump_builders_failure, bump_failure,
    builders_silent_days,
    get_last_aihot_entry_date, get_last_builders_entry_date,
    get_last_juya_entry_date,
    is_aihot_pushed_today, is_builders_pushed_today, is_pushed_today,
    juya_silent_days,
    mark_aihot_dead_alerted, mark_aihot_pushed_today,
    mark_builders_dead_alerted, mark_builders_pushed_today,
    mark_juya_dead_alerted, mark_juya_degraded_alerted,
    mark_pushed_today,
    record_aihot_entry_date, record_builders_entry_date,
    record_juya_entry_date,
    reset_aihot_failure, reset_builders_failure, reset_failure,
    should_alert_aihot_dead, should_alert_builders_dead,
    should_alert_juya_dead,
    should_alert_juya_degraded,
)

BEIJING = pytz.timezone("Asia/Shanghai")
STATE_PATH = Path(__file__).parent.parent / "state.json"
DEAD_THRESHOLD = 3
FAILURE_THRESHOLD = 3

REQUIRED_ENVS = ["LARK_WEBHOOK_URL", "LARK_WEBHOOK_SECRET",
                  "LARK_OPS_WEBHOOK_URL", "LARK_OPS_WEBHOOK_SECRET"]
PUSH_MODES = {"morning", "builders", "all"}


def _log(msg: str, err: bool = False) -> None:
    print(msg, file=sys.stderr if err else sys.stdout, flush=True)


def _handle_failure(source: str, bump_fn, reset_fn,
                    ops_webhook: str, ops_secret: str, e: Exception,
                    stage: str = "拉取") -> bool:
    """统一的失败处理：计数 + 告警 + 重置。返回 False。"""
    n = bump_fn(STATE_PATH)
    _log(f"[{source}] [fail] ({n}/{FAILURE_THRESHOLD}) {stage}: {e}", err=True)
    if n >= FAILURE_THRESHOLD:
        _alert(ops_webhook, ops_secret,
               f"⚠️ {source} 连续 {n} 次{stage}失败\n错误: {e}")
        reset_fn(STATE_PATH)
    return False


def _handle_dead_alert(source: str, url: str, silent_fn, last_date_fn,
                       should_fn, mark_fn,
                       ops_webhook: str, ops_secret: str,
                       today: date) -> None:
    """统一的停更告警。"""
    silent = silent_fn(STATE_PATH, today)
    if silent and silent >= DEAD_THRESHOLD and should_fn(STATE_PATH, today):
        last = last_date_fn(STATE_PATH)
        _alert(ops_webhook, ops_secret,
               f"⚠️ {source} 连续 {silent} 天未更新（最后: {last}）\n{url}")
        mark_fn(STATE_PATH, today)


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


def _push_mode() -> str:
    mode = os.environ.get("PUSH_MODE", "all").strip().lower() or "all"
    if mode not in PUSH_MODES:
        _log(
            f"[error] PUSH_MODE 非法: {mode}（可选 morning/builders/all）",
            err=True,
        )
        sys.exit(2)
    return mode


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


def _record_juya_entry(entry: dict, backfill: bool) -> None:
    """推送成功后记录 juya entry 日期（仅在非 backfill 模式下记录）。"""
    pub_dt = entry.get("published_dt")
    if isinstance(pub_dt, datetime) and not backfill:
        record_juya_entry_date(STATE_PATH, pub_dt.astimezone(BEIJING).date())


def _push_juya(webhook: str, secret: str, ops_webhook: str, ops_secret: str,
               today: date, backfill: bool) -> bool:
    """推送 juya，返回 True=正常结束，False=失败"""
    # 去重（backfill 也走去重，防止重复 backfill 同一天）
    if is_pushed_today(STATE_PATH, today):
        if backfill:
            _log(f"[juya] [skip] backfill already pushed ({today})")
        else:
            _log(f"[juya] [skip] already pushed today ({today})")
        return True

    # 拉取
    try:
        entry = extract_today_entry(fetch_rss(), today=today)
    except Exception as e:
        _log(f"[juya] [warn] fetch failed: {e}", err=True)
        if backfill:
            return False
        _handle_failure("juya", bump_failure, reset_failure,
                        ops_webhook, ops_secret, e, "拉取")
        # fetch 异常时也检查停更告警——持续故障 3 天以上触发持久告警
        _handle_dead_alert("juya", "https://daily.juya.uk/",
                           juya_silent_days, get_last_juya_entry_date,
                           should_alert_juya_dead, mark_juya_dead_alerted,
                           ops_webhook, ops_secret, today)
        return False

    # 无内容
    if entry is None:
        if backfill:
            # backfill 目标日期无内容 = 失败，返回 False 让 main() 退出码非 0
            _log(f"[juya] [skip] no content for {today} (backfill)")
            return False
        _log(f"[juya] [skip] not updated for {today}")
        _handle_dead_alert("juya", "https://daily.juya.uk/",
                           juya_silent_days, get_last_juya_entry_date,
                           should_alert_juya_dead, mark_juya_dead_alerted,
                           ops_webhook, ops_secret, today)
        return True

    # 渲染推送
    try:
        card = parse_entry_to_card(entry)
        if card is None:
            # 解析降级：content:encoded 为空或格式异常。
            # 补推模式：没有重试机制，直接发降级文本。
            if backfill:
                title = entry.get("title") or "<untitled>"
                link = _safe_url(entry.get("link"))
                send_lark_text(webhook, secret, f"🤖 橘鸦 AI 早报 · {title}\n（解析降级）\n{link}")
                mark_pushed_today(STATE_PATH, today)
                _record_juya_entry(entry, backfill)
                _log(f"[juya] [ok] pushed (degraded/backfill) {today}")
                return True

            # 最终兜底：11:00 后仍降级 → 发文本到主群，有总比没有好
            now_bj = datetime.now(BEIJING)
            if now_bj.hour >= 11:
                title = entry.get("title") or "<untitled>"
                link = _safe_url(entry.get("link"))
                send_lark_text(webhook, secret,
                               f"🤖 橘鸦 AI 早报 · {title}\n（卡片解析失败，点击查看完整日报）\n{link}")
                mark_pushed_today(STATE_PATH, today)
                _record_juya_entry(entry, backfill)
                _log(f"[juya] [ok] pushed (final-fallback) {today}")
                return True

            # 11:00 前：不标记已推送，返回 False 让后续 cron 重试
            if should_alert_juya_degraded(STATE_PATH, today):
                link = _safe_url(entry.get("link"))
                _alert(ops_webhook, ops_secret,
                       f"⚠️ juya 内容解析降级，等待后续 cron 重试\n{link}")
                mark_juya_degraded_alerted(STATE_PATH, today)
            _log(f"[juya] [warn] degraded, will retry {today}")
            return False

        send_lark_card(webhook, secret, card)
        mark_pushed_today(STATE_PATH, today)
        _record_juya_entry(entry, backfill)
        _log(f"[juya] [ok] pushed {today}")
        return True

    except Exception as e:
        if backfill:
            _log(f"[juya] [fail] backfill: {e}", err=True)
            return False
        return _handle_failure("juya", bump_failure, reset_failure,
                               ops_webhook, ops_secret, e, "推送")


def _push_aihot(webhook: str, secret: str, ops_webhook: str, ops_secret: str,
                today: date, backfill: bool) -> bool:
    """推送 aihot，返回 True=正常结束，False=失败"""
    # 去重（backfill 也走去重，防止重复 backfill 同一天）
    if is_aihot_pushed_today(STATE_PATH, today):
        if backfill:
            _log(f"[aihot] [skip] backfill already pushed ({today})")
        else:
            _log(f"[aihot] [skip] already pushed today ({today})")
        return True

    # 拉取
    try:
        daily = fetch_daily(today)
    except Exception as e:
        _log(f"[aihot] [warn] fetch failed: {e}", err=True)
        if backfill:
            return False
        _handle_failure("aihot", bump_aihot_failure, reset_aihot_failure,
                        ops_webhook, ops_secret, e, "拉取")
        # fetch 异常时也检查停更告警——持续故障 3 天以上触发持久告警
        _handle_dead_alert("aihot", f"{AIHOT_BASE_URL}/",
                           aihot_silent_days, get_last_aihot_entry_date,
                           should_alert_aihot_dead, mark_aihot_dead_alerted,
                           ops_webhook, ops_secret, today)
        return False

    # 无内容时尝试最新一期（backfill 模式不 fallback，避免拉到其他日期内容）
    if not has_content(daily) and not backfill:
        try:
            daily = fetch_daily()
        except Exception as e:
            _log(f"[aihot] [warn] fallback fetch failed: {e}", err=True)
            daily = None

    if not has_content(daily):
        if backfill:
            # backfill 目标日期无内容 = 失败，返回 False 让 main() 退出码非 0
            _log(f"[aihot] [skip] no content for {today} (backfill)")
            return False
        _log(f"[aihot] [skip] no content for {today}")
        _handle_dead_alert("aihot", f"{AIHOT_BASE_URL}/",
                           aihot_silent_days, get_last_aihot_entry_date,
                           should_alert_aihot_dead, mark_aihot_dead_alerted,
                           ops_webhook, ops_secret, today)
        return True

    # 检查内容日期是否等于今天
    # 防止 fallback 拉到其他日期的内容当新内容推送
    # backfill 模式下也校验：目标日期无内容时 fallback 拉到其他日期也应跳过
    entry_date = daily_date(daily)
    if not entry_date:
        # API 返回畸形数据（有条目但无 date 字段）→ 跳过，避免推到旧内容
        _log(f"[aihot] [skip] content has no date field, skipping")
        return True
    if entry_date != today:
        if backfill:
            _log(f"[aihot] [skip] content date {entry_date} != today {today} (backfill)")
            return False
        _log(f"[aihot] [skip] content date {entry_date} != today {today}（还未更新）")
        return True

    # 渲染推送
    try:
        card = parse_daily_to_card(daily)
        if card is None:
            d = daily_date(daily) or today
            send_lark_text(webhook, secret, f"🔥 AI HOT 日报 · {d}\n（解析降级）\n{AIHOT_BASE_URL}/")
            mark_aihot_pushed_today(STATE_PATH, today)
            if entry_date and not backfill:
                record_aihot_entry_date(STATE_PATH, entry_date)
            _alert(ops_webhook, ops_secret, "⚠️ aihot 内容解析降级")
            _log(f"[aihot] [ok] pushed (degraded) {today}")
            return True

        send_lark_card(webhook, secret, card)
        mark_aihot_pushed_today(STATE_PATH, today)
        if entry_date and not backfill:
            record_aihot_entry_date(STATE_PATH, entry_date)
        _log(f"[aihot] [ok] pushed {today} ({total_items(daily)} 条)")
        return True

    except Exception as e:
        if backfill:
            _log(f"[aihot] [fail] backfill: {e}", err=True)
            return False
        return _handle_failure("aihot", bump_aihot_failure, reset_aihot_failure,
                               ops_webhook, ops_secret, e, "推送")


def _push_builders(webhook: str, secret: str, ops_webhook: str, ops_secret: str,
                   today: date, backfill: bool) -> bool:
    """推送 follow-builders 推文动态，返回 True=正常结束，False=失败"""
    # 去重（backfill 也走去重，防止重复 backfill 同一天）
    if is_builders_pushed_today(STATE_PATH, today):
        if backfill:
            _log(f"[builders] [skip] backfill already pushed ({today})")
        else:
            _log(f"[builders] [skip] already pushed today ({today})")
        return True

    # 拉取 + 翻译
    try:
        daily = builders_fetch_daily()
    except Exception as e:
        _log(f"[builders] [warn] fetch failed: {e}", err=True)
        if backfill:
            return False
        _handle_failure("builders", bump_builders_failure, reset_builders_failure,
                        ops_webhook, ops_secret, e, "拉取")
        # fetch 异常时也检查停更告警——持续故障 3 天以上触发持久告警
        _handle_dead_alert("follow-builders",
                           "https://github.com/zarazhangrui/follow-builders",
                           builders_silent_days, get_last_builders_entry_date,
                           should_alert_builders_dead, mark_builders_dead_alerted,
                           ops_webhook, ops_secret, today)
        return False

    if not daily or not daily.get("tweets"):
        if backfill:
            # backfill 目标日期无内容 = 失败，返回 False 让 main() 退出码非 0
            _log(f"[builders] [skip] no content for {today} (backfill)")
            return False
        _log(f"[builders] [skip] no content for {today}")
        _handle_dead_alert("follow-builders",
                           "https://github.com/zarazhangrui/follow-builders",
                           builders_silent_days, get_last_builders_entry_date,
                           should_alert_builders_dead, mark_builders_dead_alerted,
                           ops_webhook, ops_secret, today)
        return True

    # 检查 feed 日期是否等于今天（follow-builders 通常 14:17 更新）
    # 防止早上触发时把昨天的 feed 当新内容推送
    entry_date = daily.get("date")
    if not entry_date:
        # feed 畸形数据（有推文但无 generatedAt）→ 跳过，避免推到旧内容
        _log(f"[builders] [skip] content has no date field, skipping")
        return True
    if entry_date != today:
        if backfill:
            _log(f"[builders] [skip] feed date {entry_date} != today {today} (backfill)")
            return False
        _log(f"[builders] [skip] feed date {entry_date} != today {today}（还未更新）")
        return True

    # 渲染推送
    try:
        card = builders_render_card(daily)
        send_lark_card(webhook, secret, card)
        mark_builders_pushed_today(STATE_PATH, today)
        if entry_date and not backfill:
            record_builders_entry_date(STATE_PATH, entry_date)
        _log(f"[builders] [ok] pushed {today} ({len(daily.get('tweets', []))} 条推文)")
        return True

    except Exception as e:
        if backfill:
            _log(f"[builders] [fail] backfill: {e}", err=True)
            return False
        return _handle_failure("builders", bump_builders_failure, reset_builders_failure,
                               ops_webhook, ops_secret, e, "推送")


def main() -> int:
    _check_env()
    webhook = os.environ["LARK_WEBHOOK_URL"]
    secret = os.environ["LARK_WEBHOOK_SECRET"]
    ops_webhook = os.environ["LARK_OPS_WEBHOOK_URL"]
    ops_secret = os.environ["LARK_OPS_WEBHOOK_SECRET"]

    today = _today()
    backfill = _is_backfill()
    mode = _push_mode()

    # all 模式下按时间自动分流：
    #   上午（< 14:00）→ 降级为 morning，只推 aihot + juya
    #     （builders feed 通常 14:17 才更新，上午推会被日期校验 skip，浪费翻译调用）
    #   下午（>= 14:00）→ 保持 all，依次推 aihot + juya + builders
    #     （去重机制会跳过上午已推的，未推的会补推；
    #      避免上午 cron 全部失败时下午只推 builders 导致 aihot/juya 当天丢失）
    # backfill 模式不受时间限制，手动指定什么就推什么
    if mode == "all" and not backfill:
        now_bj = datetime.now(BEIJING)
        if now_bj.hour < 14:
            mode = "morning"

    _log(f"[meta] today={today} backfill={backfill} mode={mode}")

    aihot_ok = True
    juya_ok = True
    builders_ok = True

    if mode in {"morning", "all"}:
        aihot_ok = _push_aihot(
            webhook, secret, ops_webhook, ops_secret, today, backfill,
        )
        juya_ok = _push_juya(
            webhook, secret, ops_webhook, ops_secret, today, backfill,
        )
    if mode in {"builders", "all"}:
        builders_ok = _push_builders(
            webhook, secret, ops_webhook, ops_secret, today, backfill,
        )

    # 退出码策略：
    #   全部成功 → 0
    #   部分成功 → 0（避免单个外部源故障导致整个 run 标红）
    #   全部失败 → 1（真正需要关注）
    attempted = []
    if mode in {"morning", "all"}:
        attempted.append(("aihot", aihot_ok))
        attempted.append(("juya", juya_ok))
    if mode in {"builders", "all"}:
        attempted.append(("builders", builders_ok))

    failed = [name for name, ok in attempted if not ok]
    if not failed:
        _log("[meta] all completed")
        return 0
    if any(ok for _, ok in attempted):
        _log(f"[meta] partial success, failed: {','.join(failed)}", err=True)
        return 0
    _log("[meta] all sources failed", err=True)
    return 1


if __name__ == "__main__":
    sys.exit(main())
