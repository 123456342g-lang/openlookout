# 开口质量度量（OUTCOME_METRICS）

> 代码：`sprite/proactive/outcome_report.py`（只读、标准库、纯离线）
> 测试：`sprite/proactive/test_outcome_report.py`（25 个用例）
> 一句话：**把「沉默」和「拒绝」分开，任何接受率都必须写明分母。**

本文只说明**口径**——每个数字是怎么算出来的、哪些数字故意不算。工具本身不做任何
写入，也不改任何 live 逻辑。

---

## 1. 为什么要有这个度量

`perceive/outcomes.jsonl` 一行 = 一次开口（offer / companion 气泡）的最终结果，是项目
目前**唯一的真实学习信号**。它的问题是把三类完全不同的东西塞进了同一个 `outcome` 字段：

| 类别 | 取值 | 含义 |
|---|---|---|
| 正面证据 | `accepted`、`responded` | 用户选了第一个选项 / 用户直接打字回话 |
| 负面证据 | `rejected` | 用户明确选了别的 |
| **无证据（沉默）** | `ignored`、`unanswered`、`expired`、`timeout` | 气泡超时消失，用户全程没反应 |

**沉默不是拒绝。** 把 `ignored` 算进分母得到的「接受率」一定是假的。已知实测里就有
开口其实帮上了忙、却因为气泡 180s 超时被记成 `ignored` 的行，例如
「清了 Temp：C 盘 1.96G→3.04G」和「核完 DEVELOPMENT-PLAN 事实2…」。

---

## 2. 口径（写死在 `outcome_report.py:54-67`，**不从 timing 导入**）

```
POSITIVE  = ("accepted", "responded")                          # 正面证据
NEGATIVE  = ("rejected",)                                      # 负面证据
SILENCE   = ("ignored", "unanswered", "expired", "timeout")     # 无证据（沉默）
AMBIGUOUS = ("acknowledged", "undo_requested", "undone")        # 模糊：单列，不入分母
UNKNOWN   = 其余任何字符串                                      # 全部计数并单列
```

为什么词表自持、不 `import timing`：队友会并行改 `timing.py` 的标签（T1 引入
`unanswered`）。本模块自带词表 → **新旧词表都能容忍**：`unanswered` 算沉默，
任何没见过的值进 `unknown` 并列出，绝不静默丢弃。若 timing 拿不到，第 5 节降级为
「校准状态未知」，报告主体照样成立。

几条刻意的判断：

* `acknowledged` 只表示「用户看见了」，不等于愿意 → 归入模糊、**不进分母**。
* `unanswered` 与 `ignored` 同类：都是「没观测到回应」。
* 未知值既不算正面、也不算负面、也不算沉默（否则等于替新标签做决定），只计数并列出。
* **总数守恒**：`sum(classes) == 总行数`，保证没有任何一行被静默丢掉。

---

## 3. 两个分母（本文最重要的部分）

| 指标 | 定义 | 用途 |
|---|---|---|
| **接受率（有证据口径）** | `正面 / (正面 + 负面)` | 唯一可以拿来说事的数字 |
| ⚠️ 误导口径（**不要用**） | `正面 / 全部结果行` | 把沉默算成「没被接受」——本报告专门把它单独列出**只为点名** |

报告里两个数都打印，但误导口径带 `⚠️` 与「无回应不等于拒绝」的说明。
分母为 0 时接受率显示为 `—（分母为 0）`，绝不显示 `0.000`（那读起来像「效果很差」）。

**证据够不够**：`MIN_EVIDENCE = 20`，且只数「正面 + 负面」。低于 20 → 标注
「证据不足」：此时 timing 的实际参数（`benefit_s`、`p*`）仍是**出厂先验**，
不是学出来的，不能当成「系统已经校准好了」。

---

## 4. 分列、趋势与旁证

**按 kind 分列**（`outcome_report.py:163`）——不同开口形态的质量不能混成一个数：

* `companion`：陪伴型汇报；
* `offer_with_options`：`kind=offer` **且**原始 offer 行有非空 `options`（真正的「可选开口」）；
* `offer_without_options` / 缺 kind / 未知 kind → `other`（并打印 `raw_kinds` 分布）。

**按天趋势**（`outcome_report.py:313`）——样本不足就直说不画：

* 少于 `MIN_DAYS = 2` 天有结果，或某天「有证据」少于 `MIN_PER_DAY = 5` → 判定
  **样本不足，不画趋势**，并写明原因；
* 只有两天都有足够证据时，才输出首末两天的接受率与大体方向。

