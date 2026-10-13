# 文献笔记：开放世界观察 / 未指定问题 / 主动助手

日期：2026-10-10（box）。**不声称穷尽异常类别或论文全集。**

## 与 OpenLookout 的对齐
| 我们要的 | 文献里对应 |
|---|---|
| 持续观察 → 发现未点名的问题 | PROBE：search unspecified issues → identify bottleneck → resolve |
| 不定死 taxonomy | GUITester / GUITestScape：exploratory defect discovery；open-set judge |
| 理解用 LLM，本地传感器便宜 | ProAgent / ContextAgent：tiered / on-demand perception + proactive reasoner |
| 不把「是不是网络」当主脑 | 同上：先感知代价/情境，再理解意图；传感器可插拔 |

## 精选摘要（各 3–6 行）

### 1. PROBE — Beyond Reactivity (arXiv:2510.19771)
主动 = (1) 在个性化数据里搜**未指定**问题 (2) 点名 bottleneck (3) 选对可执行动作。1000 合成职场样本；前沿模型端到端约 **40%**。失败主因：根因识别、人际归因、参数不全。启示：我们的 novel 定性 + 白名单动作 + open-until-resolved 正对这三段；不要假设本地启发式能「悟」复杂故事。

### 2. ContextAgent (NeurIPS 2025) / ProAgent (arXiv:2512.06721)
可穿戴开放世界感知 → 是否需要主动服务 → 调工具。强调 **on-demand 分层感知**（常开便宜线索 + 按需富感知），降低误打扰。启示：我们「日志为主、触发截图为辅」同构；不要常驻截屏。

### 3. GUITester (ACL Findings 2026) / GUITestScape
探索式 GUI 缺陷发现：导航与验证解耦；LLM judge 评轨迹。挑战：目标导向会**掩盖**异常、把系统缺陷归因成 agent 失误。启示：小精灵发现器要「找代价/僵局」而不是「完成用户任务」；judge 不能默认「用户在用就没事」。

### 4. PC Agent (arXiv:2412.17589) / UFO2
桌面轨迹采集与 AgentOS；认知轨迹 + grounding。偏**执行任务**，不是「发现未指定麻烦」。可借鉴：观察在动作前缓存、混合 UIA/视觉；我们仍把理解放 novel，不把桌面控制当默认。

### 5. AgentSight (arXiv:2508.02736)
eBPF 边界观测：LLM 意图 ↔ 系统效应，二次 LLM 做语义风险。启示：传感器在应用外、框架无关；二次 LLM = 我们的 novel 角色。

## 对架构的直接改动（已落地）
- `prefer_novel=True`：open 问题默认定性走云端，不是「本地套路失败才升级」。
- network / stalemate = 传感器+白名单执行器，非主脑故事线。
- 文档明确：**不枚举世界上所有异常**。

## 微实验（见 `research/microexp/`）
1. **E1 synthetic_ui_traces**：合成 focus/dwell/flicker/假 browser_error 事件 → Investigator + FakeNovelClient → 是否不经 network discover 也能定性并白名单记下。
2. **E2 prefer_novel_vs_legacy**：同一本地高置信候选，对比 prefer_novel True/False 是否调用云端（度量「主理解是否仍在本地」）。
