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

- 上午 `workflow_dispatch` 使用 `PUSH_MODE=morning`，仅推 AI HOT 和橘鸦。
- GitHub Actions 北京时间 15:00 使用 `PUSH_MODE=builders`，仅推 follow-builders。
- `PUSH_MODE=all` 仅用于本地完整验证或明确的人工补推。

## 清理规则

- 不提交 webhook、secret、token 或真实群配置。
- 不修改 GitHub Actions、调度时间或环境变量，除非用户明确确认。
- 不删除历史状态或推送记录，除非用户明确确认。
