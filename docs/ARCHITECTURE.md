# OpenLookout 小精灵架构

## 一句话
本地常驻的**主动判断闭环**：任意异常信号 → 取证 → **云端理解（默认）** → 白名单可逆行动 → 短汇报可撤销。  
层是**模块**，不是一层一个聊天 Agent。  
**不是**「先查是不是网络 / 内存 / 某类问题」——未见过的问题靠证据包 + 云端理解，不靠枚举异常清单。

## 通用环（2026-10-10 定稿）
```
观察（传感器插件）→ 取证（证据包）→ novel/cloud 定性（open 问题默认）
        → 白名单可逆执行 → recheck 直到解除（Engine open-until-resolved）
```
| 角色 | 负责 | 不负责 |
|---|---|---|
| 本地传感器 | focus/dwell、浏览失败、压力、网络可达性…立案 | 给问题定性、穷尽异常类 |
| 本地白名单 | flushdns / 挂起 / 记笔记 / rasdial…可逆动作 | 自由 shell、高风险自动做 |
| novel（云端） | **这是什么问题** + 候选白名单动作 | 常驻截图、绕过闸门 |
| Engine | 价值闸、账本、未解除持续推进 | 场景故事线 |

`needs_novel(..., prefer_novel=True)`：除 self/protected 外，open 问题默认问云端。  
本地启发式失败才升级 = **已废弃**。

## 为什么不是「每层一个独立 Agent」
| 层 | 做成独立 Agent？ | 原因 |
|---|---|---|
| 观察 | 否 | 要准、便宜、可回放 |
| 理解 | **默认云端**（有预算时） | 开放世界；本地只做闸与执行 |
| 判断/闸门 | 否 | 风险、可逆、价值闸必须确定 |
| 执行 | 否 | 本地可测、可撤销 |

## 四层模块（同一进程）
```
汇报/GUI → Engine → Investigate（discover→gather→novel→respond）→ 观察传感器
```

### 传感器插件（示例，非穷尽）
- stalemate：dwell/flicker
- network：HTTP 真通 / DNS / 代理端口（**执行器插件，非主脑**）
- pressure / annoyance / browse_error：同类

新问题类只 `register`；若必须改 `framework.py` 才能加 → 架构失败。

## 成本
- tier0 本地传感器常开
- tier1 可选本地小模型（触发视觉）
- tier2 云端 novel：open 问题默认，日预算硬顶；FakeNovelClient 测

## 研究线索
见 `docs/RESEARCH_PROACTIVE_OPENWORLD.md`（PROBE / ContextAgent / GUITester 等）。不声称穷尽异常列表。
