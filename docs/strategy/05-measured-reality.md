# 05 实测现状（Lead 卷宗）

> 本文件不引用任何项目文档的自述数字，全部结论来自**当场读取的运行时数据**。
> 采集时间：2026-10-12 07:19–07:30（Asia/Shanghai）。项目在此刻**正在运行**。

---

## 结论摘要

1. **主线是活的**：`vista/benchmarks/desktop/brain.py` + `sprite/proactive/live.py` 这条线正在实时产生回合（`sprite_home/companion/runs/20261012-072105/` 持续写入）。`lookout/`（v1 报告线）与 `sprite/`（proactive framework 线）**不是当前运行路径**。
2. **产品行为已偏离愿景**：291 条**对话提议**里 **283 条 `action=none`**，只有 1 条 `tidy_desktop`。当前实际交付的是**评论**，不是文档里写的「自己发现、自己判断、直接做、可撤销」。（注：这是**对话**账本；**动作**账本在 `undo.jsonl` / `quarantine/restore_map.jsonl`，见 §3 更正。）
3. **「自动动作 80% 失败」是假警报**：36 条 `auto_failed` 的 `error` 字段全部是 `returncode:0`（成功），且 `action` 全部为 `none`。真实问题是**收尾记账缺陷**。但**不能由此推出「系统没动过用户的机器」**——真实改动确实发生过，见 §3 更正。
4. **反馈闭环可测量地失效**：用户明确要求气泡「60 字上下」，实测 291 条气泡中位 **124 字**、p75 **146 字**，达标率仅 **13.7%**；在用户提出该意见的 10-11 当天，`offer` 类气泡 **147/147 全部超 60 字**，中位 139 字。
5. **成本的真问题不是钱，是延迟**：389 个模型段累计 **7,978 秒（133 分钟）** 纯等待；单段中位 15.0s、**最大 130.1s**，71 段超 30s。一个决策回合可拆到 6 段、耗时 3.5 分钟——期间屏幕已经变了。（redteam 于 07:50 复算为 390 段 / 最大 **201.9s**——**日志仍在增长，此数字在恶化**，引用须带采集时刻。）
6. **GUIDE.md 不是空的**（推翻 STATUS.md 的自述）：3,283 字节，10-12 07:18 写入，内容质量很高。**画像写进去了，但没有治理行为**——这才是病灶。
7. **反馈样本近乎为零**：`feedback.jsonl` 只有 8 行，其中数行只是「你好」。291 条提议对应 8 条反馈，**接受率目前根本无法计算**。
8. 结论：这个项目的瓶颈不是缺功能，而是**缺少一个能对「这句话/这个动作值不值得做」负责的价值闸**。用户已经用原话把这件事说清楚了（见下）。

---

## 1. 运行时拓扑（实测）

采集时刻的在跑进程（`Get-Process`）：

| PID | 进程 | 内存 | 启动时间 | 判定 |
|---|---|---|---|---|
| 24344 | python | 137 MB | 07:21:05 | brain 主进程 |
| 18088 | pythonw | 33 MB | 07:21:05 | GUI 小精灵窗口 |
| 12356 | python | 17 MB | 07:07:07 | 监督进程 |
| 24348 | pythonw | 19 MB | 07:07:06 | GUI 子进程 |
| 12488 / 25288 | python | 24 / 23 MB | 07:17:12 | 记录器子进程 |

热更新痕迹：`perceive/supervisor.log` mtime = 07:21:05，与 brain/GUI 启动时间一致 → **`live.py` 的热更新机制确实在工作**（AGENTS.md 的描述属实）。

实时写入证据：`sprite_home/companion/runs/20261012-072105/` 下 `turn_000001..000007` 的截图帧在 07:21–07:24 之间产生，`perceive/operations.jsonl` 最后写入 07:25:45。

---

## 2. 实际行为：几乎从不行动

`E:\OpenLookout\sprite_home\perceive\offers.jsonl`，291 条，跨度 `2026-10-10 14:43` → `2026-10-12 07:18`（约 40 小时）。

**按 `action` 字段：**

