# 自动执行结果审计：offers.jsonl 的 auto_started / auto_completed / auto_failed 到底是什么

- **审计员**：teammate `outcome-auditor`（共享任务板 `task-4`）
- **性质**：**只读审计**。数据目录 `E:\OpenLookout\sprite_home\perceive` 全程未写；唯一的写入是本文件。
- **审计窗口**：2026-10-12 12:48 – 13:00（本机时钟）。
- **代码快照**：审计期间队友 `signal-fixer` 正在改 `sprite/proactive/timing.py` 与 `live.py`。我引用的行号是下表的快照；注意 `live.py` 已从 10:41:33 的 21742 B 变成 12:55:01 的 23056 B，**行号会漂移，请以「行号 + 引用的原文」一起对照**。
- 读 jsonl 一律 `io.open(..., encoding='utf-8')`。GBK 控制台显示乱码属显示问题，**不是数据损坏**，本审计未将其计为异常。

## 0. 结论先行

1. **36 条 `auto_failed` 不是「36 次自动执行失败」**，也不是任何「40% 失败率」能支撑的数字。它的判定条件是 `live.py` 里一句 `if not final or proc.returncode:`，其中 `final` 是一个**文本**；36/36 条存的 `error` 都字面等于 **`returncode:0`**（进程正常退出）。
2. 36 条里 **18 条在结束前真的改动了这台电脑**（`desktop_trim` 工作集 trim，可逆、不结束进程），并且都通过 companion 气泡如实告诉了用户；另外 18 条**只做了只读工具**、没有任何机器改动、也没有最终结论。
3. 三个状态**都不是可信的完成度指标**：`auto_completed` 里也有 2 条运行其实是 `stopped` 且没有提交结论；另有 **9 条 `auto_started` 压根没有任何终态行**。能站住的一句话是：**「这 36 条记录的是『本轮没有产出最终结论』，而不是『操作失败』；其中一半已经落地了真实、可逆的改动。」**

---

## 1. 谁在哪儿写这三个状态（Q1）

| 状态 | 写入点（快照 seen 2026-10-12 12:55:01） | 触发条件 |
|---|---|---|
| `auto_started` | `sprite/proactive/live.py:315`（`record_offer_result(offer, "auto_started")`，在 `tick()` 里） | `current.json` 的 offer `id` 变了，且该 id 的历史状态**不在** `{auto_started, auto_completed, accepted, undone, undo_requested, ignored, acknowledged, responded, rejected}`（`live.py:312-314`）里 → 记一行后起线程 `run_offer`（`live.py:325`） |
| `auto_completed` | `live.py:102` | `final` 非空**且** `proc.returncode == 0` |
| `auto_failed` | `live.py:100`（主分支） | `final` 为空**或** `returncode != 0` |
| `auto_failed` | `live.py:84` | `subprocess.TimeoutExpired`（`timeout=900` 秒，`live.py:81`） |
| `auto_failed` | `live.py:87` | 其它异常（CLI 起不来），`error=type(exc).__name__` |

`final` 的定义（`live.py:89-95`，连同它自己的注释在 `live.py:90-92`）：

```python
action = _successful_action(result)          # live.py:89
# Persistent VISTA turns end at companion, so ``final`` is often empty.
# A post-action report (or successful mutating tool) is the completion
# signal for an accepted offer.
submitted = str(result.get("final") or "").strip()      # :93
report    = str(result.get("report") or "").strip()     # :94
final     = submitted or ((report or str(action.get("text") or "").strip()) if action else "")
if not final or proc.returncode:                         # :96
    error = f"returncode:{proc.returncode}"              # :97
    ...
    record_offer_result(offer, "auto_failed", error=error, report="这次处理没有完成，电脑没有被改动。")   # :100
record_offer_result(offer, "auto_completed", report=final[:300])                                       # :102
```

- `_successful_action`（`live.py:53-73`）在 `result["action_results"]` 里倒着找第一行 `success` 且 `tool` **不在**只读名单（`desktop_processes, desktop_inventory, desktop_provider_probe, basic_time/calculate/weather/location/search, basic_web_search, basic_web_read`）的行。
- **所以 `final` 为空 ⇔ CLI 的 JSON 输出里既没有 `final`、也没有 `report`（或最近一次 companion 的 say）、也没有「成功的非只读动作」。**
- 落盘函数：`live.py` 的 `record_offer_result(offer, result, **extra)` → 追加一行 `dict(offer, result=result, t_answer=time.time(), **extra)` 到 `offers.jsonl`。
  **行里的 `id / t / text / topic / kind / action / confidence` 全部来自「提议时」的 offer 字典，跟这次运行做了什么无关。**
