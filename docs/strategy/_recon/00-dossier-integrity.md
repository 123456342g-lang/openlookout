# 00 · 卷宗完整性核验：丢失三卷的抢救边界 + M0–M4 今日现状

> 任务：`task-1`（Agent Teams 队友 `dossier-keeper`）
> 目标：① 判定 `01-engineering-reality.md` / `02-product-positioning.md` / `04-verification.md` 三卷能否抢救；② 核验 README「四、路线图」M0–M4 共 **18 个门**（0.1–0.4 / 1.1–1.4 / 2.1–2.3 / 3.1–3.4 / 4.1–4.3）**今天**的真实状态；③ 提炼未决问题；④ 判定哪些条目因运行时变化而失效。
> 采集窗口：**2026-10-12 08:22:05 – 08:26:26（Asia/Shanghai）**。采集时项目正在运行（进程 25288 及其 3 个子进程全部存活）。
> 本文件是只读核验报告。执行边界见「附录 B」。

## 0. 标注约定（本文件强制）

| 标注 | 含义 |
|---|---|
| **实测** | 本轮直接运行命令读取文件/进程/账本得到的原始输出，命令与采集时刻随行给出 |
| **推断** | 有证据链与排除性检验，但不是直接读数；已注明推理步骤 |
| **未知** | 今天拿不到，或本轮未复测。**不猜测填充** |
| **引用 01b/02b/05b** | 该事实由队友的复测卷给出，我没有独立复测，明确标注为转引 |

数字类事实一律带采集时刻。项目正在运行，`offers.jsonl` / `decisions.jsonl` / `undo.jsonl` / `quarantine/restore_map.jsonl` 持续增长，**计数类数字会随时刻漂移**（见 §⑤）。

---

# ① 可抢救的结论

## 1.1 结论先行

**三卷正文不可恢复（实测，见 §②）。可抢救的只有"元信息"：这三卷存在过、各自负责什么、以及它们的结论被别人转述的那几句。** 三卷的**实质内容**另有队友用全新测量独立重建为 `01b` / `02b` / `05b`，但那是**新测量，不是原文**，不能当作"找回了卷宗"。

## 1.2 可抢救的内容（逐条，含出处行号）

| # | 可抢救的内容 | 出处 | 标注 |
|---|---|---|---|
| 1 | **三卷的存在与分工**（逐字）：`01-engineering-reality.md` = 架构线盘点、重复副本、可运行性实测；`02-product-positioning.md` = 定位、楔子、竞品、成功指标；`04-verification.md` = 独立核验报告 | `docs/strategy/README.md:9-13`（分卷索引表） | 实测 |
| 2 | **三卷的作者角色**（逐字）：团队为 Lead（现状卷宗+收敛决策+路线图）、**surveyor**（工程事实）、**product**（产品定位）、redteam（风险红队）、**verifier**（独立核验）→ 01=surveyor / 02=product / 04=verifier | `docs/strategy/README.md:4` | 实测 |
| 3 | **01 的一条实质结论被 05 转引**：表内写「收敛架构线 · `lookout/`、`sprite/` 不在运行路径（§1）」 | `docs/strategy/05-measured-reality.md:222` | 实测（转引） |
| 4 | **04 的两条实质结论以"更正"形式残存**：①「真正被尝试的自动动作约 0 条」→ 错（`offers.jsonl` 的 `action` 字段不覆盖 `desktop_*` 路径）；②「没有发生需要用户干预的损害记录」→ 过度断言，正确表述是「动了手，但对话账本没记」；另有数值漂移一处（单段最大耗时 Lead 记 130.1s、复算 201.9s） | `docs/strategy/README.md:204-211`（§九 自我更正记录） | 实测（转引） |
| 5 | **更正的实际载体是 03 而非 04**：`03-risk-redteam.md:32` 的小标题为「关于 Lead 卷宗的交叉核对（含两处更正）」→ 04 的独立产出**没有以任何可核对形式残存**，只剩 README §九 的转述 | `docs/strategy/03-risk-redteam.md:32` + `README.md:206` | 实测（比对） |

> 注意 4 与 5 的**归属矛盾**：README §九 说两处更正「由 redteam 证伪」，而 03 自己把这两条记在「对 Lead 卷宗的交叉核对」名下。因为 04 已丢失，**无法判定 04 当初是否独立复现过同一结论**。这条矛盾本身就是 §④ 的未决问题之一。

## 1.3 三卷的实质内容已被独立重建（替代物，非原文）

| 丢失卷 | 替代物 | 规模 / mtime | 生产者 | 标注 |
|---|---|---|---|---|
| 01-engineering-reality.md | `docs/strategy/_recon/01b-engineering-refresh.md` | 45,961 B / 2026-10-12 08:16:56（612 行） | repo-auditor | 实测（文件元数据） |
| 02-product-positioning.md | `docs/strategy/_recon/02b-market-positioning.md` | 41,476 B / 2026-10-12 08:20:53 | market-scout | 实测（文件元数据） |
| 04-verification.md | 无对应产物 | — | — | 实测 |

命令与时刻：`Get-ChildItem E:\OpenLookout\docs\strategy\_recon -File | Select Name,Length,LastWriteTime`（2026-10-12 08:22:50，复测于 08:25:49）。

`01b` 覆盖：git 覆盖率、重复副本、测试真状态（234 passed/0 failed）、分发前置、密钥卫生、断言台账（`01b-engineering-refresh.md:27-38` 结论摘要 8 条，实测）。
`02b` 覆盖：外部对标（Recall / Copilot Vision / Cluely / Limitless / Astra）、楔子 A vs B 打分、Windows-first 打包实测成本、隐私合规否决项、来源清单（访问时间 2026-10-12）。
**04 没有任何替代物**：verifier 的"独立核验"角色今天无人承担，而其原本要核验的对象（01/02）已两卷皆失 → **04 的缺失是本次事故中最不可弥补的一环**（推断）。