| action | 条数 | 占比 |
|---|---|---|
| `none`（只说话，不做任何事） | **283** | **97.3%** |
| `tidy_desktop` | 1 | 0.3% |
| 空 | 7 | 2.4% |

**按 `kind` × `result` 交叉：**

| kind | shown | auto_started | auto_failed | auto_completed | 合计 |
|---|---|---|---|---|---|
| `offer` | 68 | 54 | 36 | 9 | 167 |
| `companion` | 122 | – | – | – | 122 |
| 空 | 1 | – | – | 1 (retracted) | 2 |

**按天：** 10-10 → 43 条；10-11 → **245 条**；10-12 → 3 条。
10-11 的 245 条意味着清醒时段内**平均每 6 分钟一次开口**。项目自己的硬规则是「宁可安静。误打扰比漏提醒代价高」，这个频率与之直接冲突。

---

## 3. `auto_failed` 是记账缺陷，不是真失败

36 条 `auto_failed` 记录，逐条检查后：

- `action` 字段 **全部为 `none`** → 没有任何桌面动作被触发过。
- `error` 字段 **全部为字符串 `"returncode:0"`** → 子进程退出码 0，即**成功**。

原始记录（节选，`offers.jsonl`）：

```json
{
  "id": "1791678136202620700",
  "text": "提醒一下：可用内存只剩 0.35GB，豆包两个窗口吃掉 2.2GB，是前台程序我不能碰；……",
  "topic": "内存只剩 0.35GB",
  "kind": "offer", "action": "none", "confidence": 0.82,
  "result": "auto_failed",
  "t_answer": 1791678234.5988584,
  "error": "returncode:0"
}
```

对照一条 `auto_completed`：同为 `kind=offer` / `action=none`，结构一致，只是没有 `error` 字段。

**判定**：收尾判定把「退出码 0 但没有机器可读的成功信号」误判为失败。这解释了 `STATUS.md` 里 T12 记录的「做完后必须 submit 收尾，否则用户只看到『没能帮上忙』」——那条修复没有覆盖到自动收尾路径。

**这条必须纠正任何「自动动作失败率 80%」的说法。**

### ⚠️ 更正（2026-10-12 07:50，由 redteam 独立核验后指出）

本节初稿曾写「真正被尝试的自动动作：约 0 条」「没有发生需要用户干预的损害记录」。**这两句是错的**，反证见 `03-risk-redteam.md`：

- **`offers.jsonl` 的 `action` 字段并不记录 `desktop_*` 工具路径**，所以「283/291 为 `action=none`」只能证明**对话提议**没带动作，不能证明系统没动过用户的机器。我把前者当成了后者——**推断越界**。
- 真实改动确实发生过：`sprite_home/undo.jsonl` **7 条**（含一次「整理桌面 **79 个文件**」）；`sprite_home/quarantine/restore_map.jsonl` **277 条**，其中 `held` **272** 条、占用 **201.1 MB**、**240 条的原始路径已不存在**。
- 因此正确结论不是「没动手」，而是「**动了手，但对话账本没有记**」——这比原判断更严重，因为**可观测性缺口同时存在于两个方向**。

保留成立的部分：

- 36 条 `auto_failed` 的确是假失败（`action=none` + `error="returncode:0"`），**「80% 失败率」不成立**。
- 自动动作成功率**无法从 `offers.jsonl` 可靠计算**——不是分母为零，而是**分母记在别处**，要看 `undo.jsonl` 与隔离区账本。
- 真实风险不在「提议失败」，而在**未被评测覆盖的动手路径**：`desktop_end_process` 走 `terminate()`+`kill()`，撤销只能重启进程、**无法恢复未保存内容**，且没有任何对抗用例覆盖它（详见 `03-risk-redteam.md` R2）。

**数据口径教训**：`offers.jsonl` 是**对话**账本，`undo.jsonl` / `restore_map.jsonl` 是**动作**账本。任何「系统做了多少事」的结论必须同时查两本账。

---

## 4. 反馈闭环实测：画像写了，行为没改

### 4.1 GUIDE.md 有内容，而且质量很高

`E:\OpenLookout\sprite_home\companion\GUIDE.md`，3,283 字节，mtime 10-12 07:18:55。

