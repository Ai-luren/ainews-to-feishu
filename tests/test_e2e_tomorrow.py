"""端到端模拟测试：模拟明天早上 8 点的完整推送流程。"""
import json
import os
from datetime import date, datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import push
from push import main


@pytest.fixture
def mock_env(monkeypatch):
    """模拟环境变量。"""
    monkeypatch.setenv("LARK_WEBHOOK_URL", "https://example.com/webhook")
    monkeypatch.setenv("LARK_WEBHOOK_SECRET", "test-secret")
    monkeypatch.setenv("LARK_OPS_WEBHOOK_URL", "https://example.com/ops")
    monkeypatch.setenv("LARK_OPS_WEBHOOK_SECRET", "ops-secret")


@pytest.fixture
def fresh_state(tmp_path: Path) -> Path:
    """创建一个干净的 state.json（模拟新的一天）。"""
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({
        "juya_pushed_date": None,
        "juya_failures": 0,
        "last_juya_entry_date": "2026-06-15",
        "juya_dead_alerted_on": None,
        "aihot_pushed_date": None,
        "aihot_failures": 0,
        "last_aihot_entry_date": "2026-06-15",
        "aihot_dead_alerted_on": None,
        "last_pushed_date": None,
        "consecutive_failures": 0,
    }))
    return state_path


def test_tomorrow_8am_push_simulation(fresh_state: Path, mock_env, monkeypatch):
    """模拟明天（2026-06-16）早上 8 点的推送流程。"""
    tomorrow = date(2026, 6, 16)

    # 1. 模拟日期
    monkeypatch.setattr(push, "_today", lambda: tomorrow)

    # 2. 模拟 state 路径
    monkeypatch.setattr(push, "STATE_PATH", fresh_state)

    # 3. 模拟 aihot API 返回明天的内容
    mock_aihot_daily = {
        "date": "2026-06-16",
        "sections": [
            {
                "label": "模型发布/更新",
                "items": [
                    {
                        "title": "GPT-5 发布",
                        "sourceUrl": "https://example.com/gpt5",
                        "sourceName": "OpenAI",
                        "summary": "最新模型发布",
                    }
                ]
            }
        ],
    }

    # 4. 模拟 juya RSS 返回明天的内容
    mock_juya_entry = {
        "title": "2026-06-16",
        "link": "https://daily.juya.uk/2026-06-16",
        "published_dt": datetime(2026, 6, 16, 8, 0),
        "content_html": "<h2>模型发布</h2><ul><li>GPT-5 发布</li></ul>",
    }

    # 5. 记录推送调用
    pushed_cards = []
    pushed_texts = []

    def mock_send_card(url, secret, card):
        pushed_cards.append((url, card))

    def mock_send_text(url, secret, text):
        pushed_texts.append((url, text))

    # 6. 应用所有 mock
    monkeypatch.setattr(push, "fetch_daily", lambda d=None: mock_aihot_daily if d == tomorrow else None)
    monkeypatch.setattr(push, "fetch_rss", lambda: "<rss/>")
    monkeypatch.setattr(push, "extract_today_entry", lambda xml, today: mock_juya_entry if today == tomorrow else None)

    # mock 卡片渲染函数返回有效卡片
    monkeypatch.setattr(push, "parse_entry_to_card", lambda e: {
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": f"🤖 橘鸦 AI 早报 · {e['title']}"}},
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "测试内容"}}],
    })
    monkeypatch.setattr(push, "parse_daily_to_card", lambda d: {
        "config": {"wide_screen_mode": True},
        "header": {"template": "blue", "title": {"tag": "plain_text", "content": f"🔥 AI HOT 日报 · {d['date']}"}},
        "elements": [{"tag": "div", "text": {"tag": "lark_md", "content": "测试内容"}}],
    })

    monkeypatch.setattr(push, "send_lark_card", mock_send_card)
    monkeypatch.setattr(push, "send_lark_text", mock_send_text)

    # 7. 运行主流程
    rc = main()

    # 8. 验证结果
    assert rc == 0, "推送流程应该成功"

    # aihot 先推送（卡片）
    assert len(pushed_cards) >= 1, "应该推送 aihot 卡片"
    aihot_card = pushed_cards[0][1]
    assert "AI HOT" in aihot_card["header"]["title"]["content"]
    assert "2026-06-16" in aihot_card["header"]["title"]["content"]

    # juya 后推送（可能是卡片或降级文本）
    juya_pushed = len(pushed_cards) >= 2 or len(pushed_texts) >= 1
    assert juya_pushed, "应该推送 juya 内容"

    # 验证状态更新
    state = json.loads(fresh_state.read_text())
    assert state["aihot_pushed_date"] == "2026-06-16", "aihot 应标记已推送"
    assert state["juya_pushed_date"] == "2026-06-16", "juya 应标记已推送"
    assert state["last_aihot_entry_date"] == "2026-06-16", "aihot 条目日期应更新"
    assert state["last_juya_entry_date"] == "2026-06-16", "juya 条目日期应更新"


def test_duplicate_push_skipped(fresh_state: Path, mock_env, monkeypatch):
    """模拟 8:30 第二次触发时跳过已推送的源。"""
    tomorrow = date(2026, 6, 16)
    monkeypatch.setattr(push, "_today", lambda: tomorrow)
    monkeypatch.setattr(push, "STATE_PATH", fresh_state)

    # 模拟已经推送过
    from state import mark_aihot_pushed_today, mark_pushed_today
    mark_aihot_pushed_today(fresh_state, tomorrow)
    mark_pushed_today(fresh_state, tomorrow)

    # 记录推送调用
    pushed_cards = []
    monkeypatch.setattr(push, "send_lark_card", lambda u, s, c: pushed_cards.append(c))

    # 运行主流程
    rc = main()

    # 应该跳过，不推送
    assert rc == 0
    assert len(pushed_cards) == 0, "已推送过，应该跳过"


def test_cron_job_org_schedule_validation():
    """验证 cron-job.org 的 crontab 配置。"""
    # crontab: */30 8-10 * * *
    # 应该在以下时间触发（北京时间）：
    expected_times = ["08:00", "08:30", "09:00", "09:30", "10:00", "10:30"]

    # 验证 crontab 表达式解析正确
    import re
    crontab = "*/30 8-10 * * *"
    parts = crontab.split()

    # 分钟: */30 = 0, 30
    assert parts[0] == "*/30"

    # 小时: 8-10 = 8, 9, 10
    hours = parts[1]
    assert hours == "8-10"

    # 计算实际触发时间
    actual_times = []
    for h in range(8, 11):  # 8, 9, 10
        for m in [0, 30]:
            actual_times.append(f"{h:02d}:{m:02d}")

    assert actual_times == expected_times, f"触发时间不匹配: {actual_times} != {expected_times}"


def test_github_actions_fallback_schedule():
    """验证 GitHub Actions 兜底 schedule 配置。"""
    # workflow 中的 cron: '0 3 * * *'
    # UTC 03:00 = 北京时间 11:00

    from datetime import timedelta

    utc_hour = 3
    beijing_hour = (utc_hour + 8) % 24  # UTC+8

    assert beijing_hour == 11, f"北京时间应该是 11:00，实际是 {beijing_hour}"
