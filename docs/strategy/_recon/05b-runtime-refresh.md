# 05b 运行时刷新：基线 vs 现在（重测卷宗）

> **采集窗口：2026-10-12 08:06:51 – 08:10:16（Asia/Shanghai, +08:00）。项目此刻正在运行。**
> 基线 = `05-measured-reality.md`（采集 2026-10-12 07:19–07:30）。本文件用**同一口径**重算，
> 逐项标注「改善 / 恶化 / 无变化」与幅度。
>
> **口径纪律**：`offers.jsonl`、`child_brain.log`、`supervisor.log` 等在采集期间持续增长。
> 每个数字都带**采集时刻**；跨两行的数字之间存在真实漂移，不是误差。
> 实证：`child_brain.log` 在 08:07:57 为 7,233 行，08:10:02 已为 7,244 行（+11 行 / 125 秒）。
>
> **全新指标**：基线卷宗**没有**截图库存、supervisor 重启计数、`拦截计数` 三项。凡标「无基线」者为首测，
> 不做「改善/恶化」判定。
>
> 只读采集：未杀进程、未运行 `sprite.proactive.live`、未调用 `desktop_*`、未写 `sprite_home\`、未执行 `docker`。

---

## 0. 采集环境（实测）

采集时刻 **2026-10-12 08:10:16**，`Get-Process` 快照：

| PID | 进程 | 内存 | 启动时间 | 与基线对比 |
|---|---|---|---|---|
| 12356 | python | 1 MB | 07:07:07 | **未变**（监督进程） |
| 24348 | pythonw | 6 MB | 07:07:06 | **未变** |
| 12488 / 25288 | python | 5 / 5 MB | 07:17:12 | **未变**（记录器子进程） |
| 5948 | python | 91 MB | **08:09:41** | **新增**（brain 重启后） |
| 29284 | pythonw | 32 MB | **08:09:41** | **新增**（GUI 重启后） |
| 15960 | python | 122 MB | 08:10:05 | 新增 |

> **重要漂移**：基线记录的 brain（PID 24344, 07:21:05）与 GUI（PID 18088, 07:21:05）**已不存在**，
> 于 **08:09:41** 被监督进程热更新重启。`supervisor.log` mtime = 08:09:41 与之吻合。
> 即：**在本次采集窗口内发生过一次 brain+GUI 重启**。账本为 append-only，故下述计数不受影响；
> 但「同一进程连续视觉上下文」这条已被打断。`会话已建立` 全文 300 次（基线 294）→ 重启次数在增加。
>
> **伴随观测（08:12:14，实测）**：`companion\runs\` 目录数在 **08:09:38 为 387 → 08:12:14 为 391**（+4）。
> 其中重启后 30 秒内连续出现 `20261012-081024` / `081032` / `081040` 三个目录（**间隔约 8 秒**），
> 随后归于平静（最后一个写于 08:10:41）。这是对 §5.2 中 `WinError 183`（同一秒启动两次回合、抢占同一 run 目录）
> 竞态的**现场佐证**：重启后短时间内会高频新建会话目录。

---

## 1. 核心对比表

**括号内 `[A#]` 为附录 A 的完整命令；采集时刻为该行数字的实测时刻。**

| # | 指标 | 基线（07:19–07:30） | 现在 | 变化 | 判定 | 采集时刻 | 置信 | 命令 |
|---|---|---|---|---|---|---|---|---|
| 1 | `offers.jsonl` 行数 | 291 | **292** | +1（+0.3%） | 无变化（自然增长） | 08:07:39 | 实测 | [A1] |
| 2 | 唯一 `id` 数 | 未测 | **192**（55 个 id 各有 2 行） | — | 无基线 | 08:07:39 | 实测 | [A2] |
| 3 | 气泡字数 P50 | 124 | **121** | −3（−2.4%） | **无变化**（仍 > 60，门未过） | 08:07:39 | 实测 | [A3] |
| 4 | 气泡字数 P75 | 146 | **145.25** | −0.75（−0.5%） | 无变化 | 08:07:39 | 实测 | [A3] |
| 5 | 气泡字数 max | 197 | **197** | 0 | 无变化 | 08:07:39 | 实测 | [A3] |
| 6 | ≤60 字达标率 | 13.7% | **13.7%**（40 / 292） | 0.0 pp | **无变化** | 08:07:39 | 实测 | [A3] |
| 7 | ≤60 字达标率（按 `id` 去重口径） | 未测 | **19.8%**（38 / 192）；P50=109.5 | — | 无基线（稳健性检验） | 08:09:38 | 实测 | [A4] |
| 8 | `action=none` 条数 | 283 | **284** | +1 | 无变化 | 08:07:39 | 实测 | [A5] |
| 9 | `action=tidy_desktop` | 1 | **1** | 0 | 无变化 | 08:07:39 | 实测 | [A5] |
| 10 | `action` 空 | 7 | **7** | 0 | 无变化 | 08:07:39 | 实测 | [A5] |
| 11 | `kind=offer` | 167 | **167** | 0 | 无变化 | 08:07:39 | 实测 | [A6] |
| 12 | `kind=companion` | 122 | **123** | +1 | 无变化 | 08:07:39 | 实测 | [A6] |
| 13 | `auto_failed` 条数 | 36 | **36** | 0 | 无变化（假失败未修） | 08:07:39 | 实测 | [A6] |
| 14 | 按天：10-10 | 43 | **43** | 0 | 无变化 | 08:07:39 | 实测 | [A7] |
| 15 | 按天：10-11 | 245 | **245** | 0 | 无变化 | 08:07:39 | 实测 | [A7] |
| 16 | 按天：10-12 | 3 | **4** | +1 | 无变化 | 08:07:39 | 实测 | [A7] |
| 17 | `feedback.jsonl` 行数 | 8 | **9** | +1（+12.5%） | 无变化（样本仍近零） | 08:07:39 | 实测 | [A8] |
| 18 | `undo.jsonl` 条数 | 7 | **10** | **+3（+42.9%）** | **恶化**（动手次数上升） | 08:07:39 | 实测 | [A9] |
| 19 | `restore_map.jsonl` 记录数 | 277 | **5,466** | **+5,189（×19.7）** | **严重恶化** | 08:07:39 | 实测 | [A10] |
| 20 | 其中 `held` | 272 | **5,461** | **+5,189（×20.1）** | **严重恶化** | 08:07:39 | 实测 | [A10] |
| 21 | 隔离区占用 | 201.1 MB | **5,368.0 MB** | **+5,166.9 MB（×26.7）** | **严重恶化** | 08:07:39 | 实测 | [A10] |
| 22 | 原始路径已不存在的条数 | 240 | **5,438** | **+5,198（×22.7）** | **严重恶化** | 08:07:39 | 实测 | [A11] |
| 23 | 模型段总数 | 389 | **457** | +68（+17.5%） | **恶化** | 08:07:57 | 实测 | [A12] |
| 24 | 模型等待累计 | 7,978.3 s（133.0 min） | **10,303.4 s（171.7 min）** | **+2,325.1 s（+29.1%）** | **恶化** | 08:07:57 | 实测 | [A12] |
| 25 | 单段耗时中位 | 15.0 s | **15.9 s** | +0.9 s（+6.0%） | **恶化（轻微）** | 08:07:57 | 实测 | [A12] |
| 26 | 单段耗时最大 | 130.1 s | **201.9 s** | **+71.8 s（+55.2%）** | **严重恶化** | 08:07:57 | 实测 | [A12] |
| 27 | 耗时 >30 s 段数 | 71（18.3%） | **103（22.5%）** | +32（**+4.2 pp**） | **恶化** | 08:07:57 | 实测 | [A12] |
| 28 | 输入 token 合计 | 1,821,155 | **2,449,980** | +628,825（+34.5%） | 恶化 | 08:07:57 | 实测 | [A12] |
| 29 | 输出 token 合计 | 278,637 | **351,630** | +72,993（+26.2%） | 恶化 | 08:07:57 | 实测 | [A12] |
| 30 | 单段输入 token 中位 / 最大 | 3,979 / 16,304 | **4,355 / 32,721** | 中位 +9.5%；**最大 ×2.0** | **恶化** | 08:07:57 | 实测 | [A12] |
| 31 | `会话已建立` 次数 | 294 | **300** | +6（+2.0%） | 恶化（重启增多） | 08:07:57 | 实测 | [A12] |
| 32 | `Traceback` 总数 | 395 | **403** | +8（+2.0%） | 无变化（未归零） | 08:07:57 | 实测 | [A13] |
| 33 | 最后一次 Traceback 距日志末尾 | 88 行 | **154 行** | +66 行 | 无变化 | 08:07:57 | 实测 | [A13] |
| 34 | 含 `Error` 行数 | 882 | **890** | +8（+0.9%） | 无变化 | 08:07:57 | 实测 | [A14] |
| 35 | `SSLEOF` 次数 | 200 | **200** | 0 | **无变化（流血未止）** | 08:07:57 | 实测 | [A14] |
| 36 | `retry` 次数 | 102 | **102** | 0 | **无变化（流血未止）** | 08:07:57 | 实测 | [A14] |
| 37 | 末 1500 行内 `SSLEOF` | 200（全文同值） | **200**（= 全文全部命中该窗口） | — | **无变化** | 08:10:02 | 实测 | [A15] |
| 38 | 末 1500 行内 `direct model call failed` | 163（98 SSL + 65 URLError） | **145** | −18（−11.0%） | 改善（轻微） | 08:10:02 | 实测 | [A15] |
| 39 | `profile requested unavailable tools` | 末 1500 行内 10 次 | 全文 **79**；末 1500 行内 **0** | 全文增，近端归零 | **口径不同，判为「恶化后近期未复现」** | 08:10:02 | 实测 | [A15] |
| 40 | `WinError 183`（同秒抢目录） | 1 | **1** | 0 | 无变化 | 08:10:02 | 实测 | [A15] |
| 41 | `decisions.jsonl` 行数 | 226 | **245** | +19（+8.4%） | 无变化（自然增长） | 08:09:22 | 实测 | [A16] |
| 42 | `quiet` 占比 | 151 / 226 = 66.8% | **163 / 245 = 66.5%** | −0.3 pp | **无变化** | 08:09:22 | 实测 | [A16] |
| 43 | 开口占比（offer+companion） | 33.2% | **33.5%** | +0.3 pp | **无变化** | 08:09:22 | 实测 | [A16] |
| 44 | `decisions` 中 `actions` 非空 | 8 | **9** | +1 | 无变化 | 08:09:22 | 实测 | [A16] |
| 45 | `GUIDE.md` 字节数 | 3,283 | **3,283** | 0 | 无变化（但 mtime 已刷新至 08:07:44） | 08:10:02 | 实测 | [A17] |
| 46 | `supervisor.log` 重启计数 | 无基线 | **411 次** `brain 退出，已自动拉起` | — | 无基线（新指标） | 08:07:57 | 实测 | [A18] |
| 47 | 全量热更新次数 | 无基线 | **177 次** `重启全部子进程` | — | 无基线（新指标） | 08:07:57 | 实测 | [A18] |
| 48 | 只热更新窗口 | 无基线 | **241 次** | — | 无基线（新指标） | 08:07:57 | 实测 | [A18] |
| 49 | `brain 代码变了` 重启 | 无基线 | **163 次** | — | 无基线（新指标） | 08:07:57 | 实测 | [A18] |
| 50 | 截图库存：张数 | 无基线 | **1,827 张 .jpg** | — | 无基线（新指标） | 08:09:38 | 实测 | [A19] |
| 51 | 截图库存：占用 | 无基线 | **242.4 MB** | — | 无基线（新指标） | 08:09:38 | 实测 | [A19] |
| 52 | 截图库存：run 目录数 | 无基线 | **387 个**；全部文件 7,022 个 / 675.2 MB | — | 无基线（新指标） | 08:09:38 | 实测 | [A19] |
| 53 | **拦截计数** | 无此埋点 | **0（落库）** | — | **门未过（见 §2）** | 08:09:07 | 实测 + 推断 | [A20] |

### 1.1 判定汇总

| 判定 | 条数 | 代表项 |
|---|---|---|
| **严重恶化** | 5 | 隔离区记录 ×19.7 / `held` ×20.1 / 占用 ×26.7 / 原始路径消失 ×22.7 / 单段最大耗时 +55.2% |
| **恶化** | 12 | `undo` +42.9%、模型段 +17.5%、累计等待 +29.1%、>30 s 占比 +4.2 pp、输入 token 最大 ×2.0、重启计数增加 |
| **无变化** | 20+ | **气泡 P50（124→121）、达标率 13.7%、`action=none`、`auto_failed` 36、SSLEOF 200、retry 102、开口率 33.5%** |
| **改善** | 1 | 末 1500 行 `direct model call failed` 145（−11.0%） |
| **无基线（首测）** | 7 | 唯一 id、去重口径达标率、supervisor 五类计数、截图库存、拦截计数 |

> **一句话结论**：气泡长度这件事**一个字节都没改善**；`auto_failed` 假失败**一条没修**；
> SSL 重试风暴**完全没变**；而**真实动手量（隔离区）膨胀了约 20–27 倍**，延迟上限从 130 s 涨到 202 s。

---

## 2. 三个可测门：今天全部不成立

判据出自 `docs/strategy/README.md` 第 106 行、`03-risk-redteam.md` 第 77–78 行。

### 门 1 — 气泡 P50 ≤ 60 字 → ❌ **不成立**

| 口径 | P50 | P75 | ≤60 字占比 | 采集时刻 |
|---|---|---|---|---|
| 原始行（与基线同口径） | **121 字** | 145.25 | **13.7%**（40/292） | 08:07:39 |
| 按 `id` 去重 | **109.5 字** | 138.2 | **19.8%**（38/192） | 08:09:38 |

**真实值：P50 = 121 字（门限 60，超标 101.7%）。** 两种口径都不达标，差距非口径问题。
分日明细（08:07:39）：10-11 `offer` **147 条全部 > 60**，中位 137；10-12 `companion` 4 条中位 72.5。

### 门 2 — 24h 内重复文本 = 0 → ❌ **不成立**

| 口径 | 24h 窗口内重复行数 | 采集时刻 |
|---|---|---|
| 原始行 | **108** | 08:07:39 |
| 按 `id` 去重（排除 `shown`+终态配对） | **8** | 08:09:38 |

去重后仍为 **8 条真重复**（同一句话在 24h 内重发），全部集中在 10-10 19:38–20:44：

```
10-10 19:38:16 → 19:38:34   topic='磁盘'  「C盘快满了，要我清一下吗？」
10-10 19:38:34 → 19:38:53   topic='磁盘'  同上（间隔 19 s）
10-10 19:38:53 → 19:40:50   topic='磁盘'  同上
10-10 19:38:53 → 19:40:50   topic=''      「C盘只剩0.6GB了，要我清一下吗？」
10-10 19:40:50 → 19:55:25   topic='磁盘'  同上（间隔 14.6 min）
10-10 19:55:25 → 20:04:32   topic='磁盘'  同上（间隔 9.1 min）
10-10 20:04:32 → 20:33:14   topic='磁盘'  同上（间隔 28.7 min）
10-10 20:33:14 → 20:43:58   topic='磁盘'  同上（间隔 10.7 min，终态 auto_started）
```

**真实值：去重后 8 条（原始行 108 条）。** 同一句话最多重发 **8 次**（基线记「9 次」——9 是含 `shown`+终态配对的原始行数）。

> **根因（实测，`help.py:21-24, 97`）**：现有闸门 `worth_saying()` 的窗口是
> `OFFER_COOLDOWN_S = 300`（5 分钟，offer）/ `COMPANION_COOLDOWN_S = 600`（10 分钟，companion），
> **不是 24 小时**。上列 8 条共 7 个相邻间隔，其中 **4 个已超过 5 分钟**（14.6 / 9.1 / 28.7 / 10.7 分钟），
> 从窗口外漏过；只有 3 个（18 s / 19 s / 117 s）本应在 5 分钟窗口内被拦。
> 所以「24h 内同 topic 不重复」这条**今天根本不是已实现的能力**，而基线卷宗的判据把它当成已有闸门的失效——**口径需要更正**：
> 不是闸门失效，是**闸门比要求松了 288 倍**（5 min vs 24 h）。

### 门 3 — 拦截计数 > 0 → ❌ **不成立（实测 0，且该埋点不存在）**

| 证据 | 结果 | 采集时刻 |
|---|---|---|
| `offers.jsonl` 中 `result` 取值 | `shown` / `auto_started` / `auto_failed` / `auto_completed` / `retracted` —— **无任何 `suppressed`/`拦截` 行** | 08:07:39 |
| `child_brain.log` 中 `suppressed` / `decision:suppressed` | **0 次** | 08:09:07 |
| `child_gui.log` / `supervisor.log` 同上 | **0 次** | 08:09:07 |
| `decisions.jsonl` 中 `suppressed` 字段 | **0 行** | 08:09:07 |
| `decisions.jsonl` 中「拦截」二字 | 5 行，**全部是模型自己叙述「被现场变化拦截」**，非闸门计数 | 08:09:22 |

**代码事实**：`self.suppressed` 在 `vista/benchmarks/desktop/session.py:37` 定义、`:105` 自增，
但**只存在于内存**——`session.close()`（`:187-188`）不落盘，`ToolReply` 的 `event_text="decision:suppressed"`（`:107`）
也只进内存事件流，未写入任何 jsonl 或日志。**因此「拦截计数」今天无法从磁盘读出，实测值 = 0 条记录。**

**独立的推断交叉验证（推断，非实测）**：`decisions.jsonl` 在闸门**之前**写入（`session.py:99-100`），
`offers.jsonl` 在闸门**之后**写入（`:104-112`）。故可对 brain 路径做差集：

- 候选开口（`kind∈{offer,companion}`、`say` 非空、offer 需 `confidence≥0.7`）：**79 条**
- 其中 `say` 出现在 `offers.jsonl`：**79 条**
- **差集 = 0 条 → brain 路径推断拦截数 = 0**

**数据边界**：该推断仅覆盖 brain/session 路径（10-11 19:17 起）。
更早的 `help.check_once()` 路径（10-10 → 10-11 19:17，占 158 条 `shown`）在闸门拦下时**不写任何记录**，
**无法推断**（未知）。

> **门 3 结论：不成立。** 拦截计数不是「0 次拦截」，而是「**根本没记**」——
> 即便闸门真的拦了，今天也拿不到这个数字。这正是基线卷宗 §8 把「记拦截计数」列为验收条件的原因。

---

## 3. offers.jsonl 细分（实测，采集 08:07:39 / 08:09:38；文件 mtime 08:06:16，128,407 B）

### 3.1 `kind` × `result` 交叉（原始行口径）

| kind | shown | auto_started | auto_failed | auto_completed | retracted | 合计 |
|---|---|---|---|---|---|---|
| `offer` | 68 | 54 | 36 | 9 | – | **167** |
| `companion` | 123 | – | – | – | – | **123** |
| （空） | 1 | – | – | – | 1 | **2** |
| 合计 | 192 | 54 | 36 | 9 | 1 | **292** |

与基线（offer 167 / companion 122 / 空 2）相比：**仅 companion +1**，其余逐格完全一致。

### 3.2 重复 topic Top（实测 08:07:39）

| 排名 | topic | 条数 |
|---|---|---|
| 1 | `''`（空标签） | **157** |
| 2 | `磁盘` | 9 |
| 3 | `内存吃紧` | 6 |
| 4 | `内存回收` | 4 |
| 5 | `桌面整理` / `内存腾挪` / `内存只剩 0.35GB` / `Codex 被 503 打断` | 各 3 |

> **空 topic 占 53.8%**。这与 `help.py:122-124` 的注释一致（「模型经常忘了给标签」），
> 也正是闸门退化到 `_fingerprint(say)` 兜底的原因。**但注意**：兜底指纹去掉了数字与虚词，
> 所以「C盘快满了」与「C盘只剩0.6GB了」会归为同类——`held` 那 8 条重复里确实有一组这样被归并。

### 3.3 按天 × kind 的字数（实测 08:07:39）

| 日期 | kind | n | 中位 | 最大 | >60 字 |
|---|---|---|---|---|---|
| 10-10 | companion | 21 | 87 | 142 | 16（76%） |
| 10-10 | offer | 20 | 18 | 189 | 7（35%） |
| 10-11 | companion | 98 | **97** | 196 | **79（81%）** |
| 10-11 | offer | 147 | **137** | 197 | **147（100%）** |
| 10-12 | companion | 4 | **72.5** | 87 | 3（75%） |
| 10-12 | （空 kind） | 0 | – | – | – |

**关键**：基线记录的「10-11 当天 offer 达标率 0/147」今天**仍然成立**，一条未变。
10-12 最新 4 条 companion 中位 72.5 字（基线为 3 条 / 87 字）——**仍远超 60**。

---

## 4. 动作账本（实测，采集 08:07:39）

### 4.1 `undo.jsonl`：7 → **10** 条（+3）—— 恶化

| # | `desc` |
|---|---|
| 1 | 整理桌面 79 个文件（只移动） |
| 2–7 | 清理 40 / 12 / 40 / 30 / 30 / 120 个可再生文件（隔离区，可还原） |
| **8** | **清理 200 个可再生文件（隔离区，可还原）** ← 新增 |
| 9 | 清理 30 个可再生文件（隔离区，可还原） |
| **10** | **清理 4960 个可再生文件（隔离区，可还原）** ← 新增 |

> **`undo_kind` 字段仅 1 条有值（`desktop_tidy`），其余 9 条为空**（与基线相同的字段稀疏问题）。
> 第 10 条「4960 个文件」一次动作即解释了 §4.2 的绝大部分膨胀。

### 4.2 `quarantine/restore_map.jsonl`：277 → **5,466** 条 —— 严重恶化

| 指标 | 基线 | 现在 | 变化 |
|---|---|---|---|
| 总记录 | 277 | **5,466** | **×19.7** |
| `status=held` | 272 | **5,461** | **×20.1** |
| `status=restored` | 5 | **5** | 0 |
| held 占用（`sum(stored)`） | 201.1 MB | **5,368.0 MB** | **×26.7** |
| 原始路径已不存在（held 内） | 240 | **5,438** | **×22.7** |
| 原始路径已不存在（全状态） | — | **5,443** | — |
| `mode` | — | 全部 `move` | — |
| held 时间跨度 | — | 2026-10-11 07:18:59 → 2026-10-12 07:58:18 | — |

> **口径核对**：`size` 与 `stored` 两列的 held 求和**完全相同**（5,368.0 MB），说明无截断/压缩存储。
> 基线 201.1 MB 由此确认同口径（held × `stored`）。
>
> **判定：这是本轮最严重的恶化**。用户机器上被移走的文件从 272 个涨到 5,461 个，
> 且 **99.6%（5,438/5,461）的原始路径已不存在**——撤销映射指向的位置已经空了。
> 「全部可还原」这一承诺的**可验证性在下降**：映射还在，但还原目标已被别的进程改动/占用。

### 4.3 隔离区目录的物理占用（实测 08:06:51）

`quarantine\` 顶层 **5,462 个文件 / 5,370.3 MB**，与 `restore_map.jsonl` 的 held 计数（5,461）自洽。

---

## 5. 模型段与延迟（实测，采集 08:07:57；`child_brain.log` 7,233 行，mtime 08:07:48）

**先确认实际文件名与格式（任务要求）**：实际存在的是 `sprite_home\perceive\child_brain.log`（无 `brain.log` 于此目录）
与 `sprite_home\perceive\supervisor.log`。日志行形如：

```
[brain] 会话已建立：持续视觉上下文开始
[brain] model segment=N elapsed=X.Xs tokens=A/B tools=[...]
[brain] turn done boundary=decision_complete decisions=N
```

`supervisor.log` 是**另一种格式**（`HH:MM:SS 中文消息`，无模型段记录）——**模型段与耗时只能从 `child_brain.log` 取**，
`supervisor.log` 只提供重启/热更新计数（见 §5.3）。

### 5.1 逐项对比

| 指标 | 基线 | 现在 | 变化 |
|---|---|---|---|
| 日志行数 | 6,959 | **7,233**（08:07:57）→ **7,244**（08:10:02） | 持续增长 |
| 模型段总数 | 389 | **457** | +68（+17.5%） |
| 输入 token 合计 | 1,821,155 | **2,449,980** | +34.5% |
| 输出 token 合计 | 278,637 | **351,630** | +26.2% |
| 等待累计 | 7,978.3 s（133.0 min） | **10,303.4 s（171.7 min）** | **+29.1%** |
| 单段耗时中位 | 15.0 s | **15.9 s** | +6.0% |
| 单段耗时最大 | 130.1 s | **201.9 s** | **+55.2%** |
| >30 s 段数 | 71（18.3%） | **103（22.5%）** | +32（+4.2 pp） |
| >60 s 段数 | 未测 | **20** | 首测 |
| >120 s 段数 | 未测 | **3** | 首测 |
| 单段输入 token 中位 / 最大 | 3,979 / 16,304 | **4,355 / 32,721** | 中位 +9.5%；**最大 ×2.0** |
| `会话已建立` | 294 | **300** | +6 |
| `turn done` | 未测 | **1,009** | 首测 |

> 基线卷宗 §5 的脚注已预告「redteam 于 07:50 复算为 390 段 / 最大 201.9 s」。
> 本次 **08:07:57 复算 = 457 段 / 最大 201.9 s**：**最大值停在 201.9 s 未再上升**（同一极端段），
> 但**段数与累计等待继续增长**。基线「单段最大 130.1 s」应视为**已被 201.9 s 取代**。

### 5.2 稳定性：SSLEOF 风暴**完全未变**

| 指标 | 基线（全文） | 现在（全文，08:07:57） | 现在（末 1500 行，08:10:02） |
|---|---|---|---|
| `Traceback` | 395 | **403** | 9 |
| 含 `Error` 行 | 882 | **890** | — |
| `SSLEOF` | 200 | **200** | **200** |
| `retry` | 102 | **102** | **102** |
| `direct model call failed` | — | — | **145** |
| `profile requested unavailable tools` | 末 1500 行内 10 | 全文 **79** | **0** |
| `WinError 183` | 1 | **1** | 1 |

**两个精确读数（重要）**：
1. **全部 200 次 `SSLEOF` 与全部 102 次 `retry` 都落在末 1500 行（第 5,745 行之后）**——
   即 TLS 中断**集中发生在最近一小时**，且与基线**逐数相同**（200/102 → 200/102）。**这不是噪声，是稳定的持续故障率。**
2. `profile requested unavailable tools` 全文 79 次但**末 1500 行内 0 次** → 该确定性 bug 的爆发集中在中段历史，
   **最近一小时未复现**。基线的「10 次」落在当时末 1500 行内，两窗口不完全重叠（基线窗口 5,459–6,959，现窗口 5,745–7,244），
   故**不可直接相减**，只能说：全文计数增加，近端归零。

**Traceback 位置分桶**（1000 行/桶，08:07:57）：

```
行     0-  999 : 72
行  1000- 1999 : 94
行  2000- 2999 : 118   ← 历史峰值
行  3000- 3999 : 42
行  4000- 4999 : 42
行  5000- 5999 : 26
行  6000- 6999 :  2
行  7000- 7999 :  7   ← 最新桶，基线此桶为 1
末条 Traceback 在第 7,078 行，距末尾 154 行
```

与基线（末桶 1 次 / 距末尾 88 行）相比：**最新桶 1 → 7，崩溃未归零且近期抬头**。

### 5.3 supervisor.log：重启是常态（首测，08:07:57；1,072 行，mtime 08:06:53）

| 事件 | 次数 |
|---|---|
| `brain 退出，已自动拉起` | **411** |
| `重启全部子进程`（热更新） | **177** |
| `只热更新窗口` | **241** |
| `brain 代码变了：重启 brain` | **163** |
| `gui 退出，已自动拉起` | 55 |
| `help 退出，已自动拉起` | 11 |

按小时分布峰值在 **18 时（336 条）**、19 时（137）、14 时（71）。
**411 次 brain 拉起 ≈ 每 2.3 分钟一次进程重启**（跨 ~14 小时日志跨度）。
本次采集窗口内也发生了 1 次（08:09:41，见 §0）。

---

## 6. 截图库存与隐私（实测 + 代码实测）

### 6.1 本地库存（首测，08:09:38）

| 指标 | 值 |
|---|---|
| `sprite_home\companion\runs\` 下 `.jpg` | **1,827 张 / 242.4 MB** |
| run 目录数 | **387** |
| 全部文件（含 jsonl/artifacts） | 7,022 个 / **675.2 MB** |
| 2026-10-10 | 391 张 / 52.4 MB |
| 2026-10-11 | 1,282 张 / 172.8 MB |
| 2026-10-12（至 08:09） | **154 张 / 17.2 MB** |
| 最新帧 | `runs\20261012-075803\artifacts\context\visuals\turn_000017_frame_0.jpg`，mtime **08:07:50** |

> **10-12 单日 8 小时不到已产生 154 张**，按此外推全天约 **460 张 / 51 MB**。
> **无保留策略**：全库 `src\openlookout` 内**未发现**针对 `runs/` 或 `visuals/` 的删除/TTL/`rmtree`
> （grep `rmtree|prune|retain|cleanup_runs|max_age` 的命中全部属于其它模块：lookout、arc3、demo、runner 自清理）。
> 帧文件写入后 `chmod(0o400)` 变为只读（`vista\core\support.py:299`），**只增不减**。

### 6.2 是否仍逐帧全屏上传 → **是**（代码实测）

| 环节 | 位置 | 事实 |
|---|---|---|
| 截屏 | `vista\benchmarks\desktop\session.py:19-24` `screen_visual()` | `ImageGrab.grab()` **抓整个虚拟屏（含多显示器）**，`.convert("RGB")`，等比缩放到 **宽 1280**，存 **JPEG quality 75** |
| 采集频率 | `vista\benchmarks\desktop\brain.py:89-94` `LiveScreen._run()` | `while not stop.wait(2)` → **每 2 秒抓一次全屏** |
| 是否都上传 | `brain.py:60-75` `sample()` | 仅当 **缩略图变化 / 前台窗口变化 / feedback 变化**时才更新 `ScreenSample`。即：**抓屏每 2 s，上传按「画面变化」**（有变化才成为新 CURRENT） |
| 上传路径 | `brain.py:883` `session.observe(vis)` → `ObservationBundle` → `vista\core\contracts.py:163` `base64.b64encode(view.data)` | 每个决策 step 把当前帧以 **base64 JPEG** 附给模型 |
| 旁路上传 | `sprite\proactive\help.py:59-63` `ask()` | 旧 help 通道**每次 `check_once` 都把最新帧 base64 发给模型**（该通道 10-11 19:17 后已不在主路径） |
| 落盘 | `vista\core\support.py:290-301` | 每个「新见到」的视觉写入 `<run>\artifacts\context\visuals\turn_%06d_frame_0.jpg`，`chmod(0o400)` |

**结论**：**仍是全屏、逐帧（按变化帧）base64 上传 + 本地全量留档。**

### 6.3 有无遮挡逻辑 → **完全没有**（代码实测；「不存在」为强断言）

对 `src\openlookout` 全库检索 `mask|blur|redact|occlude|exclude|sensitive|password|region|crop|resize|thumbnail|downscale`：
命中的**全部**与屏幕隐私无关，逐条列明以免误读：

| 命中处 | 实际是什么 |
|---|---|
| `recorder\record.py:59-61` `mask` | Linux inotify 事件掩码，不是图像遮罩 |
| `vista\benchmarks\arc3\render.py:42-45` `mask` | 游戏像素网格渲染线，不是隐私遮挡 |
| `vista\backends\claude\mcp_host.py:424` `"<redacted>"` | 日志里脱敏 **credential 键值**，不涉及截图 |
| `real_data\convert_rlkwic.py:100` `"[redacted]"` | 离线数据集里脱敏人名，不涉及截图 |
| `session.py:20-23` `convert/resize/save(quality=75)` | **只是缩放与压缩，不是遮挡** |

**明确不存在的能力**（负面清单，逐项确认未找到）：
- ❌ 密码框/敏感区域的遮挡、打码、模糊
- ❌ 指定窗口排除（白名单/黑名单）
- ❌ 自窗口排除——小精灵自己的气泡是 `-topmost` 窗口（`sprite\gui.py:133`），
  `ImageGrab.grab()` 会**把小精灵气泡本身拍进截图再上传**
- ❌ 截图前的用户确认 / 提示 / 暂停开关
- ❌ 上传审计（哪一帧去了哪里，无记录）
- ❌ 本地截图的 TTL / 上限 / 自动清理

**风险量级（推断）**：按 §6.1 的 1,827 张、每张 ≈ 133 KB，本机已留存约 **242 MB 的全屏画面史**，
跨度自 2026-10-10 17:50 起；其中包含用户所有的窗口内容（浏览器、终端、文档）。

---

## 7. 「接受率」今天能否算出来？→ **不能**（实测 + 代码实测）

### 7.1 现状：三种状态**一个都不落库**

`offers.jsonl` 实际出现过的 `result` 取值只有 5 种（08:07:39）：
`shown`(192) / `auto_started`(54) / `auto_failed`(36) / `auto_completed`(9) / `retracted`(1)。

**`accepted`、`dismissed`、`timeout` 各 0 行。** 但代码里它们**是被承认的状态**——
`help.py:111` 显式读取 `{"accepted", "auto_started", "auto_completed", "undone"}`，
`help.py:109` 读取 `dismissed`，`live.py:293` 读取 `{"auto_started","auto_completed","accepted","undone","undo_requested"}`。
**即：读取端已就位，写入端缺失。**

逐状态溯源（GUI 侧实测）：

| GUI 状态 | 触发点（实测） | 数据流 | 是否落库 |
|---|---|---|---|
| **accepted**（点「好」） | `sprite\gui.py:198` 按钮 `("好", ("ok", None))` → `:249` `on_choice(None, ok=True)` | `sprite\proactive\live.py:252-257` `on_choice()` → `if not offer or i is not None: return` → 只执行 `w.hide(expired=False)` | ❌ **丢弃** |
| **rejected**（点「不用」） | **GUI 里根本没有这个按钮**：`sprite\gui.py:193-200` `_buttons()` 只会产出 `详情` / `options` / `撤销` / `好` | 无 | ❌ **不存在**（连产生都产生不了） |
| **timeout**（气泡自动消失） | `sprite\gui.py:187` `after(wait*1000, ... self.hide(expired=True))` → `:189-190` `hide(expired=True)` → `self.on_expire()` | `sprite\proactive\live.py:275` 构造窗口时传入 **`lambda: None`**（空函数） | ❌ **丢弃** |

**附带后果（重要）**：因为 accepted/timeout 都不写，一条气泡超时消失后 `offers.jsonl` 里**永远停在 `shown`**。
于是 `help.recently_said()`（`help.py:114`）把它当「说过但没回应」——只看 5/10 分钟窗口；
`live.py: offer_status()`（`:367`）也永远返回 `shown`。**用户沉默与用户接受，在数据上完全不可区分。**

### 7.2 最小改动点（**仅指名文件 + 函数，不写代码**）

写入端已有现成函数，**不需要新建账本、不需要新字段、不需要改 schema**：

| # | 文件 | 函数 / 位置 | 改什么 |
|---|---|---|---|
| 1 | `sprite\proactive\live.py` | `run_gui()` 内嵌 `on_choice()`（≈252 行） | 在 `w.hide(expired=False)` 之前，用闭包里的 `offer_state["offer"]` 调 `record_offer_result(offer, "accepted")`。**「好」按钮此刻已能到达这里，只差一次写账。** |
| 2 | `sprite\proactive\live.py` | `run_gui()` 中 `SpriteWindow(root, DIR, on_choice, on_undo, lambda: None)`（≈275 行） | 把 `lambda: None` 换成真正的 `on_expire` 回调：`record_offer_result(offer_state["offer"], "timeout")`。**超时事件已在触发，只是被丢进空函数。** |
| 3 | `sprite\gui.py` | `SpriteWindow._buttons()`（≈193-200 行） | 为带 `action_id` 的气泡**新增一个「不用/拒绝」按钮**（新的 action 元组，如 `("dismiss", id)`）。这是三步里**唯一需要加 UI** 的一步——rejected 今天没有任何入口。 |
| 4 | `sprite\gui.py` | `SpriteWindow._click()`（≈243-250 行） | 把上一步的新 action 路由到一个 `on_dismiss` 回调（或 `on_choice` 的第三个分支）。 |
| 5 | `sprite\proactive\live.py` | `run_gui()` 内嵌 `on_choice()` 或新增 `on_dismiss()` | 收到拒绝时调 `record_offer_result(offer, "dismissed")`。 |

**落点与连接键（已验证可用）**：

- **写入函数**：`sprite\proactive\live.py: record_offer_result(offer, result, **extra)`（**第 360 行**），
  append 到 `sprite_home\perceive\offers.jsonl`，并自带 `t_answer=time.time()` 时间戳。
- **join key 已存在**：`offer["id"]`。点击时刻它就在闭包里——
  `live.py:254` `offer = offer_state["offer"]`，且气泡消息带 `action_id=offer.get("id")`（`live.py:103`、`gui.py:198`）。
  **不需要新增任何标识字段。**
- **读取端已就位**（改完即可算）：`sprite\proactive\help.py: recently_dismissed()`（77 行）与 `recently_said()`（88 行）
  会自动开始尊重这些状态；`vista\benchmarks\desktop\chat_planner.py: observe()`（约 66-75 行）
  本就按 `accepted`/`dismissed` 累计并按 topic 存档。
- **注意**：`chat_planner.py` 头部自述为 "Legacy conversation experiment, retained for reference only"，
  且 `brain.py` 主路径不经过它——**不能假设它已消费这些事件**，需在改完后单独确认。

**验收（改完后立刻可算）**：
`接受率 = count(result="accepted") / count(result="shown")`，另加 `dismissed`、`timeout` 两列即可构成完整漏斗。
今天的分母已经存在（192 条 `shown`），**分子为 0 是因为没记，不是因为没人点**。

---

## 8. 三态标注：实测 / 推断 / 未知

### 实测（已直接读取文件或代码，数字可复现）
- §1 表中标「实测」的全部 53 行。
- §2 三个门的真实值：P50=121、24h 重复（去重）8 条、拦截记录 0 条。
- §4 隔离区 5,466 / held 5,461 / 5,368.0 MB / 原始路径消失 5,438。
- §5 模型段 457 / 10,303.4 s / 中位 15.9 s / 最大 201.9 s。
- §6 截图 1,827 张 / 242.4 MB；上传与落盘路径（`session.py:19-24`、`brain.py:89-94`、`support.py:290-301`）。
- §7 GUI 三状态的数据流（`gui.py:187,189-200,243-250`；`live.py:252-257,275,360`）。

### 推断（有证据链但非直接读数，已在正文标注）
- §2 门 3 的「brain 路径拦截数 = 0」：由 `decisions.jsonl`(闸门前) 与 `offers.jsonl`(闸门后) 的 79 条差集推得。
- §2 门 2 的根因「闸门窗口 5 min / 10 min 而非 24 h」：由 `help.py:21-24,97` 的常量与 8 条重复的间隔实测推出。
- §6.3 风险量级「本机留存约 242 MB 全屏画面史」：由文件数与平均大小估算。
- §6.1 「按此外推全天约 460 张 / 51 MB」：由 10-12 的 154 张线性外推。

### 未知（今天拿不到，已确认无法从现有落盘数据得出）
- **拦截计数**：埋点不存在（`session.suppressed` 仅在内存）。今天**任何数字都是 0 记录**，不代表闸门没工作。
- **`help.check_once()` 路径（10-10 → 10-11 19:17，158 条 `shown`）的拦截次数**：该路径被拦时不留任何痕迹。
- **真实的接受率 / 拒绝率 / 超时率**：三种状态均未落库（§7），且 rejected **没有 UI 入口**。
- **`accepted` 以外的用户意图**：`feedback.jsonl` 仅 9 行且多为「你好」，无法作为接受信号。
- **`>60s` / `>120s` 段的基线值**：基线未测，无法判「改善/恶化」。
- **截图库存的基线**：基线卷宗无此指标，本次为首测。
- **`auto_failed` 是否已修**：36 条与基线**逐数相同**，说明**未修**（`error` 仍为 `returncode:0`）——但「未修」是从计数不变**推断**的；未逐条复核 `error` 字段现文本（基线已复核过）。

---

## 附录 A：完整命令（全部只读；`$py = E:\OpenLookout\.venv312\Scripts\python.exe`）

> 注：含中文的分析一律走**内联 python（stdin 管道）**，不经 shell 内联字符串，避免编码/转义错误。
> 下列命令为可复现的最小形式，实际执行时部分统计合并为一次 python 调用。

| 编号 | 命令 |
|---|---|
| A1 | `python -c "print(sum(1 for l in open(r'E:\OpenLookout\sprite_home\perceive\offers.jsonl',encoding='utf-8') if l.strip()))"` |
| A2 | `python -c "import json,collections;r=[json.loads(l) for l in open(r'...\offers.jsonl',encoding='utf-8') if l.strip()];c=collections.Counter(x['id'] for x in r);print(len(r),len(c),sum(1 for v in c.values() if v>1))"` |
| A3 | `python -c "import json,statistics as s;L=sorted(len(json.loads(l)['text']) for l in open(r'...\offers.jsonl',encoding='utf-8') if l.strip());print(len(L),s.median(L),L[int(.75*(len(L)-1))],L[-1],sum(1 for x in L if x<=60))"` |
| A4 | 同 A3，但先按 `id` 去重（`{r['id']:r for r in rows}`）后取 `values()` |
| A5 | `python -c "import json,collections;print(collections.Counter(json.loads(l).get('action') for l in open(r'...\offers.jsonl',encoding='utf-8') if l.strip()))"` |
| A6 | `python -c "import json,collections;r=[json.loads(l) for l in open(r'...\offers.jsonl',encoding='utf-8') if l.strip()];print(collections.Counter(x.get('kind') for x in r),collections.Counter(x.get('result') for x in r))"` |
| A7 | `python -c "import json,datetime,collections;TZ=datetime.timezone(datetime.timedelta(hours=8));print(collections.Counter(datetime.datetime.fromtimestamp(json.loads(l)['t'],TZ).strftime('%Y-%m-%d') for l in open(r'...\offers.jsonl',encoding='utf-8') if l.strip()))"` |
| A8 | `python -c "print(sum(1 for l in open(r'...\perceive\feedback.jsonl',encoding='utf-8') if l.strip()))"` |
| A9 | `python -c "import json;print([json.loads(l).get('desc') for l in open(r'...\undo.jsonl',encoding='utf-8') if l.strip()])"` |
| A10 | `python -c "import json,collections;r=[json.loads(l) for l in open(r'...\quarantine\restore_map.jsonl',encoding='utf-8') if l.strip()];h=[x for x in r if x['status']=='held'];print(len(r),len(h),sum(x['stored'] for x in h)/1048576)"` |
| A11 | `python -c "import json,os;r=[json.loads(l) for l in open(r'...\restore_map.jsonl',encoding='utf-8') if l.strip()];h=[x for x in r if x['status']=='held'];print(sum(1 for x in h if not os.path.exists(x['orig'])))"` |
| A12 | `python -c "import re,statistics as s;t=open(r'...\perceive\child_brain.log',encoding='utf-8',errors='replace').read();g=[(float(a),int(b),int(c)) for a,b,c in re.findall(r'model segment=\d+ elapsed=([\d.]+)s tokens=(\d+)/(\d+)',t)];e=[x[0] for x in g];print(len(g),s.median(e),max(e),sum(e),sum(1 for x in e if x>30))"` |
| A13 | `python -c "t=open(r'...\child_brain.log',encoding='utf-8',errors='replace').read().splitlines();p=[i for i,l in enumerate(t) if 'Traceback (most recent call last)' in l];print(len(p),p[-1],len(t)-1-p[-1])"` |
| A14 | `python -c "t=open(r'...\child_brain.log',encoding='utf-8',errors='replace').read().splitlines();print(*[sum(1 for l in t if k in l) for k in ('Error','SSLEOF','retry')])"` |
| A15 | 同 A14，但对 `t[-1500:]` 统计；键为 `SSLEOF` / `retrying request once` / `direct model call failed` / `profile requested unavailable tools` / `Traceback` / `WinError 183` / `turn done` |
| A16 | `python -c "import json,collections;r=[json.loads(l) for l in open(r'...\perceive\decisions.jsonl',encoding='utf-8') if l.strip()];print(len(r),collections.Counter(x.get('kind') for x in r),sum(1 for x in r if x.get('actions')))"` |
| A17 | `python -c "import os;p=r'...\companion\GUIDE.md';print(os.path.getsize(p))"` |
| A18 | `python -c "t=open(r'...\perceive\supervisor.log',encoding='utf-8',errors='replace').read().splitlines();print(*[sum(1 for l in t if k in l) for k in ('brain 退出，已自动拉起','重启全部子进程','只热更新窗口','brain 代码变了')])"` |
| A19 | `python -c "import os;r=r'...\companion\runs';n=m=0\nfor d,_,f in os.walk(r):\n for x in f:\n  if x.lower().endswith('.jpg'): n+=1; m+=os.path.getsize(os.path.join(d,x))\nprint(n,m/1048576)"` |
| A20 | `python -c "t=open(r'...\perceive\child_brain.log',encoding='utf-8',errors='replace').read();print(t.count('suppressed'))"` |
| A21 | 进程快照：`Get-Process \| Where-Object { $_.ProcessName -match 'python\|pythonw' } \| Select-Object Id,ProcessName,StartTime` |

### 附录 B：本次采集的原始时刻表

| 时刻 | 动作 |
|---|---|
| 08:06:51 | 目录清单、隔离区物理占用 |
| 08:06:53 | `supervisor.log` mtime |
| 08:07:39 | offers / feedback / undo / restore_map 全量统计 |
| 08:07:47–57 | 日志文件名与格式确认；`child_brain.log` 模型段与错误统计；`supervisor.log` 计数 |
| 08:09:07 | 拦截计数检索（4 个日志 + 2 个账本） |
| 08:09:22 | `decisions.jsonl` 统计与差集推断 |
| 08:09:38 | 去重口径重复/长度；截图库存 |
| 08:10:02 | 末 1500 行窗口统计；关键文件 mtime/大小 |
| 08:10:16 | 进程快照；创建 `_recon/` 目录 |

**采集期间日志增长证据**：`child_brain.log` 08:07:57 = 7,233 行 → 08:10:02 = 7,244 行；
`supervisor.log` mtime 08:06:53 → 08:09:41（新增重启记录）；`decisions.jsonl` mtime 08:09:49。
**引用的任何数字都只在该时刻有效。**