**两类旁证（不并入开口级分母）**：

1. `疑似气泡超时`：不再用统一常量，而是按本行气泡预算判定
   （`latency_s + 5s 容差 ≥ bubble_budget_s`）——offer 行预算 120s
   （`OFFER_ASK_S=60`，gui 展示 ×2），companion 行按文案长度 30~90s
   （30s 阅读基线 + 0.1s/字，上限 90s）。
   这类 `ignored` 说明用户根本来不及回应——它们里可能包含真实帮上忙的汇报。
2. `疑似漏记的 responded`：结果落库后 `LATE_USER_WINDOW_S = 900` 秒内用户打字，
   但结果记成了沉默 → 明显是漏记，不是用户没反应。

`offers.jsonl` 的 `result`（`shown` / `auto_started` / `auto_completed` / …）是**提议侧**
状态，不是用户回应；没有对应 `outcomes` 行的提议 = **还没被观测到结果**，不算沉默。
`feedback.jsonl` 是自由文本、没有 offer 级 join key，只作旁证。

---

## 5. 校准状态（对 `timing.py` 的只读、弱依赖检查）

只读调用 `sprite.proactive.timing.benefit_now()` 与 `stop_threshold(app)`，并且：

* **原样照录** `benefit_now()` 返回的 `why` 文本（不加工、不翻译）；
* 同时打印 `timing.py` 的路径与 **mtime**，便于区分队友并行改动的版本；
* 打印 timing 自己的 `_POSITIVE` / `_NEGATIVE` / `MIN_OUTCOMES`，**点名口径差异**：
  timing 目前把 `ignored` 也算进 negative → 它的「有效率」分母包含沉默，
  正是本报告要指出的误导口径；
* 任一调用抛异常 → 记录异常类型与消息，字段留空，**降级不崩**；
* `import timing` 失败 → `calibration.status = "校准状态未知"`。

---

## 6. 只读纪律

* 只**打开读取** `perceive/` 下的 4 个文件：`outcomes.jsonl`、`offers.jsonl`、
  `feedback.jsonl`、`conversation.jsonl`；任何只读打开失败都降级为空数据，不创建文件。
* 默认输出到 stdout；`--report <path>` 只写你指定的那一个路径，
  **拒绝写进 `perceive/`**（退出码 2），防止误伤实时账本。
* 制服编码：一律 `encoding="utf-8"`。用 PowerShell `Get-Content` / GBK 控制台看
  `perceive/*.jsonl` 会显示成「鏍稿畬」之类的乱码——**那是控制台的问题，不是数据损坏**。

---

## 7. 用法

```bash
# 人看的 markdown（默认打到 stdout）
python -m sprite.proactive.outcome_report --perceive E:\OpenLookout\sprite_home\perceive

# 机器可读 JSON
python -m sprite.proactive.outcome_report --json

# 写到指定文件（不得在 perceive/ 内）
python -m sprite.proactive.outcome_report --report reports\outcome.md

# 指定 app（传给 timing.stop_threshold）
python -m sprite.proactive.outcome_report --app default
```

Python API：`summarize(perceive_dir, app="default", timing_module=None) -> dict`、
`render_markdown(report) -> str`。

---

## 8. 当前真实数据的结论（2026-10-12 实测）

* `outcomes.jsonl` 5 行，**5/5 全部是 `ignored`**，kind 全为 `companion`，
  latency 180.4 / 237.2 / 186.2 / 181.3 / 181.8（**5 行全部 ≥170s，全部疑似气泡超时**）；
* 正面 0、负面 0、沉默 5、模糊 0、未知 0；
* 接受率（有证据口径）= 0/0 = **—（分母为 0）**；误导口径 = 0/5 = 0.000（**点名即可，不可用**）；
* 有证据的开口 0 条 < 20 → **证据不足**；`timing.py` 的 `why` 原话：
  「真实结果行只有 5 条（<20），证据不足，仍用出厂先验 60s——这不是学出来的」；
* 只有 1 天有结果 → **样本不足，不画趋势**；
* `offers.jsonl` 302 行里，带非空 `options` 的 offer 为 **0 行** → `offer_with_options`
  这一桶目前**没有样本**，「可选开口」的质量维度暂时无法度量。

> **结论：不能。** 这套数据里没有任何正面或负面证据，全是沉默；说「开口质量在变好」
> 目前**没有数据支撑**。等到有证据的开口 ≥ 20 条（且跨 ≥ 2 天）再谈趋势。