## 1.4 存活两卷的结构（可安全引用）

- `03-risk-redteam.md`（41,438 B / 07:33:54 / 383 行）：结论文摘 + **R1–R9** 九条失败模式，分级为 R1(P0) 信任/打扰+旁白化、R2(P0) 不可逆动作/误删、R3(P1) 隐私全屏逐帧上传零遮挡、R4(P1) 工程可持续性（核心代码不在 git + 热更新打碎）、R5(P1) 分发（AGENTS.md 前提是错的）、R6(P2) 磁盘无上限、R7(P2) 撤销语义错误 + 撤销日志是可执行命令文件、R8(P2) 判断质量（时机无基准 / 画像不管用 / 数字反复报错）、R9(P2) 两份文档描述两个不同产品（标题均实测自 `grep '^#{1,3} '`，2026-10-12 08:22:05）。
- `05-measured-reality.md`（18,324 B / 07:39:44 / 320 行）：结构为 结论摘要 / 1 运行时拓扑 / 2 实际行为 / 3 `auto_failed` 记账缺陷（含 07:50 更正） / 4 反馈闭环 / 5 成本与延迟 / 6 反馈样本量 / 7 用户已把战略说出来 / 8 由实测推出的优先事项 / 9 运行可靠性（模型通道）。

---

# ② 不可恢复的内容

## 2.1 结论

**不可恢复。** 已在 7 个通道搜索，零副本、零残留、零删除记录（全部**实测**，采集窗口 2026-10-12 08:24:34 – 08:25:49，复测 08:24:34 与 08:25:49 两次一致）。

## 2.2 搜索通道与当场输出

统一采集时刻：**2026-10-12 08:24:34（RS_START）– 08:25:49（终检）**。

| # | 通道 | 命令 | 当场输出 | 判定 |
|---|---|---|---|---|
| 1 | git 删除记录 | `git -C E:\OpenLookout log --all --diff-filter=D --name-only \| Select-String 'strategy\|engineering-reality\|product-positioning\|verification'` | 命中 **0** | 无删除记录 |
| 2 | git 对该目录的提交历史 | `git -C E:\OpenLookout log --all --oneline -- docs/strategy` | 提交数 **0** | 从未入库 |
| 3 | 是否被 .gitignore 排除 | `git -C E:\OpenLookout check-ignore -v docs/strategy/README.md` | **空输出** | **未被忽略**——不是"被排除所以丢了"，是**从未 `git add`** |
| 4 | git 已跟踪的 docs 文件 | `git -C E:\OpenLookout ls-files docs` | **0** | 整个 `docs/` 均未入库 |
| 5 | git 不可达对象 | `git -C E:\OpenLookout fsck --unreachable --no-reflogs` | 3 条 unreachable blob | 见 2.3，**已逐一定性，非本卷内容** |
| 6 | 备份目录 `_bak_20261010_081350/` | `Get-ChildItem ... -Recurse -File` + `-Filter *.md` | 140 个文件，其中 **md 仅 4 个**：`STATUS.md`(1,879 B, 10-10 07:51:16)、`TASKS.md`(17,872 B, 10-10 07:51:49)、`sprite\README.md`(19,420 B, 10-09 21:28:50)、`sprite\demo_live\README_DEMO.md`(8,227 B, 10-10 07:51:11) | 无 strategy 文档。且**备份包 mtime 全部早于卷宗写作时间（10-12 07:19–08:00）**，时间上不可能包含（实测+推断） |
| 7 | `.tmp/` | `Get-ChildItem E:\OpenLookout\.tmp -Recurse -File` | 1 个文件 `run_final_demo.py`(2,706 B, 10-10 08:15:05)，**md 0 个** | 无 |
| 8 | `_sync_for_box.zip` | python `zipfile.ZipFile(...).namelist()`（**只读列名，未解压**） | 143 entries；`.md` = `sprite/README.md`、`sprite/demo_live/README_DEMO.md`、`TASKS.md`、`STATUS.md`、`AGENTS.md`；含 `strategy` 的条目 **0** | 是代码同步包，不含 docs/strategy |
| 9 | 全盘文件名搜索（E:\，深度 5） | `Get-ChildItem E:\ -Recurse -File -Depth 5 \| Where Name -in (三卷名)` | **命中 0** | 无 |
| 10 | 全盘文件名搜索（C:\Users\q，深度 5） | 同上 | **命中 0** | 无 |
| 11 | `docs/` 全树清单 | `Get-ChildItem E:\OpenLookout\docs -Recurse -File` | 仅 `ARCHITECTURE.md`、`PROACTIVE_AGENT.md`、`RESEARCH_PROACTIVE_OPENWORLD.md` + `strategy/` 的 3 份存活件 + `_recon/` 的 3 份重建件 | 无隐藏副本 |
| 12 | `.git/lost-found` | `Test-Path E:\OpenLookout\.git\lost-found` | **False** | 无 |

**未执行**：`git fsck --lost-found`（该开关会写入 `.git/lost-found/`，属写操作，被任务边界禁止）；改用只读的 `--unreachable --no-reflogs` + `cat-file` 手工定性。

## 2.3 git 不可达对象的定性（关键排除）

这是唯一"看起来像残留"的通道，已逐个打开**实测**（`git cat-file -p <sha>` 经 python 以 utf-8 解码，2026-10-12 08:25:49）：

| blob sha | 大小 | 实际内容（首行） | 是不是丢失的卷宗 |
|---|---|---|---|
| `4492557f894f3ff2ef279d9cb14cf73e582f2d1f` | 20,282 B | `"""OpenLookout V1 主入口。…  python3 -m lookout.v1 --capture <dir> --out <dir>` | **否**，是 `lookout.v1` 的 Python 源码 |
| `fb7ac1cbbb9f71806d7dee3b280924329b2aeef2` | 15,151 B | `"""行为 × 趋势交叉：在行为 finding 上挂已验证趋势，并按 kits 追加成品。… from . import trends as T` | **否**，`lookout` 线另一 Python 源文件 |
| `5695f011d27b4afdcfc3aef4443c377953c2aaca` | 3,905 B | `"""云端模型调用（OpenAI 兼容接口）。Key 只从 ~/.config/ai-butler/mimo.env 读…` | **否**，同上线的 llm 模块 |