- `t` = offer 提议时间，`t_answer` = 写这一行的时间。这也是为什么同一逻辑开口会有多行（见 §5）。

**一个必须写清楚的证据：磁盘上的 `live.py` 不是写这些行的那个版本。** 36 条 `auto_failed` 的键精确为 `['action','confidence','error','id','kind','result','t','t_answer','text','topic']`，9 条 `auto_completed` 为同上去掉 `error` —— **两类都已经带上了 `error`（能落盘），却都没有 `report` 键**；而当前 `live.py:100/102` 必然写 `report`。见 §7 第 5 条。

---

## 2. 谁在消费它们（Q2）

| 消费者 | 位置 | 读什么 | 是否在活跃路径 |
|---|---|---|---|
| 聊天历史渲染 | `sprite/proactive/conversation.py:80-105` | 每一行 `result` → 一句气泡文本 | **是**。`live.py:14` `from . import conversation`；`live.py:248` 与 `live.py:348` 用 `conversation.history()` 喂 `ChatDialog` |
| 重复执行门 | `live.py:312-314` | 该 id 的状态是否属于「已答复」集合 | **是**（`tick()`） |
| 机会策略评分 | `vista/benchmarks/desktop/opportunity_policy.py:111,116` | `accepted/auto_completed/auto_failed/undone` | **否（死路）**。`DECISION_ALGORITHM.md:26,32` 明说当前运行链路不再用它决定开口；全仓无 `import opportunity_policy` |
| 聊天事实/规划 | `vista/benchmarks/desktop/chat_facts.py:45`、`chat_planner.py:66,72` | `auto_completed` 等 | **否**，只被各自的 test 导入 |
| 测试 | `sprite/proactive/test_auto_action.py:33,40-46` 等 | `auto_completed` | 测试 |

`conversation.py` 的映射（`conversation.py:89-94`）：`auto_started` → `"我开始处理：{text}"`；`auto_completed` → `report` 或 `"已完成：{text}"`；`auto_failed` → `report` 或 **`"这次处理没有完成，我保留了现场，没有继续改动。"`**；`undone` → `"已撤销刚才的改动。"`。

**关于「有没有人在算失败率」——我 grep 了全仓 `auto_failed`，只出现 3 处（三个写入点）+ `conversation.py:93` 的展示 + `opportunity_policy.py:111` 的死代码。没有任何程序在统计、聚合或计算 `auto_failed` 的比率。** 换句话说：任何「40%」都是人在日志上做除法做出来的，没有工具口径兜底，因而更容易错。

> **更正我自己的一处早前判断**：我一度以为 `sprite/proactive/help.py` 也是活跃消费者 —— **错**。`help.py` 在活跃路径上没有任何导入者（唯一导入它的是 `sprite/proactive/test_timing.py:20`），`live.py` 里也没有 `help.` 引用。它的 `worth_saying` 门不在活跃路径上。

---

## 3. 36 条 `auto_failed` 的真实性质（Q3）

### 3.1 台账的形状（我的测量，`offers.jsonl` 302 行 / 202 个不同 id）

| 维度 | 计数 |
|---|---|
| 行数 / 不同 id | 302 / 202 |
| `kind=offer` | 167 行 / **68** 个 id |
| `kind=companion` | 133 行 / 133 个 id |
| `kind=None` | 2 行 / 1 个 id（同一条被重写） |
| 按 result 的行数 | `shown` 202、`retracted` 1、`auto_started` **54**、`auto_failed` **36**、`auto_completed` **9** |
| 68 个 offer | 54 个执行过（`auto_started`）+ **14 个只 shown、从未执行** |
| 集合关系 | `auto_failed` ⊆ `auto_started`（36⊆54，成立）；`auto_completed` ⊆ `auto_started`（9⊆54，成立）；**9 个 `auto_started` 没有任何终态行** |

### 3.2 36 条的共性（全部逐条核对）

