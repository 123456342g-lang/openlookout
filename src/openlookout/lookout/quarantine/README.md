# V1 隔离区说明

下列模块**保留在仓库里**，但**不是** `python3 -m lookout.v1` 的产品路径：

| 模块 | 原因 |
|---|---|
| `lookout/world.py` | 外部新闻/比赛/安全公告卡片 —— 定时机器人也能做，不是潜在需求洞察 |
| `lookout/opportunity_engine.py` | 创业赛道/机会发现 —— 找用户，不是以自己为用户挖潜在需求 |
| `lookout/world_kits/` | 依赖 world 卡片的预习包等 |
| `opportunities/` | Round 11–12 的机会与账本实验 |

V1 主入口只允许：detectors / history / sheet_audit / series_kit / solvers（验证用）/ surprise / inbox。