三个全部打上 `KW_HIT` 检查：不含 `engineering-reality` / `product-positioning` / `verification` / `strategy` 任一关键词。→ **git 通道彻底排除**。

## 2.4 为什么会丢（机理，实测）

`docs/strategy/` 从未被 `git add`（通道 2/4），且**不被 `.gitignore` 排除**（通道 3）。README 自述"所有结论都指向带证据的分卷"（`README.md:3`），但这些分卷只存在于工作区。→ 任何一次误删、清理或工作区回滚都会像 `reading.py` 那样**永久消失**（对照 `README.md:104` 记录的同类事故）。**本次不是意外，是同一类事故的第二次发生**（推断）。

## 2.5 只能重建到什么粒度

**不可重建**：三卷的逐条证据、原始命令、原始输出、原始数字与结论措辞。
**已重建**：三卷各自**该覆盖什么**（§1.2 第 1 条）、**谁写的**（§1.2 第 2 条）、以及三卷中的 3 句话被转引的残句（§1.2 第 3–4 条）。
**新增事实**：因 01 已丢，`05-measured-reality.md:222` 引用的那条 01 结论（"`lookout/`、`sprite/` 不在运行路径"）今天**无从对照原文**，只能作为孤证——而它恰好已被本轮实测部分证伪（见 §⑤-1）。

---

# ③ M0–M4 逐条现状表（今天 08:22–08:26 实测）

**18 个门，今日达标 0 个**：❌ 不成立 **13** 个、⚠️ 部分成立 **5** 个、✅ 完全成立 **0** 个。
（M2 另有一条总门"开口率 33%→<10% 且接受率上升"：**因接受率不可计算而不可验收**，未知。）

主采集时刻：**2026-10-12 08:24:04 / 08:24:05**（一次合并只读扫描，见附录 A-1）。辅助采集：08:22:50、08:23:14、08:26:07。

## M0 · 止血（不加任何新功能）

| 门 | 卷宗定义 | 今日实测（命令 → 当场输出） | 判定 | 标注 |
|---|---|---|---|---|
| **0.1** | `git ls-files src/openlookout/vista` 非空 | `git -C E:\OpenLookout ls-files src/openlookout/vista \| Measure -Line` → **0**（总跟踪文件 161）。转引 `01b-engineering-refresh.md:31`：该目录 **116 个 .py / 25,730 行** | ❌ 未做 | 实测 |
| **0.2** | 新增 `auto_failed` = 0 **且原因为真实错误** | 账本：`AUTO_FAILED=36  ERR=[('returncode:0', 36)]  时间窗=[2026-10-11 08:22:16 .. 2026-10-11 08:59:18]  自 10-12 07:00 后新增=0`。**代码**：`sprite/proactive/live.py:96-100` 仍为 `if not final or proc.returncode:` → `error = f"returncode:{proc.returncode}"` → `record_offer_result(offer, "auto_failed", …)`（同文件 `:90` 注释自认 `final` is often empty） | ⚠️ **数值面达标、缺陷未修** | 实测 |
| **0.3** | 新增气泡 `P50 ≤ 60`；重复文本 = 0；**且拦截计数 > 0** | `OFFERS_ROWS=292  P50=121  P90=175  MAX=197  ≤60 字占比=13.7%  最后一条 t=2026-10-12 08:06:16`；24h 内重复 topic：`内存吃紧=4`、`内存只剩 0.35GB=3`、`Codex 被 503 打断=3`、`503 连败换路=3`；全库 `grep '拦截\|blocked_count\|gate_hit'` 于 `src/**/*.py` → **0 命中** | ❌ 三项**全不成立**（P50 超标 2.0 倍；24h 仍重复；拦截计数**埋点根本不存在**） | 实测 |
| **0.4** | 无出处的数字气泡 = 0 | 实现层：`grep 'serves_goal\|expected_value\|numeric_gate\|数字闸\|出处'` 于 `src/**/*.py` → **0 命中**（无数字闸）。样本侧：08:06:16 气泡称「刚实测C盘已回到4.68G」；我 08:26:07 实测 `Get-PSDrive C` → **Free 3.32 GB**；反向核对：`decisions.jsonl` 末行（t=08:23:05）称「08:22 实测 **3.36G**」，与我 08:26:07 的 3.32 GB 基本一致 | ❌ 未实现；「无出处数字=0」**无法计算**（无闸门、无字段）；单条真题伪**未知**（20 分钟自然漂移不可区分） | 实测 + 未知 |

> ⚠️ 0.2 的门有**自欺陷阱**：今天 `新增 auto_failed = 0` 是因为 08:06 之后系统没再发起过行动（292 行里最后一条是 `companion/shown`），**不是缺陷被修**。若以"门已达标"结案，正是 `README.md:186` 想防的失败信号。

## M1 · 可测量（让「有没有变好」可计算）