- 全为 `kind=offer`；`error` 字段 **36/36 都是 `returncode:0`**；**均无 `report` 字段**。
- 时间窗口 **2026-10-11 08:22:16.202621 → 08:59:18.442643**，跨度 **37.0 分钟**；35 个启动间隔：中位 **34.7 s**、最大 **533.8 s**；21 个分钟里有 12 个分钟发生了 ≥2 次；最忙的分钟 08:37 有 5 次启动。
- 逐条打开运行归档 `sprite_home/desktop_runs/<时间戳>/artifacts/events.jsonl`：**36/36 都是 `stopped`（reason=`session_closed`）+ `closed status=stopped` + 0 个 `final_response`**。
  对比 7 条「真完成」的 `auto_completed`：`final_response` + `closed status=completed`。
  ⇒ **`auto_failed` 的真实语义是：模型这一段运行在「没有提交最终答案」的状态下结束（例如停在 companion / 决策边界 / 某个工具调用之后），而 `live.py` 用一个 `final` 文本测试把它记成了 `auto_failed`。** 它不是「命令失败」。
- 注意 `error` 里的 `returncode:0` 恰好证明 `proc.returncode` 是 0：`live.py:96` 的 `or` 是左边的 `not final` 为真才进来，进来后 `error` 拼的就是真实的 returncode。

### 3.3 分类与计数（按「是否真的动了电脑」）

**A 类：18 条 —— 至少完成 1 次成功的机器改动，全部是 `desktop_trim`（工作集 trim，可逆，进程不被结束）。**
- 18 条合计：**57 次成功的 `desktop_trim` + 18 次 companion 气泡调用**（`environment:true` 且 `success:true`）；另有 **28 次环境操作被拒/失败**（如 `拒绝给 24660 减内存：进程不存在：process PID not found (pid=24660)`），合计 103 次尝试、75 次成功。
- **18/18 都以一次 companion 调用收尾**，且 say 非空（102–197 字），如实说明「已把闲置内存还给系统 / 进程仍在运行 / 可还原」。
- 取样（20261011-085550）：19 次工具调用、5 次成功 trim、还拒绝了一次无目标 trim，最后写 companion 告诉用户结果 —— **它被记成了「失败」，只因为它没有 `final_response`。**

**B 类：18 条 —— 0 次机器改动，只做了只读工具**（`read_guide / desktop_processes / desktop_inventory / history / read_working / inspect / read_pixels`），也没有最终结论。

**按「提议说的内容」再分，是两簇而不是一簇：**
- 内存压力簇：A 类 18 条 + 部分 B 类（offer 文本是内存告警 → trim 就是正确动作）。
- Codex / CC-Switch 503 供应商配置**建议簇**：B 类大半。这些 offer 本身就是要「看一看、给建议」（`Codex 被 503 打断`、`503 连败换路`、`换供应商`、`点 ▶ 切使用中`、`API 请求地址`…），**根本没有机器动作可做**，因此「有没有改动电脑」对它们不是合适的成功判据。

> **因此不能从这两个标签推出「操作成功/失败」。** 两个标签都在描述「有没有最终结论」，而写入它们的代码在 10-11 之后改过（§5 末、§7 第 5 条）。是否达成用户目标，需要看运行归档，而**B 类 18 条在归档里就是「无事发生 + 无结论」**，其中一部分（纯建议类）今天仍然无法判定「它本该怎么算成功」。

---

## 4. 诚实的失败率口径（Q4）

### 4.1 不能说

- **不能说「自动执行 36/54 = 66.7% 失败」，更不能说「40% 失败」。** 理由逐条：
  1. `auto_failed` 的判据是「`final` 文本为空」，不是「失败」；36/36 的 `error` 字面是 `returncode:0`（正常退出）。
  2. 36 条里 18 条**已经成功改动机器**（可逆 trim）并如实报告了。
  3. 另有 **9 条 `auto_started` 完全没有终态行** —— 它们既没进分子也没进分母。用 54 当分母的比率把这 9 条悄悄丢了（归档显示 8 条 `stopped` 无结论，1 条连运行目录都没有）。
  4. 分母语义是混的：68 个 offer 只有 54 个执行过，另外 14 个「只 shown」也可能被某些口径算成「本该执行」。
  5. 36 条挤在 10-11 的 **37 分钟**内（中位启动间隔 34.7 s，一分钟最多 5 次启动）。这是一次**连续事件/突发**，其上的比率不是稳态失败率。
  6. **「没执行」不等于「失败」**：`auto_started` 的触发只是 `current.json` 的 offer id 变化，没有冷却/配额/去重（`docs/strategy/07-history-gold-hour.md` 已记录此现象）。所谓「执行量」本身就只有 54。
