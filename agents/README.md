# agents/ — 多 Agent 协作工具（通用）

本目录提供仓库内多个 AI agent 并发协作的最小机制，**与具体 agent 产品无关**：
任何能在此仓库运行 `python` 和 `git` 的 agent 都按同一规则协作。
当前由哪个 agent 干活并不重要——`--who` 只是看板上区分占用者的名字。

## 单一事实源

- `STATUS.md` —— 任务看板（未认领 / 进行中 / 已完成 + 认领人）
- `agents/.locks.json` —— 文件锁（某路径当前被谁占用；运行时状态，不入库，已在 `.gitignore`）

## 命令参考（统一在仓库根目录运行）

| 命令 | 作用 |
|---|---|
| `python agents/board.py status` | 查看任务看板 + 当前文件锁 |
| `python agents/board.py claim <任务ID> --who <名字> [--files a.py,b.py]` | 认领一个「未认领」任务，可顺带锁文件 |
| `python agents/board.py release <任务ID> --who <名字> [--force]` | 放弃任务，回到「未认领」 |
| `python agents/board.py lock <路径...> --who <名字>` | 锁住即将修改的文件（他人已锁则拒绝） |
| `python agents/board.py unlock <路径...> --who <名字>` | 释放自己名下的锁 |
| `python agents/board.py verify <任务ID> --run "<命令>"` | 只跑验收命令，不改看板 |
| `python agents/board.py done <任务ID> --who <名字> --run "<命令>"` | 验收命令 exit 0 才标记「已完成」并追加一行进度；失败则任务保持「进行中」，退出码 1 |

## 协作规则（已写入 AGENTS.md，每个 agent 会话自动读取）

认领 → 锁文件 → 修改 → 验收 → 登记；不得修改他人锁住的文件；验收失败不登记完成。

## 示例（某个 agent 接手 T4）

```
python agents/board.py status
python agents/board.py claim T4 --who my-agent --files sprite/tiers.py,sprite/sim_tokens.py
python agents/board.py done T4 --who my-agent --run "python -m unittest discover -s opportunities/tests -v"
python agents/board.py unlock sprite/tiers.py sprite/sim_tokens.py --who my-agent
```

## 兼容性说明

- 退出码：0 = 成功；1 = 冲突或验收失败（看板未被修改）。
- 支持 Windows / Linux / macOS；Python 3.8+，仅标准库。
- 任务看板文件若被人工编辑（如临时改状态），下次运行 `status`/`claim` 会按最新内容解析。