| 门 | 卷宗定义 | 今日实测 | 判定 | 标注 |
|---|---|---|---|---|
| **1.1** | 能跑出「过去 7 天接受率 = X%」 | `RESULT 取值 = [('shown',192),('auto_started',54),('auto_failed',36),('auto_completed',9),('retracted',1)]`；`accepted`/`ignored_by_timeout` 键存在性 = **False**；`feedback.jsonl` **9 行**（`kind` 取值：None 6 / outcome 2 / correction 1），最新一行 `2026-10-12 07:56:15 "啥意思，c盘100MB，跟我说不用清理吗" kind=correction source=codex_relay` | ❌ 三态未落库 → 292 提议对 9 反馈，**接受率仍不可计算** | 实测 |
| **1.2** | 三指标各有定义、及格线、**计算脚本** | `grep -rn '接受率\|开口率\|达标率\|p95\|P95\|分位\|percentile\|留存\|打扰率' --include=*.py src` → **No matches found** | ❌ 无脚本。定义只存在于 `README.md:113-120` 的文档层 | 实测 |
| **1.3** | 能报出延迟分位（基线：单段中位 15s、最大 201.9s） | 同上 grep → 无 P50/P95 打点脚本。基线数字转引自 `README.md:117` 与 `README.md:211`（后者自述该值**在恶化**） | ❌ 无打点、无脚本 | 实测（缺失）+ 引用（数值） |
| **1.4** | 「系统做了多少事」一次查询可得 | `DEC_ROWS=257`；含 `actions` 的行 = **12**；工具分布 `[('desktop_trim',11),('desktop_reclaim',5)]`；落在对话账本的时间窗 `[2026-10-11 20:01:02 .. 2026-10-12 08:24:03]`；`undo.jsonl` 10 行，键为 `{desc 10, undo_cmd 10, cwd 10, undo_kind 1, moves 1}` | ⚠️ **部分成立**：`desktop_trim`/`desktop_reclaim` 确已写入决策账本（这是相对卷宗"动了手但对话账本没记"的**改善**）；但 `undo.jsonl` 无 `ts`/`task_id`，两账本无关联键 → "一次查询可得"仍不成立 | 实测 |

## M2 · 价值闸（核心）

| 门 | 卷宗定义 | 今日实测 | 判定 | 标注 |
|---|---|---|---|---|
| **2.1** | 每轮决策记录含 `serves_goal`/`evidence`/`expected_value`/`cost`；任一为空→强制 quiet | 字面字段名核验：`serves_goal` **不存在**、`expected_value` **不存在**（`HAS_4FIELD_NAMES=['evidence','cost']` 仅子串命中）。真实形态是 `{goal, evidence, choice, expected_outcome, uncertainty, observed_outcome}`，**仅 21/257 行**有 `decision` 字段（quiet=169 行）。另有 `sprite_home/companion/decision_state.json`（439 B，mtime 08:18:27）：`{"version":1,"total_decisions":1,"stats":{"disk-blocker":{"attempts":1,"successes":0,"failures":1,…},"memory-pressure":{…},"investigate-user-trail":{…},"natural-companion":{…}},"seen_outcomes":["initial:1791764307169095100"]}` | ⚠️ **部分实现**：确有候选打分落库（`policy: {candidate, score, reason, alternatives}`，样例见 `decisions.jsonl` 末行 `score 0.62638`），但①字段名与卷宗不同；②"任一为空→quiet"的强制关系**无法从外部验证** | 实测（结构）+ 推断（强制关系） |
| **2.2** | GUIDE 偏好编译成**机器可校验策略**，偏好违反率可统计且为 0 | 全库无策略模块（`grep` 命中 0）；`P50=121`（长度偏好已被违反且未拦截）→ 违反率不为 0 | ❌ | 实测 |
| **2.3** | 每次否决留下**可审计的理由行** | 有理由结构：`decisions.jsonl` 21 行含 `choice`/`uncertainty`/`observed_outcome`；但那是**开口/动手**的理由，不是"否决用户明确偏好"的专门审计行。`offers.jsonl` 的 `reason` 字段**仅 1 行**非空（值：`提议绕过安全检查，违反规则`） | ⚠️ 部分：可读不可统计 | 实测 + 未知 |
| **M2 总门** | 开口率 33% → <10%，**且**接受率上升 | 接受率不可计算（1.1）；08:06:16 之后 17 分钟无新增提议（样本不足） | **未知／不可验收** | 未知 |

## M3 · 让手接上

| 门 | 卷宗定义 | 今日实测 | 判定 | 标注 |
|---|---|---|---|---|
| **3.1** | 所有会改用户机器的工具都在**同一条**闸门之后 | `actions.py` 静态读码：`_refusal` 定义于 `:298`，调用点 `:596`（`suspend`，定义 `:594`）、`:607`（`end_process`，定义 `:604`）、`:835`；而 `from sprite.risk import Env` 仅在 `:702`（`:698 _real_env` 内）与 `from sprite import risk as R` 在 `:756`（`:748 reclaim` 内）导入 | ❌ 只有 `reclaim` 一条路径接入 `risk.py`；`suspend`/`end_process`/`tidy` 走的是 `_refusal`（前台/自己人/保护名单），**没有**接入 `risk.py` 分类器 + 隔离区 + `eval_all` | 实测（静态读码，未执行任何动作） |
| **3.2** | `eval_all` 陷阱集含 `end_process` 用例，且不变量声明不再矛盾 | `grep 'end_process\|suspend\|tidy'` 于 `sprite/eval_*.py` → 命中 16 处**全部是 suspend**（`eval_engine.py:44` 变异体；`eval_all.py:102/138/140/143/162/163/164` 断言），**end_process 用例 = 0**；`actions.py:604` `def end_process(args)` 仍在，且 `:1067` 仍以 `"desktop_end_process": (end_process, _spec("desktop_end_process", "结束一个明确指定的后台进程。…"))` **暴露在模型可见工具表里** | ❌ | 实测 |
| **3.3** | 端到端「发现→判断→动手→汇报→撤销」有真实会话记录 + 撤销日志，且**不询问** | `undo.jsonl` **10 行**（键 `{desc 10, undo_cmd 10, cwd 10, undo_kind 1, moves 1}`），含 `"整理桌面 79 个文件（只移动）"` 的 `moves` 明细；`quarantine/restore_map.jsonl` **5,466 行** | ⚠️ 部分：真实改动与撤销日志**存在**（实测）；但每行是 `undo_cmd`（shell 字符串）+ `cwd`，且无 `ts`/`task_id`；"不询问"无法从账本判定 | 实测 + 未知 |
| **3.4** | 单一场景**连续 7 天**真实使用，接受率有数 | `offers.jsonl` 最早 `t=2026-10-10 14:43:58` → 至 08:24:05 约 **1 天 18 小时** < 7 天；接受率不可计算 | ❌ 且**今天结构上不可能达标** | 实测 |