- **「40%」最可能来自哪里**：`36 / (54 + 36) = 40.0%` —— 即把 `auto_started` 行数与 `auto_failed` 行数相加当分母，**把同一个逻辑开口的两行重写算成了两个事件**（每个 `auto_failed` 的 id 之前都已经写过一个 `auto_started` 行）。这正是 `docs/strategy/07-history-gold-hour.md:345-346` 记的「行 vs 逻辑开口」问题。**分母重复计了一个 id，所以这个 40% 从构造上就是错的。**

### 4.2 能说（可复核）

- 「54 次自动执行中，9 次留下终态 `auto_completed`，36 次留下 `auto_failed`，**9 次没有任何终态记录**。」
- 「36 次 `auto_failed` 中，**18 次**在结束前完成了至少一次成功、可逆的机器改动（工作集 trim，合计 57 次成功 trim）并如实告知用户；**18 次**只有只读动作、无机器改动、无最终结论。」
- 「把 `auto_failed` 当『失败』会**同时高估与低估**失败：18 条其实做了事（高估），而 9 条无终态 + 18 条无结论的其实也没帮上忙（低估）。」
- 想给一个数，就必须附明口径，例如「以 `offers.jsonl` 的**行数**为口径，`auto_failed` 占 302 行的 11.9%」——并立刻声明这个数**没有决策含义**（行不是事件）。
- 一个可被工具验证的替代口径：以运行归档的 `closed.status` 为准 → 54 次执行里 **7 次** `completed`（有提交），**47 次** `stopped`（其中 2 次仍被标成 `auto_completed`）。

---

## 5. 两条通道的数据流；`outcomes.jsonl` 是不是唯一出口（Q5）

### 5.1 offer 通道（动作类提议）

```
提议(offer) → current.json
   → live.py tick 读到新 id（live.py:303-306）
   → 判定「未答复」（live.py:312-314）
   → record_offer_result(offer,"auto_started")            → offers.jsonl: auto_started
   → 起子进程 run_offer → python -m vista.benchmarks.desktop.cli --objective <goal>   (live.py:80-81)
        └─ CLI 内部 DesktopRuntime/session 跑一段；结束时 print(json.dumps(session.result()))
   → run_offer 解析 stdout → _last_json (live.py:82)
   → 记 auto_failed (live.py:100) 或 auto_completed (live.py:102)   → offers.jsonl
   → 同时 present 一个气泡 (live.py:101 / live.py:103)
撤回按钮 → "undo_requested"(live.py:276) / "undone"(live.py:284)   → offers.jsonl
```
**结果出口 = `offers.jsonl` 的 `auto_*` 行 + 聊天气泡。**

### 5.2 companion 通道（陪伴/旁白）

```
companion offer → current.json
   → live.py tick 读到 kind=="companion" → 只 present 一句 say 气泡 (live.py:307-309)
     ★ 不调用 run_offer → 永远不会写 auto_*
   → offers.jsonl: shown（由 vista/.../session.py:162 或 sprite/proactive/help.py:189 写）
用户的后续响应 → outcomes.jsonl：responded(live.py:216) / accepted|rejected(live.py:263) /
                  acknowledged(live.py:266) / ignored(live.py:271)
```
**结果出口 = `offers.jsonl` 的 `shown` 行 + `outcomes.jsonl`（用户响应）。**

### 5.3 直接回答两个问题

- **「`outcomes.jsonl` 是不是 companion 通道唯一的结果出口？」→ 不是。** companion 也会写 `offers.jsonl` 的 `shown` 行，而且**`shown` 才是聊天历史读的那份**（`conversation.py`）。`outcomes.jsonl` 只记「用户有没有响应」这一个维度，现状只有 **5 行，全部 `outcome="ignored"`、全部 `kind="companion"`、时间全在 10-12**（10:07:09 / 11:17:15 / 11:28:10 / 11:45:49 / 11:59:33，`latency_s` 180–237）。
- **「offer 通道是不是真的绕开了 `outcomes.jsonl`？」→ 是。** 被自动执行的 offer 不会再走 `on_choice`/`on_expire`（那是用户对气泡的交互），所以永远不会产生 `accepted/rejected/ignored` 行。数据验证：54 个 `auto_started` 的 id 里 **0 个**出现在 `outcomes.jsonl`；`outcomes.jsonl` 里 **0 行** `kind=offer`。⇒ **在 `outcomes.jsonl` 里，被自动执行的 offer 是完全不可见的。**（结论强度：这是「在本数据的窗口内、以 id 为键」的观察。）