**这推翻了 `STATUS.md` 第 102 行的自述**（「GUIDE.md 用户画像：机制已接好，但模型尚未形成有内容的画像（仍是初始值）」）。它现在有实质内容，包括用户逐条给出的产品要求：

- 「**短：单条气泡尽量 60 字上下，一次一个点**」（2026-10-11 反馈原话：「看起来好长看不懂」）
- 「**汇报要报"帮上了什么"，不要报"你正在干什么"**」（原话：「我没有看到它帮忙的报告，一直都说我现在在干什么」）
- 「**内存/指标类小事要默默解决，不要摆到明面上**」
- 「**不要给自己设次数、间隔、配额**」
- 「**没明确关联就别去检索**」
- 「**先做完再汇报，不要事前询问**」
- 「别做指标触发的条件反射」

### 4.2 但气泡长度反而变长了

对 291 条 `text` 的字符长度统计（中文按字符计）：

| 日期 | kind | n | 中位长度 | 最大 | >60 字条数 |
|---|---|---|---|---|---|
| 10-10 | companion | 21 | 87 | 142 | 16 (76%) |
| 10-10 | offer | 20 | 18 | 189 | 7 (35%) |
| **10-11** | **companion** | 98 | **97** | 196 | **79 (81%)** |
| **10-11** | **offer** | 147 | **139** | 197 | **147 (100%)** |
| 10-12 | companion | 3 | **87** | 87 | 2 (67%) |

全量分位：`n=291, min=13, p25=84, 中位=124, p75=146, max=197`；**≤60 字的仅占 13.7%**。

**关键推论**：用户的长度要求写进了 GUIDE.md，而 10-11 当天 `offer` 类气泡达标率为 **0/147**；在此之后的 10-12 三条最新气泡中位仍是 87 字。**画像内容没有转化为输出策略约束。**

这是本项目最值得优先修的一个问题，因为它是**可测的**、**不需要新功能**、而且直接对应已经发生的用户不满。

### 4.3 开口频率 vs 「宁可安静」

`perceive/decisions.jsonl`（226 条，跨度 10-11 19:17 → 10-12 07:18，约 12 小时）：

| decision | 条数 | 占比 |
|---|---|---|
| `quiet` | 151 | **66.8%** |
| `offer` | 51 | 22.6% |
| `companion` | 24 | 10.6% |

即 **33.2% 的回合在说话**。12 小时内开口 75 次 ≈ **每 10 分钟一次**。其中 `actions` 字段非空的仅 **8 条**。

---

## 5. 成本与延迟实测

`E:\OpenLookout\sprite_home\perceive\child_brain.log`（6,959 行），解析全部 `model segment=N elapsed=Xs tokens=A/B` 记录：

| 指标 | 实测值 |
|---|---|
| 模型段总数 | **389** |
| 输入 token 合计 | **1,821,155** |
| 输出 token 合计 | **278,637** |
| 模型等待累计 | **7,978.3 秒 = 133.0 分钟** |
| 单段输入 token 中位 / 最大 | 3,979 / 16,304 |
| 单段耗时中位 / 最大 | **15.0s / 130.1s** |
| 耗时 >30s 的段数 | **71**（占 18.3%） |
| 「会话已建立」次数 | 294 |

单回合极端样例（同一回合连续 6 段）：

```
segment=1 elapsed=55.0s tokens=5746/1596  tools=['desktop_history']
segment=2 elapsed=36.4s tokens=11645/1952 tools=['basic_search']
segment=3 elapsed=22.2s tokens=6052/1394  tools=['basic_search']
segment=4 elapsed=20.0s tokens=4039/1134  tools=['basic_web_search']
segment=5 elapsed=45.7s tokens=6369/3432  tools=['inspect']
segment=6 elapsed=26.6s tokens=6584/2014  tools=['basic_web_read']
```

**一个决策回合 = 6 段 / 约 46,400 输入 token / 206 秒。** 这正是 `STATUS.md` 反复提到的「单段滞后」的算术来源：模型还在想，屏幕已经换了两屏。