## M4 · 收敛与分发

| 门 | 卷宗定义 | 今日实测 | 判定 | 标注 |
|---|---|---|---|---|
| **4.1** | 仓库只有**一条**入口命令 | `Test-Path E:\OpenLookout\src\openlookout\lookout` = **True**（根 `E:\OpenLookout\lookout` = False，卷宗未写明路径，见 §⑤-7）；重复副本仍在（转引 `01b-engineering-refresh.md:34`：`observe/`、`recorder_ext/` 逐字节全同，`sprite/sprite/` 等自嵌套）；运行态同时存在三条入口：`-m sprite.proactive.live`（pid 25288）、`-m vista.benchmarks.desktop.brain`（pid 5464）、`record_win.py`（pid 12488）、`pythonw -m sprite.proactive.live --gui`（pid 6800） | ❌ | 实测 |
| **4.2** | `AGENTS.md` 前置 ≤ 3 步，且与实际代码路径一致 | `AGENTS.md` = **10,828 B**；容器通道仍抛 `TypeError`（8 个必填形参全未传），Windows 上 `brain.build()` 直接返回直连后端（转引 `01b-engineering-refresh.md:37`，含日志+签名 bind+源码行号） | ❌ | 实测（文件规模）+ 引用 01b（功能） |
| **4.3** | 一个没装过 Python 的人 10 分钟内装上并看到一次真实帮助 | `Get-ChildItem E:\OpenLookout -Filter *.spec -Recurse` → **0 个**；无安装包/签名产物 | ❌ 未开始 | 实测 |

## ③ 汇总

| 阶段 | 门数 | ❌ | ⚠️ | ✅ |
|---|---|---|---|---|
| M0 止血 | 4 | 3 | 1 | 0 |
| M1 可测量 | 4 | 3 | 1 | 0 |
| M2 价值闸 | 3 | 1 | 2 | 0 |
| M3 让手接上 | 4 | 3 | 1 | 0 |
| M4 收敛分发 | 3 | 3 | 0 | 0 |
| **合计** | **18** | **13** | **5** | **0** |

---

# ④ 未决问题

## 4.1 README §八 已记录的 4 条（逐条复核今日状态）

| # | 卷宗原文要点（`README.md:197-200`） | 今日状态 | 标注 |
|---|---|---|---|
| 1 | M0.1 排序之争：redteam 认为 P0 是「加闸门」（R1），Lead 坚持「核心代码进 git」在前（因 `reading.py` 永久丢失）；结论「如果只做一件事，先做 0.1」 | **未决且已过期**：0.1 今天仍为 `git ls-files = 0`（实测）。排序之争在事实面前已无意义——**两件事都没做** | 实测 |
| 2 | `lookout/` 是否直接删除：Lead 主张归档而非删除（"完整可用的另一个产品，6,328 行"）；redteam 未表态 | **仍未决**；`lookout/` 线确实存在于 `src/openlookout/lookout/`（实测），但**"6,328 行"未复测**，且其 git 不可达 blob（20,282+15,151+3,905 B）显示该线曾进出过索引（实测） | 未决 |
| 3 | 隐私遮挡的具体形态（R3）：本卷只给"必须做"，未给方案 | **仍未决**（本轮未复测遮挡逻辑，转引 `05b-runtime-refresh.md` §6.3：仍无遮挡） | 未决/引用 |
| 4 | 是否真发生过用户损失：`quarantine` 272 条 `held`、240 条原始路径消失；`desktop_tidy` 移动 79 个桌面文件（含私人文件名）**无用户确认记录** | **仍未决，且规模已恶化**：`restore_map.jsonl` **277 → 5,466 行**（约 20 倍，实测）。79 文件的 `moves` 明细在 `undo.jsonl` 中可查，但**用户是否认可仍无记录** | 实测 |

## 4.2 本轮新发现的未决问题（7 条）

| # | 问题 | 证据 | 为什么必须裁决 |
|---|---|---|---|
| 5 | **"运行路径"这一前提已被证伪，`README.md` §三 的收敛决策是否需要重做？** `README.md:24` 称 `src/openlookout/sprite/`（全项目最大）**不在运行路径上**；本轮实测其**正是**运行路径（见 §⑤-1） | 进程 25288 命令行 + `live.py:16/114/162` 的 `cwd=ROOT`（`ROOT = parents[2] # src/openlookout`）+ 根 `sprite/proactive` 不存在 | §三"一条主线，两个挂件"是**基于"谁在跑"做的取舍**；前提变了，取舍的合法性就变了 |
| 6 | **撤销账本是可执行的命令文件（R7）没有归属任何 milestone。** `undo.jsonl` **10/10 行含 `undo_cmd`**（shell 字符串）+ `cwd`；`sprite/proactive/trigger.py:160` 把 `undo_cmd=offer["undo_cmd"]` 写入 journal，`trigger.py:116` 以 `subprocess.Popen(cmd, shell=True, …)` 执行 | 实测（键统计 + 源码行号） | M3.2 只管 `end_process` 一个工具；R7 这条 P2 在路线图里**无对应门**，等于无人认领 |
| 7 | **两套账本无关联键**：`decisions.jsonl`(257 行) 与 `undo.jsonl`(10 行) 之间没有任何 `ts`/`task_id` 可 join | 实测（`undo.jsonl` 键集合无时间字段） | M1.4「一次查询可得」缺少可 join 的主键，门无法实现 |
| 8 | **`now.json` 与 `current.json` 的时效矛盾**：`now.json` mtime 内容为 `2026-10-10T15:05:55`（第 2 天前的画面），`current.json` 内为 08:22:25 | 实测（两文件内容对读） | 没有一个"何为权威当前状态"的定义，任何外部核验都可能读到过期画面 |
| 9 | **两个"决策"计数口径冲突**：`decision_state.json` 的 `total_decisions = 1`，而 `decisions.jsonl` 有 257 行、`companion/decision_state.json` 的 `seen_outcomes` 只有 1 条 | 实测（对读） | M2 的"每轮决策记录"若按 `total_decisions` 计，M2.1 会被误判为几乎未实现；若按 `decisions.jsonl` 计又混淆了 quiet/offer |
| 10 | **`docs/strategy/` 是否纳入版本控制？** 未入 git 且**未被 .gitignore 排除**（`check-ignore` 空输出、`ls-files docs` = 0） | 实测 | 不裁决 → 本次丢失**必然重演**（M0.1 只要求提交 `vista/`，没覆盖 `docs/`） |
| 11 | **03 与 README 对同一更正的归属矛盾**：`README.md:206` 记为「redteam 证伪」，`03-risk-redteam.md:32` 记为「关于 Lead 卷宗的交叉核对（含两处更正）」；04 已丢 → 无法核对 verifier 当初是否独立复现 | 实测（两处文本对读） | 04 的缺失使"独立核验"这一环节今天**完全无人承担**（verifier 角色空缺） |