### 5.4 一处不干净但影响真实的边角

**`kind` 在两条通道之间不是干净隔离：** auto 运行内部的 companion 调用可以把 `kind` 指定为 `"offer"`（`session.py:158-163` 直接把 `d["kind"]` 拷进 offer），于是它会往自己的输出流里 publish **一条新的 offer 气泡**。实测 18 条 A 类里有 5 条这样做了（`083506 / 083715 / 084248 / 085301 / 085423`）。

这也解释了 §3.1 里「14 个 offer 只 shown 没执行」，以及「看起来同一批 offer 被重写」：**同一逻辑开口在 `offers.jsonl` 里是 1–3 行**（`shown` → `auto_started` → `auto_failed|auto_completed`）。已核对：55 个多行 id 的序列恰好是 `('shown','auto_started','auto_failed')`×36、`('shown','auto_started')`×9、`('shown','auto_started','auto_completed')`×9、`('shown','retracted')`×1。

另外：**行内的 `action` 列（全 `"none"`）来自提议时的 offer 字典，不是这次运行做了什么。任何按 `action` 列做的统计都会算错。**

---

## 6. 一条最高价值的建议信号（Q6）

> **最高价值：把这一行的记录依据从「`final` 文本是否为空」换成运行自己报告的 `answered`，并顺带记下运行目录与成功的机器改动数。**

具体落点（`live.py`，快照 2026-10-12 12:55:01，23056 B，sha256(前16) `39edc5f639bdfdc6`）：

- 在 `live.py:82`（`result = _last_json(proc.stdout) or {}`）之后取出运行自己的终态事实：
  - `answered = bool(result.get("answered"))` —— `session.result()`（`vista/benchmarks/desktop/session.py:242-250`）里现成就有这个字段；
  - `mutations = len([r for r in result.get("action_results", []) if r.get("success") and r.get("tool") not in inspection])`，即 `_successful_action` 的同源数据的中性版本（**计数**，不是「最后一条」）；
  - 运行目录：`run_offer` 现在不传 `--directory`（`live.py:80-81`），所以目录是 CLI 的默认值（`cli.py:21-22`）；要记就顺手显式传一个自己算的 `--directory`，或把它读回来。
- 终态判据改为：
  - `answered` → `auto_completed`（真的提交了结论）；
  - `not answered` → **一个新状态**（如 `auto_stopped` / `auto_no_answer`），代替今天的 `auto_failed`；
  - `returncode != 0` → `auto_errored`（**这才是真的执行错误**）。
- 为什么它比别的选项好：
  1. **`answered` 与运行归档的 `closed.status` 可证明等价**（在当前快照里核过）：`session.submit()` 返回 `finished=True`（`session.py:233-240`）→ `runtime.py:520-521` 置 `COMPLETED` → 归档 `closed status=completed`；不提交则 `close()` → `stop("session_closed")`（`runtime.py:533-547`）→ `closed status=stopped`。改完之后，**账本（`offers.jsonl`）与证据（`desktop_runs/`）按构造一致**，不用再靠猜。
  2. **直接修掉当前 36 条的误标**：它们都是 `answered=False`，改后会变成明确的「没有产出结论」，而不是听起来像执行失败的 `auto_failed`。
  3. **给 `conversation.py:93-94` 一个不再说谎的渲染依据**：今天它对这 36 条用兜底文本「我保留了现场，没有继续改动」，而其中 18 条其实已经改动过（虽然是安全可逆的 trim）。
  4. **给 `live.py:312-314` 的「已答复」集合以真实语义**：今天 `auto_failed` **不在**那个集合里，所以同一个 id 若再次成为 `current.json`，会被重新 `auto_started` 并**再执行一遍**。这是**代码读出的隐患**；我核对了数据：**到目前为止 0 次真实重跑**（54 个 id 里没有第二个 `auto_started`，也没有任何行出现在 `auto_failed` 之后）。修完状态语义后，应把新状态一并放进「已答复」集合。
  5. 比替代方案更小、更可验证：比「让 CLI 永远输出 `final_response`」（改模型/契约，风险大且未必对）小得多；比「在文档里给 40% 加个脚注」（不改事实）有意义得多。它同时服务**账本 / UI / 门禁**三处。
     （`docs/strategy/DEVELOPMENT-PLAN.md:191` 的 M0.2 门禁「新增 `auto_failed` = 0」今天是个自证式指标 —— 因为同一秒的热重载/不产生新动作就能让它归零；改后这个门禁才有意义。）
