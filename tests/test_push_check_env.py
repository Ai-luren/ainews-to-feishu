"""push.py 顶层错误路径的补充测试：_check_env 缺环境变量时 sys.exit(2)。

原 test_push.py 都是 monkeypatch.fetch_rss + 全流程 happy path，没有验证：
  - 当缺少 LARK_WEBHOOK_URL / LARK_OPS_WEBHOOK_URL 等必需变量时，push 进程
    应该以退出码 2 优雅结束而不是继续往下走引发 KeyError。
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest

import push


REPO_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# 单元路径：直接 import push，在当前进程里调用 _check_env
# ---------------------------------------------------------------------------

def test_check_env_exits_with_code_2_when_missing(monkeypatch):
    """缺一个必需变量 → sys.exit(2)。"""
    # 清掉所有必需变量；保留 LARK_OPS_WEBHOOK_URL 以验证"任意缺失即失败"
    for k in push.REQUIRED_ENVS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LARK_OPS_WEBHOOK_URL", "x")
    monkeypatch.setenv("LARK_OPS_WEBHOOK_SECRET", "x")
    # 保留 2 个缺 2 个 → 仍然应失败
    with pytest.raises(SystemExit) as exc_info:
        push._check_env()
    assert exc_info.value.code == 2


def test_check_env_passes_when_all_present(monkeypatch):
    """所有必需变量都设置 → 不抛异常。"""
    for k in push.REQUIRED_ENVS:
        monkeypatch.setenv(k, "dummy")
    # 不应抛异常
    push._check_env()


# ---------------------------------------------------------------------------
# 端到端子进程路径：以干净环境跑 push.py，验证实际 exit code 和 stderr
# ---------------------------------------------------------------------------

def test_push_subprocess_exits_2_when_env_missing(tmp_path):
    """完全不带 LARK_* 环境变量跑 push.main() → exit code 2，stderr 明确提示缺变量。"""
    clean_env = {k: v for k, v in os.environ.items() if not k.startswith("LARK_")}
    # src/ 目录结构调整后，子进程需要 PYTHONPATH 才能找到 push 模块
    clean_env["PYTHONPATH"] = str(REPO_ROOT / "src")
    # 给 state.json 指定独立位置，避免污染仓库
    state_p = tmp_path / "state.json"
    state_p.write_text("{}")

    code = (
        "import sys, os; "
        f"os.chdir({str(REPO_ROOT)!r}); "
        "import push; "
        "sys.exit(push.main())"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        env=clean_env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2, (
        f"预期 exit code 2，实际 {result.returncode}\n"
        f"stderr={result.stderr}\nstdout={result.stdout}"
    )
    # stderr 里应明确提到环境变量
    assert "环境变量" in result.stderr or "缺少" in result.stderr or "LARK_" in result.stderr
