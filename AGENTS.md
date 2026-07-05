# 项目规范

## 项目目标

聚合橘鸦 AI 早报、AI HOT 和 follow-builders，并自动推送为飞书卡片。

## 目录与命名

- 根目录 Python 文件分别负责数据拉取、卡片渲染、推送和状态管理。
- `tests/` 存放 pytest 测试，`docs/` 存放设计与运维说明。
- Python 使用 `snake_case`，常量使用 `UPPER_SNAKE_CASE`。

## 验证命令

```bash
pytest -v
```

修改单一卡片时，先运行对应测试文件，再运行全量测试。

## 调度边界

- 定时触发由 cron-job.org 负责，每 30 分钟一次（Crontab `*/30 8-15 * * *`，08:00-15:30 北京时间），POST `workflow_dispatch` 并传 `PUSH_MODE=all`。
- GitHub Actions workflow 仅保留 `workflow_dispatch` 触发器，已移除 `schedule`，不存在 15:00 自动兜底。
- `PUSH_MODE=all` 在 `push.py` 内按北京时间 auto-routing：
  - 上午（< 14:00）→ 自动降级为 `morning`，只推 AI HOT 和橘鸦（builders feed 通常 14:17 才更新）。
  - 下午（>= 14:00）→ 保持 `all`，依次推 aihot + juya + builders（去重跳过已推的，未推的会补推）。
  - backfill 模式（设置了 `PUSH_TARGET_DATE`）不受时间限制，手动指定什么就推什么。
- `PUSH_MODE=morning` / `PUSH_MODE=builders` 仅用于本地单独验证或明确的人工补推。
- cron-job.org 的 crontab、PAT、Body 属于外部维护项，需要用户自己保管；仓库内不存放 PAT，更新 PAT 在 cron-job.org 后台操作。

## 清理规则

- 不提交 webhook、secret、token 或真实群配置。
- 不修改 GitHub Actions、调度时间或环境变量，除非用户明确确认。
- 不删除历史状态或推送记录，除非用户明确确认。