- **顺带的一行小改**（独立、低风险，请与上面的信号分开评估）：把 `live.py:315` 所在判断的集合里补上 `"auto_failed"`，先消掉重跑隐患。

---

## 7. 我没能证实的（诚实边界）

1. **`operations.jsonl` 与 `decisions.jsonl` 不覆盖 08:22–08:59 这段窗口。** `operations.jsonl` 的 `ts` 从 `2026-10-12T07:17:12+08:00` 起，且它其实是**窗口焦点记录器**（由 `record_win.py` 写，schema 只有 `{ts,type,app,title,dur_s}`，**没有 `tool` 字段**，全是 `focus`/`file_save`/`clipboard`/`file_open`），不是工具执行日志；`decisions.jsonl` 的 `t` 从 10-11 19:17:32 起。**因此我没有独立于 CLI 的第二条事件流来交叉验证那 36 次运行的时序或动作。**
2. **那 36 次运行有没有达成「用户想要的结果」—— 无法从账本断定。** 我只能证明「没有最终结论」与「有没有机器改动」；对纯建议类 offer，连「成功」的定义都还是开放的。
3. `desktop_trim` 那些 trim 后来有没有被撤销 / 被重新占用 —— 数据里没有后续证据。
4. **确切的进程退出码**：我只看到存下来的字符串 `"returncode:0"`，没有独立观测到退出码本身（尽管 `if not final or proc.returncode:` 与 `error` 字面一起强烈指向 0）。
5. **08:22 当时跑的 `live.py` 具体版本无从复原。** `live.py` **不在 git 里**（`git status --porcelain` → `?? src/openlookout/sprite/proactive/`；HEAD `dd697a5` = 2026-10-10 07:53，而整个 `sprite/proactive/` 与 `src/openlookout/vista/` 都是未跟踪目录）。我能证明的只有「写这些行的版本 ≠ 现在磁盘上的版本」：
   - 36 条 `auto_failed` 与 9 条 `auto_completed` **都没有 `report` 键**，而当前 `live.py:100/102` 必然写 `report`；同时 `error` 确实落盘了（说明 kwargs 是能存的）。
   - 行为不连续：10-11 **10:33**（`20261011-103312`）与 **11:51**（`20261011-115102`）两条运行，形状与那 18 条一样（`stopped` + companion say、无提交），却被记成了 `auto_completed`。
   - **可重建的轮廓（这是推断，不是记录）**：早期版本用「只有 `final` 字段」判据 → 36 条无提交的运行落到 `auto_failed`、7 条真提交的落到 `auto_completed`；随后某个版本加入了 `report`/`action` 兜底（就是当前 `live.py:90-95` 连同它那段注释），于是 10:33/11:51 两条同样形状的运行变成了 `auto_completed`。**具体规则无法复原。**
6. **模型「为什么停在这里」（正常边界还是意外中断）、它「打算做什么」—— 数据里没有。别猜。**
7. **`conversation.py` 也可能是后改的**：它的 mtime 是 `2026-10-11 19:28:04`，**晚于** 08:2x 窗口，所以连「用户当时在聊天里看到的那句兜底文本」也无法复原。§2/§6 里我引用的 `conversation.py:94` 文本是**当前版本**的文本，不是当时数据的文本。
8. **同样地，`session.py` 的 mtime 是 `2026-10-12 09:16:48`**，晚于所有被审运行。§6 第 1 条「`answered` ⇔ `closed.status`」的等价性是在**当前快照**里读出来的，不是对当时运行时的复现。
9. **`live.py` 在我审计期间正被 `signal-fixer` 修改**（10:41:33 / 21742 B → 12:55:01 / 23056 B）。我引用的是 12:55:01 快照的行号；若它再变，请以「行号 + 引用原文」一起核对。
10. **「40%」这个数字我无法证实其来源口径**；我只能说没有程序在算它，并指出 `36/(54+36)=40.0%` 这一最可能的构造及其分母错误（§4.1 末）。

---

## 8. 附录

### 8.1 36 条 `auto_failed` 逐条明细

`mut` = 归档里 `environment:true` 且 `success:true` 的事件数（A 类含 1 次 companion）；`envtried` = `environment:true` 的事件数；`last` = 最后一个 `tool_started`。全部 36 条的 `closed` 都是 `stopped`、`final_response` 都是 0。

