# OpenLookout（瞭望手）

**V1 唯一核心：** 从可量化的本机行为痕迹里，挖出你说不出、也没察觉的需求，并交出已验证的方案。行为定位卡点；已核对的外部趋势打开新能力（不是新闻摘要）。

详见 **[V1.md](./V1.md)**。惊喜门控：**[lookout/SURPRISE.md](./lookout/SURPRISE.md)**。

```bash
python3 -m lookout.v1 --capture <backfill目录> --out <输出目录> --no-llm
```

- 历史回填（Windows）：`backfill_win/`（Day-1，不用先录几天）
- 每日最多 3 张卡；无证据 / 无指标 / 无成品 / 未过惊喜门控 → 不出卡
- 原始数据只留本机

## 不是什么

新闻助手、比赛提醒、创业点子机、多 Agent 账本、鼠标操控——这些已隔离，不是 V1（见 `lookout/quarantine/`）。

## 仓库结构（V1 相关）

| 路径 | 作用 |
|---|---|
| `lookout/v1.py` | **产品主入口** |
| `lookout/surprise.py` | 惊喜 / 潜在需求门控 |
| `lookout/trends/` + `trends.py` | 已核对趋势目录与行为匹配 |
| `lookout/feedback_rules.json` | 用户「不重要」降权 |
| `lookout/nexus.py` | 行为×趋势成品包 |
| `lookout/scale_sources.py` | 来源族统一 + 消融 |
| `lookout/detectors.py` / `history.py` / `sheet_audit.py` / `series_kit.py` | 行为规律发现 |
| `lookout/solvers.py` + `history.solve` | 构建并验证成品 |
| `backfill_win/` | Windows 历史回填 |
| `V1.md` | 锁定的核心与验收 |

## 原型与历史迭代

早期模拟人物流水线仍可用：`python3 -m lookout.run`（非 V1 主路径）。  
迭代记录见 `CHANGELOG.md`。`demo_private/`、`capture_userbf/` 含私有实测，**不进 git**。

## 依赖

Python 3、openpyxl；可选：LibreOffice（表格公式重算）、google-chrome（截图）、bubblewrap（沙箱）。云端模型任意 OpenAI 兼容接口（V1 可用 `--no-llm`）。