token 花费按 flash 级模型单价折合约为**每天不到 1 元**——**钱不是瓶颈**。瓶颈是**每轮 15 秒起步、最长 130 秒的决策延迟**，以及为了「看得更准」而去调用 `basic_search` / `basic_web_read` 造成的额外 20–46 秒。

---

## 6. 反馈样本量：目前无法计算接受率

`perceive/feedback.jsonl` 共 **8 行**（跨度 10-10 13:45 → 10-11 16:04），内容多为「你好」「你能看到我屏幕截图吗」「这个ai agent叫做claude code，学会了吗」。

对照 291 条提议 → **8 条反馈**。`offers.jsonl` 里也没有可靠记录「用户点了不用」。

**结论：项目文档里「开口时机的质量没有数据」是准确的，而且是当前最严重的可测量性缺口。** 在拿到接受/拒绝信号之前，任何关于「时机变好了」的说法都无法证伪。

---

## 7. 用户已经把战略说出来了

`GUIDE.md` 最后一段（2026-10-11 用户给 Codex 的要求，模型自己标注「对我同样适用」）：

> - **别做指标触发的条件反射**：看见内存高就去 trim、看见文件多就归档，这种"没有战略理解"动作他明确点名为反面例子。
> - 主动性要落在两件事上：①自己去找"哪些场景我真能派上用场"；②派上用场前先有全局排序——这件事此刻值不值得做、为什么要做，比做本身重要。
> - 所以每次动手前先自问一句：这个动作服务的整体目标是什么？答不上来就不要动，宁可 quiet。

**这段话就是本项目的产品验收标准**，而且它比任何现有文档里的描述都更精确。它要求的是一个**价值闸**：能被追问「这个动作服务的整体目标是什么」，答不上来就闭嘴。

当前系统恰恰缺这一层——它是「看到什么就评论什么」，所以产生了 283/291 条 `action=none` 的旁白。

---

## 8. 由实测数据直接推出的优先事项

| 优先级 | 事项 | 为什么（证据） | 验收方式 |
|---|---|---|---|
| P0 | 修自动收尾记账：`returncode:0` 不得计为失败 | 36/36 条 `auto_failed` 均为假失败（§3） | 重跑后该字段为 0 |
| P0 | 给「开口」加价值闸：答不上「服务什么整体目标」就 quiet | 用户原话（§7）；33.2% 回合在说话（§4.3） | 开口率下降且接受率上升 |
| P0 | 把 GUIDE.md 的偏好变成**硬约束**而非提示词 | 60 字要求达标率 13.7%（§4.2） | 气泡长度 P50 ≤60 且可测 |
| P1 | 建可计算的接受率 | 291 提议 / 8 反馈（§6） | 每张气泡可归因到接受/拒绝/无响应 |
| P1 | 砍决策延迟 | 单段中位 15s、最大 130s（§5） | P50 单回合 <10s |
| P2 | 收敛架构线 | `lookout/`、`sprite/` 不在运行路径（§1） | 见 `01-engineering-reality.md` |

---

## 9. 运行可靠性：模型通道是当前最大的不稳定源

`child_brain.log`（6,960 行）中的错误分布：

| 计数 | 内容 |
|---|---|
| **395** | `Traceback (most recent call last)` |
| **882** | 含 `Error` 的行 |
| **200** | `SSLEOF` |
| **102** | `retry` |
| 21 | 含「失败」 |

### 9.1 陈迹 vs 正在发生

Traceback 按日志位置分桶（1000 行一桶）：

```
行     0-  999 :  36
行  1000- 1999 :  77
行  2000- 2999 : 135   ← 峰值
行  3000- 3999 :  65
行  4000- 4999 :  49
行  5000- 5999 :  25
行  6000- 6999 :   7
行  7000- 7999 :   1   ← 最后一条在 6872 行，距日志结尾 88 行
```

结论：**崩溃频率在显著下降，但尚未归零**——最后 88 行内仍有 1 次崩溃。

最后一次 Traceback 是**启动期崩溃**：

```
File "...\vista\benchmarks\desktop\brain.py", line 525, in <module>
  run()
File "...\vista\benchmarks\desktop\brain.py", line 435, in run
  session, runtime, backend, mode = build(cfg, root)
```