| # | 启动时间 | 运行目录 | mut/envtried | 收尾工具 | 主题 |
|---|---|---|---|---|---|
| 1 | 10-11 08:22:16 | 20261011-082217 | 3/5 | companion | 内存只剩 0.35GB |
| 2 | 10-11 08:22:33 | 20261011-082233 | 0/0 | desktop_inventory | Codex 被 503 打断 |
| 3 | 10-11 08:24:39 | 20261011-082440 | 0/0 | history | 503 连败换路 |
| 4 | 10-11 08:25:19 | 20261011-082520 | 0/0 | desktop_processes | 换供应商 |
| 5 | 10-11 08:31:16 | 20261011-083117 | 0/0 | read_pixels | |
| 6 | 10-11 08:32:03 | 20261011-083204 | 0/0 | inspect | |
| 7 | 10-11 08:32:54 | 20261011-083254 | 3/3 | companion | |
| 8 | 10-11 08:33:08 | 20261011-083308 | 0/0 | history | |
| 9 | 10-11 08:33:49 | 20261011-083350 | 0/0 | inspect | |
| 10 | 10-11 08:34:04 | 20261011-083404 | 0/0 | inspect | |
| 11 | 10-11 08:34:20 | 20261011-083420 | 5/5 | companion | |
| 12 | 10-11 08:34:33 | 20261011-083434 | 0/0 | inspect | |
| 13 | 10-11 08:35:06 | 20261011-083506 | 4/4 | companion | |
| 14 | 10-11 08:36:13 | 20261011-083615 | 5/11 | companion | Codex 限流收尾 |
| 15 | 10-11 08:36:46 | 20261011-083647 | 0/0 | inspect | |
| 16 | 10-11 08:37:13 | 20261011-083715 | 5/8 | companion | |
| 17 | 10-11 08:37:34 | 20261011-083735 | 0/0 | read_guide | |
| 18 | 10-11 08:37:47 | 20261011-083747 | 5/6 | companion | |
| 19 | 10-11 08:38:09 | 20261011-083811 | 0/0 | desktop_processes | |
| 20 | 10-11 08:38:44 | 20261011-083845 | 6/6 | companion | Codex 503 与内存 |
| 21 | 10-11 08:39:04 | 20261011-083905 | 0/0 | read_pixels | |
| 22 | 10-11 08:39:17 | 20261011-083919 | 5/6 | companion | |
| 23 | 10-11 08:39:55 | 20261011-083956 | 0/0 | desktop_processes | |
| 24 | 10-11 08:41:02 | 20261011-084104 | 0/0 | read_pixels | |
| 25 | 10-11 08:41:41 | 20261011-084142 | 0/0 | read_pixels | |
| 26 | 10-11 08:42:34 | 20261011-084234 | 2/2 | companion | |
| 27 | 10-11 08:42:47 | 20261011-084248 | 6/12 | companion | |
| 28 | 10-11 08:43:40 | 20261011-084341 | 0/0 | read_working | |
| 29 | 10-11 08:43:48 | 20261011-084349 | 6/10 | companion | 内存吃紧 |
| 30 | 10-11 08:44:06 | 20261011-084407 | 2/2 | companion | |
| 31 | 10-11 08:53:00 | 20261011-085301 | 3/3 | companion | |
| 32 | 10-11 08:53:45 | 20261011-085345 | 4/5 | companion | |
| 33 | 10-11 08:54:22 | 20261011-085423 | 4/6 | companion | |
| 34 | 10-11 08:55:49 | 20261011-085550 | 5/6 | companion | 内存清理与 503 收尾 |
| 35 | 10-11 08:56:18 | 20261011-085620 | 2/3 | companion | 内存与 Codex 卡顿 |
| 36 | 10-11 08:59:18 | 20261011-085919 | 0/0 | read_working | |

### 8.2 9 条 `auto_started` 没有终态行

