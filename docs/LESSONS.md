# 开发过程踩的坑（给未来的自己和 Claude）

> 写在这里是为了下次做同类项目时，自己或 Claude 打开仓库能先扫一眼、避免重犯。

## 1. 外部契约的单元测试，必须用对方官方样例作"已知向量"

**现象**：Task 2 写完 `lark_sign` 函数后，2 个单元测试全绿。第一次真往飞书发请求就 `19021: sign match fail`。

**根因**：我写的 HMAC 算法是 `HMAC(key=secret, msg=timestamp\nsecret)`，飞书实际是 `HMAC(key=timestamp\nsecret, msg=空)`。测试里"已知向量"是我自己用同一份错代码算出来的——测试用**错算法验证错算法**，永远绿。

**教训**：任何对外部系统的契约（飞书签名、OAuth、支付回调…）的单元测试，**不能用自己算出的期望值**，必须：
- 用对方**官方文档里给的示例输入+输出**，或
- 用对方 SDK 跑一次生成参考，或
- 让对方给你一个已知向量

如果你发现测试的期望值是你自己算的，立刻红灯：这类测试验证的是"代码内部一致性"，不是"代码和真实世界一致性"。

## 2. 解析目标的"枚举值"要实测 N 天样本，不是看 1 期就定死

**现象**：Task 6 写卡片解析时，我只看了 04-27 一期（3 个分类），把分类表写成 6 个。上线后用户反馈"不是按 juya 格式"——有整整一个 `模型发布` 分类被错误归入了 `要闻`。

**根因**：juya 每天用的分类是**不确定子集**——平均每期 5 个分类，但 30 天累计用到 8 个不同分类。只看一期相当于用瞎子摸象的一条腿盖毯子。

**教训**：当你抽取"有多少种 X"的集合时：
- **扫至少 30 个样本**确认枚举值全集
- 优先用源头的**结构化标签**（juya 用 `<h3>` 专门放分类名——比我最初"任何短文本"靠谱 10 倍）
- 把扫描脚本留在 `docs/` 或作为测试用例，以后 juya 新增分类时重跑一下就能发现

用户当时直接说"搜索近30天的核对下"——这是**非常正确的工程直觉**，我一开始没这么做是偷懒。

## 3. GitHub Actions workflow 文件名不要和触发事件同名

**现象**：我最初把 workflow 文件命名为 `.github/workflows/push.yml`。GitHub 永远不索引它（Actions 页面只显示 Dependabot）。手动 `gh workflow run push.yml` 报 404。

**根因**：`push` 是 GitHub Actions 的保留事件名（`on: push`）。文件名撞上保留字后，GitHub 内部索引逻辑可能把它当成事件定义处理。

**教训**：workflow 文件名用**业务名**（`daily-ai-news.yml`），不要用**事件名**（`push.yml` / `schedule.yml` / `pull_request.yml`）。

## 4. GitHub Actions 自动 commit 会让本地落后，得 rebase

**现象**：修完签名 bug 本地 `git push` 被拒，"需要先 pull"。

**根因**：前一次失败的 workflow 运行把 `state.json` 的 `consecutive_failures` commit 并 push 回了远端。本地此时落后 1 个 commit。

**教训**：**任何**自动会在远端产生 commit 的 workflow（我们这个就是），本地开发 push 前先 `git pull --rebase`，或者 `git config pull.rebase true` 设成默认。

## 5. workflow 自动 commit 有跨触发源的竞态，concurrency group 防不了

**现象**：code review 时意识到一个低频但真实的 race。

**根因**：GitHub Actions 的 `concurrency.group` **只保证同一 workflow 内**的 runs 串行。但我们的 workflow 有两个触发源（cron + workflow_dispatch），两者都是 "daily-ai-news-push" 这个 workflow ——看上去 concurrency 能管。实际测试：当一个 cron run 正在 commit `state.json` 时，用户手动 dispatch，后发的 run 拿到的 base commit 是 cron run commit **之前**的，push 时 non-fast-forward，被拒。

这个 run 的问题：**飞书已经推了 / state.json 已经算了**，但 push 回仓库的 commit 丢了——下一 tick 拿到的还是旧 state，可能重复推。