即 `build()` 阶段失败 → 监督进程拉起新实例。**「崩溃-重启」循环是这个系统的常态而非异常。**

### 9.2 但真正持续在流血的是模型通道

只看**最后 1,500 行**（即最近一小时的运行）：

| 计数 | 日志原文 |
|---|---|
| **102** | `[brain] model transport interrupted: SSLEOFError; retrying request once` |
| **98** | `[brain] direct model call failed: URLError/SSLEOFError: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol (_ssl.c:1006)` |
| 65 | `[brain] direct model call failed: URLError` |
| 10 | `ValueError: The profile requested unavailable tools: ['basic_web_read', 'basic_web_search']` |
| 1 | `FileExistsError: [WinError 183] 已存在: ...\runs\20261012-071712\artifacts` |

**解读：**

- 最近一小时里，模型调用因 TLS/SSL EOF 失败 **98 次**、重试 **102 次**。这直接解释了 §5 里单段耗时中位 15s、最大 130s 的分布——**延迟主要不是模型慢，是在重试**。
- `ValueError: The profile requested unavailable tools` 是一个**确定性 bug**：`profiles.py` 里声明的工具集与当前 runtime 实际提供的工具集不一致，一旦模型请求 `basic_web_read` / `basic_web_search` 就抛异常。同一日志尾部出现 10 次。**这不是网络问题，是配置/接口不一致**，可修。
- `FileExistsError: [WinError 183] ...\20261012-071712\artifacts` 说明**同一秒内启动了两次回合**，抢占同一个 run 目录 → 竞态。回合目录命名精度不足（秒级）。

### 9.3 历史崩溃的真实成因（值得作为教训记录）

日志中出现的、现已不再重复的异常类型：

| 异常 | 说明 |
|---|---|
| `ImportError: cannot import name 'reading' from 'vista.benchmarks.desktop'` | 对应 `STATUS.md` 第 63 行记录的**事故**：`reading.py` 被误删，且此前**从未入 git**，不可恢复 |
| `NameError: name 'reading' is not defined` / `AttributeError: ... 'reading' has no attribute 'load'` | 同一事故的连锁 |
| **`SyntaxError: unterminated string literal (detected at line 13)`** | **有人把一个语法错误的版本热更新进了活文件**，子进程随即崩溃 |
| `AttributeError: module '...actions' has no attribute 'SPECS'` | 接口在改，调用方没跟上 |
| `TypeError: ChatPlanner.choose() got an unexpected keyword argument 'facts'` | 同上；且 `ChatPlanner` 按 `STATUS.md` 本应已被移除 |
| `NameError: name 'undo' is not defined` | 撤销路径曾被引用但未定义 |

**这四条（丢文件、语法错误热更新、接口漂移、幽灵模块）是同一个根因的四个症状：多个 agent 在无版本控制保护的情况下对运行中的进程热更新。** `SyntaxError` 那次尤其说明问题——热更新机制会忠实地把坏代码加载进来并重启子进程。

---

## 附：本次采集用到的原始命令

```powershell
# 运行中进程
Get-Process | Where-Object { $_.ProcessName -match 'python|pythonw' } |
  Select-Object Id, ProcessName, @{n='MemMB';e={[math]::Round($_.WorkingSet64/1MB,0)}}, StartTime

# 提议统计
Get-Content 'E:\OpenLookout\sprite_home\perceive\offers.jsonl' -Encoding UTF8 |
  ForEach-Object { $_ | ConvertFrom-Json } | Group-Object action, result

# 气泡长度
$objs | Where-Object { $_.text } | ForEach-Object { $_.text.Length } | Sort-Object

# 成本
Get-Content 'E:\OpenLookout\sprite_home\perceive\child_brain.log' -Encoding UTF8 |
  Select-String 'model segment=\d+ elapsed=([\d.]+)s tokens=(\d+)/(\d+)'
```

**数据边界**：以上均为单机、单次采集。`offers.jsonl` 中 10-10 的条目来自更早的 `help.publish()` 通道，与 10-11 起 `brain` 的 `decisions.jsonl` 非同源，比较时需注意口径。