| id / 启动时间 | 运行目录 | 归档形态 |
|---|---|---|
| `1791636238661551900` @10-10 20:43:58 | **无** | 连运行目录都没有 |
| @10-10 21:52:03 | 20261010-215203 | mut 1、stopped、无结论 |
| @10-10 22:03:17 | 20261010-220317 | mut 0、stopped、无结论 |
| @10-11 07:28:34 | 20261011-072834 | mut 0、stopped、无结论 |
| @10-11 07:30:07 | 20261011-073007 | mut 5、stopped、无结论 |
| @10-11 07:30:31 | 20261011-073031 | mut 7、stopped、无结论 |
| @10-11 07:31:17 | 20261011-073117 | mut 0、stopped、无结论 |
| @10-11 14:04:52 | 20261011-140452 | mut 0、stopped、无结论 |
| @10-11 15:22:15 | 20261011-152215 | mut 4、stopped、无结论 |

### 8.3 复现脚本（只读）

```python
# D:\python3.11\python.exe this_file.py
import io, json, os, datetime
D  = r"E:\OpenLookout\sprite_home\perceive"
RD = r"E:\OpenLookout\sprite_home\desktop_runs"
rows = [json.loads(l) for l in io.open(D + r"\offers.jsonl", encoding="utf-8") if l.strip()]
runs = sorted(os.listdir(RD))
rt   = {n: datetime.datetime.strptime(n, "%Y%m%d-%H%M%S").timestamp() for n in runs}

def rdir(t):                      # auto_started.t(run_offer 起子进程的时刻) → 最近 ±5s 的运行目录
    best = None
    for n in runs:
        if abs(rt[n] - t) <= 5 and (best is None or abs(rt[n] - t) < abs(rt[best] - t)):
            best = n
    return best

for r in rows:
    if r.get("result") != "auto_started":
        continue
    d = rdir(float(r["t"]))
    mut = env = fin = 0; closed = None
    if d:
        for l in io.open(os.path.join(RD, d, "artifacts", "events.jsonl"), encoding="utf-8"):
            if not l.strip(): continue
            e = json.loads(l)
            if e.get("event") == "evidence_event" and e.get("environment"):
                env += 1; mut += 1 if e.get("success") else 0
            if e.get("event") == "final_response": fin += 1
            if e.get("event") == "closed": closed = e.get("status")
    print(str(r["id"]), datetime.datetime.fromtimestamp(float(r["t"])), d, "mut=%d/%d" % (mut, env), "final=%d" % fin, closed)
```

### 8.4 本审计引用的文件指纹（读取时间 2026-10-12 12:48–13:00）

| 文件 | 大小 (B) | mtime | sha256（前 16 位） |
|---|---|---|---|
| `src/openlookout/sprite/proactive/live.py` | 23056 | 2026-10-12 12:55:01 | `39edc5f639bdfdc6` |
| `src/openlookout/sprite/proactive/timing.py` | 26802 | 2026-10-12 12:54:40 | `37e68ed2b40909ce` |
| `src/openlookout/sprite/proactive/conversation.py` | 5108 | 2026-10-11 19:28:04 | `e7062186e82692c1` |
| `src/openlookout/vista/benchmarks/desktop/session.py` | 14442 | 2026-10-12 09:16:48 | `dcdc158f92b3ef46` |
| `src/openlookout/vista/benchmarks/desktop/run.py` | 1734 | 2026-10-10 14:32:02 | `aab16da82b0d5cae` |
| `src/openlookout/vista/benchmarks/desktop/cli.py` | 2653 | 2026-10-10 21:01:52 | `c0e49fadc6ad78e2` |
| `sprite_home/perceive/offers.jsonl` | 131871 | 2026-10-12 11:56:31 | `38bb876cf9c53e18` |
| `sprite_home/perceive/outcomes.jsonl` | 1583 | 2026-10-12 11:59:33 | `d28d17a02543fadc` |
| `sprite_home/perceive/operations.jsonl` | 377481 | 2026-10-12 12:57:55 | `0a2633244cb6d424`（实时增长中；审计早期快照 2574 行时约 368227 B） |
| `sprite_home/perceive/decisions.jsonl` | 398674 | 2026-10-12 12:58:01 | `330ee55374a394f6`（实时增长中） |
| `sprite_home/desktop_runs/` | 59 个目录 | 2026-10-11 15:22:16 | — |
| git HEAD | — | 2026-10-10 07:53:01 | `dd697a51a329b8661109955fb7e2026500d8d7d0` |

> 写入本文件的时刻：2026-10-12 13:00 左右。`live.py` / `timing.py` 当时正被 `signal-fixer` 修改，`operations.jsonl` / `decisions.jsonl` 正被运行中的实机（`pythonw -m sprite.proactive.live --gui`）写入，故这些指纹只对上述时刻有效。