---

# ⑤ 已失效条目

判定标准：**卷宗原句在今天的运行时/仓库状态下已不成立，或数字已漂移到不可直接引用**。采集时刻见各行。

| # | 卷宗原句（含行号） | 今日实测 | 失效类型 | 标注 |
|---|---|---|---|---|
| **1** | `README.md:24`：「真正在跑的，是仓库里最小的那条线。主线 `vista/benchmarks/desktop/` 约 5,641 行且在 git 里 0 个文件；而 `src/openlookout/sprite/` 22,152 行——全项目最大——**不在运行路径上**」 | 进程 25288 = `D:\python3.11\python.exe -m sprite.proactive.live`（父 28244），其子进程 5464 = `D:\python3.11\python.exe -m vista.benchmarks.desktop.brain`、6800 = `pythonw -m sprite.proactive.live --gui`、12488 = `record_win.py --out sprite_home/perceive/operations.jsonl`；`live.py:16` 与 `:114` 均为 `ROOT = Path(__file__).resolve().parents[2]  # src/openlookout（-m sprite... 的工作目录）`，`live.py:162` `subprocess.Popen([exe, *CHILDREN[name]], cwd=ROOT, …)`；`Test-Path E:\OpenLookout\sprite` = True 但 `…\sprite\proactive` = **False**，而 `src\openlookout\sprite\proactive` = **True**；排除项：`$env:PYTHONPATH` 为空、`D:\python3.11\Lib\site-packages\*.pth` 无一指向 `E:\OpenLookout`、运行入口无 `sys.path.insert(仓库根)` | **核心前提失效**：`-m sprite.proactive.live` 只能解析到 `src/openlookout/sprite/`；**不在运行路径上的是根目录那份陈旧 `sprite/` 副本**（与 `01b-engineering-refresh.md:33` 一致）。采集 **08:23:14 / 08:24:04 / 08:26:26** | 实测（进程+源码行号+目录存在性+排除通道）；"解析到哪一份"为**推断**，已排除其他通道 |
| **2** | `README.md:9-13` 的分卷索引表 | 三条链接指向的文件均不存在 → **3 个死链**（`01-engineering-reality.md`、`02-product-positioning.md`、`04-verification.md`） | 死链 | 实测 |
| **3** | `README.md:4`：团队含 **verifier（独立核验）**，产出 `04-verification.md` | 无任何产物（`_recon/` 下只有 01b/02b/05b，无 04 对应物） | 角色与产物缺失 | 实测 |
| **4** | `README.md:23`：**291** 条开口；气泡中位 **124** 字 | **292** 条；P50 = **121** 字（P90=175，MAX=197，≤60 字占比 13.7% 不变） | 数字漂移（结论方向不变） | 实测 08:24:05 |
| **5** | `README.md:120`：`feedback.jsonl` 仅 **8 行**、291 提议对 8 反馈 | **9 行**；最新 `2026-10-12 07:56:15 "啥意思，c盘100MB，跟我说不用清理吗" kind=correction source=codex_relay` | 数字漂移 | 实测 08:24:05 |
| **6** | `README.md:200` / `03:357`：`quarantine` **272 条 held**、**240 条原始路径消失**、`restore_map.jsonl` **277 条** | `restore_map.jsonl` = **5,466 行**（≈20 倍） | **规模量级失效** | 实测 08:24:05 |
| **7** | `README.md:208` / `03:356`：`undo.jsonl` **7 条** | **10 条**（含"整理桌面 79 个文件"） | 数字漂移 | 实测 08:24:05 |
| **8** | `README.md:117` 基线「单段中位 15s、最大 **201.9s**」；`README.md:211` 自述「Lead 记 130.1s、复算 201.9s——此数字在恶化」 | 本轮未复测延迟（不重复 runtime-auditor 工作）。**引用时必须带采集时刻**，否则 130.1/201.9 两者都会被误当成现值 | 引用风险（卷宗已自我标注） | **未复测** |
| **9** | `README.md:104`：`vista/` 「**22,684 行**无版本控制」 | 转引 `01b-engineering-refresh.md:31`：**116 个 .py / 25,730 行**；但「git 里 0 个文件」**仍成立**（我 08:24:04 复验 = 0）→ **行数失效、结论有效** | 部分失效 | 实测（0）+ 引用（行数） |
| **10** | `README.md:168`：已本地囤 **2,040 张截图 / 257.3 MB**；`README.md:166`：最近一小时 **98 次 SSLEOF、102 次重试**；`03:369`：supervisor「重启 brain」**156 次** | 本轮**未复测**（由 `05b-runtime-refresh.md` §5.2/§5.3/§6.1 覆盖）。引用需注明"截至 05b 采集时刻" | 未复测（**不得当作失效**） | **未复测** |
| **11** | `05-measured-reality.md:222` 引 `01-engineering-reality.md` 表内写「`lookout/`、`sprite/` 不在运行路径（§1）」 | ①路径写法不准：根 `lookout/` **不存在**，实际在 `src/openlookout/lookout/`（实测）；②「`sprite/` 不在运行路径」已证伪（同 #1）；③原文出处（01）已丢，**该引用今天无从对照** | 三重失效（路径 / 结论 / 出处） | 实测 + 未知（原文不可查） |
| **12** | `README.md:105` 的 M0.2 门「新增 `auto_failed` = 0 且原因为真实错误」**作为"已修复"的证据** | 数值面：自 2026-10-11 08:59:18 起**新增 0**（36 条全部落在 10-11 08:22:16–08:59:18 的 37 分钟窗口内）；代码面：`live.py:96` 缺陷原文未变。**今天达标是因为没再行动，不是因为修好了** | **验收口径失效（自欺陷阱）** | 实测 |