**教训**：workflow 里凡是 `git push` 回仓库的，前面必须加 `git pull --rebase` 和失败重试循环。concurrency group 只是"弱并发控制"，不是"写锁"。

已修复方式：`.github/workflows/daily-ai-news.yml` 的 commit 步骤，push 失败时 rebase 重试 3 次。

## 6. 降级判据要对齐"业务意图"，不要只看代理指标

**现象**：code review 指出 `_card_has_content(card)` 判的是"卡片里有 div 带非空 content 字段吗"——这只是代理指标。真正的业务意图是"解析器从 HTML 里抽到分组了吗"。

**风险**：如果 juya 哪天 HTML 结构异化，`_extract_overview_groups` 返回 `[]`，但某个 `div` 由于 hard-coded 文本还是非空——`_card_has_content` 会返回 True，系统不降级，发出一张"空卡片"给团队，而且运维群也不会告警。

**教训**：当代码里有"是否降级"这类判断，问自己：**判的是业务意图本身，还是它的副产物？** 如果是后者，代理失效的那天就是生产事故。

已修复方式：`parse_entry_to_card` 在 `groups` 空时**直接返回 None**，push.py 判 `card is None` 触发降级。信号直接对齐意图，不再靠代理。

## 7. 第三方库返回的可选字段，访问前先 None check

**现象**：code review 指出 `feedparser.entries[i].published_parsed` 对畸形日期可能是 None，我代码直接 `datetime(*e.published_parsed[:6], ...)` → TypeError。

**教训**：第三方库的数据结构文档里标 "optional" / "may be None" 的字段，**必须 None check**——即使你跑 30 次都是好数据。一旦源头哪天给你一条坏数据，脚本崩 → workflow 失败 → 连续 3 次 → 告警刷屏——**不是致命但烦人**。

已修复方式：`rss.py` 里 `if not getattr(e, "published_parsed", None): continue` 跳过畸形条目。

## 8. GitHub Actions 对新建 private repo 有"cron 冷启动"延迟

**现象**：04-27 建的仓库，04-28 早上 cron 一次都没自动触发（`event=schedule` 查询返回 0 条），完全没推送。workflow 本身是 active，配置正确，手动 `workflow_dispatch` 能跑，就是定时事件没来。

**根因**：GitHub Actions 的 scheduled workflow 在仓库**首次创建后**需要 GitHub 内部注册定时任务。对于新建的 private repo，这个注册**可能延迟 1-2 天**。这是 GitHub 的已知但未公开文档化的行为。

**教训**：
1. 新部署任何 GitHub Actions 定时项目，**第一天不要期望 cron 自己跑**——预先手动触发一次作为兜底
2. 在部署说明里（skill / README）明确写出这个冷启动，免得使用者以为配置错了
3. 次日如果还不跑，可以：push 一个空 commit 唤醒；或临时改成每小时触发再改回来

已修复方式：(a) skill 的 Troubleshoot 流程会先检查 `event=schedule` 是否为空来识别这种场景；(b) setup.sh 的 "等 workflow 索引" 超时从 60 秒放宽到 180 秒，避免短暂延迟被误判为失败。

## 9. 上游数据源可能静默死亡，必须有"心跳"检测

**现象**：code review 指出我们的输入端是 `imjuya.github.io/juya-ai-daily/rss.xml`——一个**私人项目**。作者不维护或换域名的那天，整个系统会**永远打印 `[skip] juya not updated yet` 并返回 0**——飞书群里再也收不到早报，但**没任何告警**。

**根因**：`push.py` 把"juya 没更新"当成正常路径 `return 0`，等价于"一切正常"。但"一切正常"和"juya 死了"视觉上、行为上都一样。

**教训**：**任何依赖外部不稳定源头的管道，必须有"没动静也要告警"的 heartbeat 机制**。不能靠"下游用户抱怨收不到"才发现上游挂了——那时候已经晚了好几天。

已修复方式：`state.py` 新增 `last_juya_entry_date` 字段记录 juya 最后一次有内容的日期；`push.py` 在"juya not updated"分支里检查距今沉默天数，≥ 3 天告警到运维群。告警按日去重（一天最多一条），恢复后自动重置标记。