## ⑤ 补充：本轮**未复测**因而**不作失效判定**的条目

- `03` 的 R3 隐私遮挡是否存在（转引 `05b-runtime-refresh.md:395`：仍无遮挡）；
- 截图库存 / SSLEOF / supervisor 重启次数 / `eval_all` 的 `461 traps / 0 wrongful`（该数字见 `03-risk-redteam.md:352`，本轮未重跑 `eval_all`——它会执行沙箱内动作，属运行行为，被任务边界排除）；
- `02b` 的外部对标与打包成本结论（外部世界随时变化，引用须带 02b 的采集时刻）。

---

# 附录 A：本轮全部复现命令（只读，可直接粘贴）

约定：`$py = E:\OpenLookout\.venv312\Scripts\python.exe`

## A-1 合并扫描（主证据，采集 2026-10-12 08:24:04–08:24:05）

```powershell
# 0.1 / 4.1 / 4.3
Write-Host ('0.1 GIT_VISTA_TRACKED=' + (git -C E:\OpenLookout ls-files src/openlookout/vista | Measure-Object).Count)
Write-Host ('0.1 GIT_TOTAL_TRACKED=' + (git -C E:\OpenLookout ls-files | Measure-Object).Count)
Write-Host ('4.1 LOOKOUT_DIR_src=' + (Test-Path 'E:\OpenLookout\src\openlookout\lookout') + ' LOOKOUT_DIR_root=' + (Test-Path 'E:\OpenLookout\lookout'))
Write-Host ('4.3 SPEC_FILES=' + (Get-ChildItem E:\OpenLookout -Filter *.spec -Recurse -ErrorAction SilentlyContinue | Measure-Object).Count + ' AGENTS_MD_BYTES=' + (Get-Item E:\OpenLookout\AGENTS.md).Length)
```

```powershell
# 0.2 / 0.3 / 1.1 / 1.4 / 2.1 / 3.3 账本统计（务必用 python 读 utf-8，Get-Content 会乱码）
$py='E:\OpenLookout\.venv312\Scripts\python.exe'
@'
import json,collections,datetime,os
def f(t): return datetime.datetime.fromtimestamp(t).strftime('%Y-%m-%d %H:%M:%S')
H=r'E:\OpenLookout\sprite_home'
load=lambda p:[json.loads(l) for l in open(os.path.join(H,p),encoding='utf-8') if l.strip()]
o=load(r'perceive\offers.jsonl'); L=sorted(len(r['text']) for r in o if r.get('text'))
q=lambda a,p:a[min(len(a)-1,int(p*(len(a)-1)))]
print('0.3 OFFERS=%d P50=%d P90=%d MAX=%d LE60=%.1f%% LAST=%s'%(len(o),q(L,.5),q(L,.9),L[-1],100*sum(1 for x in L if x<=60)/len(L),f(max(r['t'] for r in o))))
print('0.3 RESULT=%s'%collections.Counter(str(r.get('result')) for r in o).most_common())
print('0.2 AF=%d ERR=%s'%(sum(1 for r in o if r.get('result')=='auto_failed'),collections.Counter(str(r.get('error')) for r in o if r.get('result')=='auto_failed').most_common()))
c=collections.Counter(r.get('topic') for r in o if r.get('t',0)>max(r['t'] for r in o)-86400 and r.get('topic'))
print('0.3 DUP24H=%s'%[x for x in c.most_common(4) if x[1]>1])
d=load(r'perceive\decisions.jsonl'); a=[r for r in d if r.get('actions')]
print('2.1 DEC=%d QUIET=%d DECFIELD=%d'%(len(d),sum(1 for r in d if r.get('kind')=='quiet'),sum(1 for r in d if r.get('decision'))))
print('1.4 WITHACTIONS=%d TOOLS=%s'%(len(a),collections.Counter(x.get('tool') for r in a for x in r['actions']).most_common()))
u=load('undo.jsonl'); k=collections.Counter()
for r in u: k.update(r.keys())
print('3.3 UNDO=%d KEYS=%s'%(len(u),dict(k)))
print('3.3 RESTORE_MAP=%d'%len(load(r'quarantine\restore_map.jsonl')))
fb=load(r'perceive\feedback.jsonl'); print('1.1 FEEDBACK=%d KINDS=%s'%(len(fb),collections.Counter(str(r.get('kind')) for r in fb).most_common()))
'@ | & $py -
```

## A-2 丢失三卷的抢救搜索（采集 2026-10-12 08:24:34–08:25:49）

```powershell
git -C E:\OpenLookout log --all --diff-filter=D --name-only | Select-String 'strategy|engineering-reality|product-positioning|verification'   # 0
git -C E:\OpenLookout log --all --oneline -- docs/strategy                                                                                    # 0
git -C E:\OpenLookout check-ignore -v docs/strategy/README.md                                                                                 # 空 => 未被忽略
git -C E:\OpenLookout ls-files docs                                                                                                          # 0
git -C E:\OpenLookout fsck --unreachable --no-reflogs                                                                                         # 3 blobs（见 §2.3）
foreach($p in @('E:\OpenLookout\_bak_20261010_081350','E:\OpenLookout\.tmp','E:\OpenLookout\_sync_for_box.zip','E:\OpenLookout\.git\lost-found')){ "$p => $(Test-Path $p)" }
Get-ChildItem 'E:\OpenLookout\_bak_20261010_081350' -Recurse -File -Filter *.md | Select Length,LastWriteTime,FullName
Get-ChildItem 'E:\OpenLookout\.tmp' -Recurse -File | Select Length,LastWriteTime,FullName
foreach($root in @('E:\','C:\Users\q')){ (Get-ChildItem $root -Recurse -File -Depth 5 -ErrorAction SilentlyContinue | Where-Object { @('01-engineering-reality.md','02-product-positioning.md','04-verification.md') -contains $_.Name }).Count }
# zip 只读列名（不解压）
@'
import zipfile
n=zipfile.ZipFile(r'E:\OpenLookout\_sync_for_box.zip').namelist()
print(len(n),[x for x in n if x.lower().endswith('.md')],[x for x in n if 'strategy' in x.lower()])
'@ | & E:\OpenLookout\.venv312\Scripts\python.exe -
```

## A-3 运行路径归属（采集 2026-10-12 08:23:14 / 08:26:26）

```powershell
Get-CimInstance Win32_Process -Filter "Name='python.exe' or Name='pythonw.exe'" | Select ProcessId,ParentProcessId,CommandLine | Format-List
Select-String -Path 'E:\OpenLookout\src\openlookout\sprite\proactive\live.py' -Pattern '^ROOT|ROOT\s*=|cwd=ROOT|CHILDREN\s*=' -Encoding utf8
"root sprite/proactive = $(Test-Path 'E:\OpenLookout\sprite\proactive')"
"src  sprite/proactive = $(Test-Path 'E:\OpenLookout\src\openlookout\sprite\proactive')"
$env:PYTHONPATH
Get-ChildItem 'D:\python3.11\Lib\site-packages' -Filter *.pth | ForEach-Object { Select-String -Path $_.FullName -Pattern 'OpenLookout' -Encoding utf8 }
```

## A-4 M0.2 / 3.1 / 3.2 代码面（采集 2026-10-12 08:23:14）

```powershell
Select-String -Path 'E:\OpenLookout\src\openlookout\sprite\proactive\live.py' -Pattern 'returncode|auto_failed|final' -Encoding utf8 | Select -First 12
Select-String -Path 'E:\OpenLookout\src\openlookout\vista\benchmarks\desktop\actions.py' -Pattern 'def end_process|def suspend|def tidy|end_process|_refusal|from sprite' -Encoding utf8
Select-String -Path 'E:\OpenLookout\src\openlookout\sprite\eval_*.py' -Pattern 'end_process|suspend|tidy' -Encoding utf8   # 16 命中，全为 suspend
Select-String -Path 'E:\OpenLookout\src\openlookout\sprite\proactive\trigger.py' -Pattern 'undo_cmd|shell=True|Popen' -Encoding utf8
```

## A-5 指标脚本存在性（采集 2026-10-12 08:22:5x）

```powershell
# 期望命中 0（=> M1.2/M1.3 无脚本、M0.4 无数字闸）
grep -rn '接受率|开口率|达标率|p95|P95|分位|percentile|留存|打扰率' --include=*.py E:\OpenLookout\src
grep -rn 'serves_goal|expected_value|numeric_gate|数字闸|出处' --include=*.py E:\OpenLookout\src
grep -rn '拦截|blocked_count|gate_hit' --include=*.py E:\OpenLookout\src
```

---

# 附录 B：执行边界声明（本报告的可信度前提）

本报告**只做只读采集**。具体：

1. **未杀任何进程**，未重启任何组件；进程表仅为 `Get-CimInstance` 读取（08:23:14）。
2. **未运行** `sprite.proactive.live` / `brain.py` / GUI / `eval_all` / 任何 `desktop_*` 工具。
3. **未写入 `sprite_home/`**（只读取其中的 `.jsonl` / `.json`）。JSON 一律用 python 以 `encoding='utf-8'` 解析，**未用 `Get-Content` 读 JSONL**（避免中文乱码导致数字失真）。
4. **未执行任何 `docker` 命令**。
5. **未删除、移动、重命名任何文件**。唯一写入 = 本文件；唯一目录创建 = `docs/strategy/_recon`（`New-Item -ItemType Directory -Force`，2026-10-12 08:20:53）。
6. **未执行 `git fsck --lost-found`**（该开关会写 `.git/lost-found/`）；改用只读的 `--unreachable --no-reflogs` + `cat-file -p` 手工定性三个 blob。
7. **未解压** `_sync_for_box.zip`，仅用 `zipfile.namelist()` 只读列名。
8. **未 `pip install`、未建 venv**。注意：任务指定的 `E:\OpenLookout\.venv312\Scripts\python.exe` 本身**缺 psutil/pytest**（转引 `01b-engineering-refresh.md:36`），因此它只被用来做**纯 json 统计**，未依赖任何第三方包；运行中的真实解释器是 `D:\python3.11\python.exe`（源码 `live.py:16` 与其一致）。
9. **未依赖压缩摘要**：本报告所有数字均来自 08:22–08:26 的当场输出。凡未复测项（延迟分位、截图库存、SSLEOF、supervisor 重启数、`eval_all` 结果、遮挡逻辑、`lookout` 行数）一律标注 **未复测/引用**，**不以卷宗旧数字充当日实现值**。
10. **写作范围**：本文件路径 `E:\OpenLookout\docs\strategy\_recon\00-dossier-integrity.md` 与队友的 `01b` / `02b` / `05b` 互不重叠（各自独立文件，无写入冲突）。

*报告完成时间：2026-10-12 08:26（Asia/Shanghai）。所有数字的采集时刻已随行标注；项目持续运行，计数类数字会漂移。*
