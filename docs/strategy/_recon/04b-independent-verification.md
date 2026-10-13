# 04b · 独立核验（第三方复测）

> **核验员**：plan-verifier（独立角色，非 `DEVELOPMENT-PLAN.md` 作者，也非 00/01b/02b/05b 任何一份证词的作者）
> **被核对象**：`E:\OpenLookout\docs\strategy\DEVELOPMENT-PLAN.md`（26,950 B / 300 行 / mtime 2026-10-12 08:30:41）
> **核验时刻窗**：2026-10-12 **08:31:43 – 08:38:30**（每条数据附采集时刻）
> **证据来源**：`_recon/00-dossier-integrity.md`、`01b-engineering-refresh.md`、`02b-market-positioning.md`、`05b-runtime-refresh.md` **仅作对照证词，不作为事实**；本卷所有数字均为本轮独立重测。
> **执行边界（已遵守）**：全程只读。未杀进程、未启停目标系统、未调用任何 `desktop_*` 工具、未跑 docker、未写 `sprite_home/`、未删/移/改名任何文件。唯一写入 = 本文件。

**判定口径**：`【实测】`= 本轮命令输出；`【推断】`= 由实测数据推理；`【未知】`= 未测或无法复现。**未为让方案结论成立而放宽口径**；发现不一致即记录，不为任何一方背书。

---

## 0. 结论摘要

| # | 判定 | 项 |
|---|---|---|
| ✅ | **可采信（精确复现）** | 隔离区 5466/5461/5368.0MB、`undo.jsonl` 10 行 10/10 含 `undo_cmd`、桌面 moves=79、git tracked 161 / `vista`=0 / `docs`=0、`tmp_inv` 未忽略、`auto_failed`=36、气泡 P50=121、达标率 13.7%、`feedback.jsonl` 9 行、SSLEOF 200 / retry 102、崩溃 411 / 热更新 177、延迟最大值 201.9s、全部 20 处代码引用中的 18 处 |
| 🟡 | **漂移（方向与宣称一致）** | 开口率 33.5%→**33.7%**；`runs/` 1827 张/242.4MB→**1897 张/250.9MB**（总 675.2→693.8MB）；延迟 P50 15.9→**16.6**；offers 292→293；decisions 245→**264** |
| 🔴 | **需修正（引用/口径错误）** | ① M3.1「`risk.py` 未接入」**被代码证伪**；② `actions.py:1073` 应为 **1109**；③ `session.py:37/105` 应为 **40 / 132-134**；④ §十 step2 的 `git grep` 命令在文件未 tracked 时**恒零输出** |
| ⚪ | **未复测 / 未知** | 决策延迟「端到端」口径（日志只有 per-segment `elapsed=`）；M3.3/M3.4；撤销可回放率从 0.4% 改为 2.86%（路径法）或 0.49%（内容哈希法） |

**总裁定：方案的载荷性事实（记忆未固化、隔离区膨胀、撤销是雷、无反馈闭环）全部成立且多数数字可精确复现；但有 1 条门判定（M3.1）与代码直接矛盾，2 处行号引用不可解析，1 条自带门命令在今天的仓库状态下失效。建议按 §6 最小改动清单修正后再作为工作单使用。**

---

## 0.5 核验方法（对应任务要求 ①）与结构对照

**方法**：全程只读，不采信 `_recon/` 下任何证词的数字，只把它们当"待证主张"。每条主张都用**自己重写的命令**在**同一时点**重测一次，并记录采集时刻；能精确命中的记 ✅，落在同一量级但数值变化的记 🟡（漂移），无法用任何合理口径复现的记 🔴（需修正）。

**取数方式**：优先 `read` / `Select-String -Path` / `git` / `Get-ChildItem` / `Measure-Object`；结构化账本用 `ConvertFrom-Json` 逐行解析；目的文件（`restore_map.jsonl` 2.4 MB、`offers.jsonl`、`decisions.jsonl`、`undo.jsonl`）**全量读入内存解析，不做抽样**（抽样会让"5466 行"这类总数不可验证）。日志类（`child_brain.log` 500 KB / 7,465 行、`supervisor.log` 1111 行）用 `Select-String -AllMatches` 计数，并**对关键模式做"精确模式 vs 裸子串"对照**，防止口径混淆（见 §2.6 热更新 177 vs 441）。

**时间**：单条数据附时刻；核验窗 2026-10-12 08:31:43–08:38:30（目标系统全程在跑，`child_brain.log` 核验期间 mtime 从 08:32 推进到 08:38，**计数必然继续漂移**）。

**结构对照**：①方法与时间 = §0.5 + 卷首 ｜ ②逐条核验表 = §2 ｜ ③不一致与无法复现清单 = §4 / §5 / §6（§6 为最小改动表） ｜ ④门命令可运行性表 = §3 ｜ ⑤结论三分类（可采信 / 存疑降级 / 需修正）= §0 + §8 ｜ ⑥未核项与限制 = §7。

---

## 1. 方法论警告（先读这条）

本机 `pwsh` 的 `Get-Content` **数组索引**对 `actions.py` 出现 **−2 行系统性偏差**：

```
Get-Content actions.py → Count = 1159
read 工具 / Select-String / 原始字节 LF 数 → 1172 行
```

同一文件、同一时刻（08:34:46），两种取行号方式的映射相差 2 行。**已实测确认 `read` 工具与 `Select-String -Path` 及字节级 LF 计数三者一致（1172），`Get-Content` 数组索引不可信。**

> **后果**：任何用 `$c[NNN]` 方式核验行号的结论都可能有 ±2 偏差。本卷**全部行号均以 `read` 工具 / `Select-String -Path` 为准**。建议后续所有卷宗的「命令 + 时刻」纪律里补一句：**行号引用必须用 `Select-String -Path` 或 `git grep` 产生，不得用数组下标推算。**

---

## 2. 载荷性数字逐项复测

### 2.1 隔离区（事实 2）

| 指标 | 方案宣称 | 本轮实测 | 判定 |
|---|---|---|---|
| `restore_map.jsonl` 记录数 | 5,466 | **5,466**（2,442,405 B） | ✅ |
| 其中 `held` | 5,461 | **5,461**（`restored`=5） | ✅ |
| held 占用 | 5,368.0 MB | **5,368.0 MB**（5,628,721,392 B） | ✅ |
| 原始路径已不存在 | 5,438 | **5,305** | 🟡 见下 |
| 撤销可回放率 | 0.4%（23/5,461） | 路径法 **156/5,461 = 2.86%**；内容哈希法 **27/5,461 = 0.49%** | 🟡 口径不稳 |

```
采集 08:32:01–08:33  路径 E:\OpenLookout\sprite_home\quarantine\restore_map.jsonl
python -c "import json,os;r=[json.loads(l) for l in open(...,encoding='utf-8') if l.strip()];
h=[x for x in r if x['status']=='held'];print(len(r),len(h),sum(x['bytes'] for x in h));
print(sum(1 for x in h if not os.path.exists(x['orig'])))"
```

**「5,438 vs 5,305」的根因（本轮查清，属漂移不属错误）**：方案/05b 的 5,438 是 08:07 时点用**完全相同**命令测得。两次之差 133 条，全部是**被操作系统/应用重新创建**的文件，不是真正恢复：

- 现存 held 原路径 156 条中：**132 条在 `Chrome\User Data`（浏览器缓存）**、**24 条在 `AppData\Local\Temp`**；
- 这 156 条的 mtime **中位数 08:25:54、最大 08:31:29**，全部晚于 held 最后写入 07:58 → **都是新文件**。

**由此得出一条对方案有用的结论（本轮新增）**：指标「隔离区原始路径仍存在的比例」**会被时间自动污染、随时间单调虚高**（08:07 的 23 → 08:35 的 156，2.86% 仍远低于 95% 目标，但已把真实可恢复率高估 5.8 倍）。**该滑轮指标应改为内容哈希口径**：对现存原路径逐个比 SHA256，**实测 SAME=27 / DIFF=120 / ERR=9 → 真实可回放率 0.49%**。

> 结论方向不变（近乎全损），且 27/5,461 与方案宣称的 23/5,461 同量级（差异 4 条 = 时间漂移），**方案的 0.4% 结论可采信；但其定义需替换**。

### 2.2 `undo.jsonl`（事实 3 的载体）

**注意路径**：真实 journal = **`E:\OpenLookout\sprite_home\undo.jsonl`**（`actions.py:23 JOURNAL = HOME / "undo.jsonl"`），**不在 `sprite_home/perceive/` 下**。

| 指标 | 方案宣称 | 本轮实测（08:37:50） | 判定 |
|---|---|---|---|
| 行数 | 10 | **10**（13,669 B，mtime 07:58:22） | ✅ |
| 含可执行 `undo_cmd` | 10/10 | **10/10** | ✅ |
| 桌面 moves | 79 | **79** | ✅ |
| desc 最长 | 23 字 | **23 字**（「清理 4960 个可再生文件（隔离区，可还原）」） | ✅ |
| held 最后写入时刻 | 07:58:18 | mtime **07:58:22** | ✅（±4s） |

**本轮新增证据（支撑「撤销是已装上引信的雷」）**：同目录存在**已被消费的旧 journal** `undo.1791641174.done`（11,485 B，mtime **2026-10-10 22:03:05**）。这正是 `actions.py:681 JOURNAL.rename(...)` 的产物 → **【推断】该撤销路径在真实运行中至少被完整触发过一次**，意味着 07:58 之前的桌面操作已被全量回放过一次。方案只把它写成"可能性"，实测说明它**已经发生过**。

### 2.3 git 覆盖（事实 1 / M0.1）

| 指标 | 方案宣称 | 本轮实测 | 判定 |
|---|---|---|---|
| `git ls-files` 总数 | 161 | **161** | ✅ |
| `src/openlookout/vista` tracked | 0 | **0** | ✅ |
| `docs` tracked | 0 | **0** | ✅ |
| `src/openlookout/sprite/proactive` tracked | （未列） | **0** | ✅ 一致 |
| `src/openlookout/observe` tracked | （未列） | **0** | ✅ 一致 |

### 2.4 `tmp_inv`（S0.4）

| 指标 | 方案宣称 | 本轮实测 | 判定 |
|---|---|---|---|
| 占位 | 6,430 MB | **97 files / 6,430.2 MB** | ✅ |
| `git check-ignore -v tmp_inv` | 期望非空 | **空，exit=1** → 未被忽略 | ✅（门不成立，与方案一致） |

构成：`old_dataset.bin` / `unique_video.bin` 各 ~700 MB 重复出现（合成基准数据）。

### 2.5 反馈闭环（事实 4 / M1.1）

`E:\OpenLookout\sprite_home\perceive\offers.jsonl`（08:38:22）

| 指标 | 方案宣称 | 本轮实测 | 判定 |
|---|---|---|---|
| 提议总数 | 292 | **293** | 🟡 漂移 +1 |
| `feedback.jsonl` | 9 行 | **9 行** | ✅ |
| `auto_failed`（M0.2） | 36 | **36** | ✅ 逐数相同 |
| `result` 分布 | — | shown 193 / retracted 1 / auto_started 54 / auto_failed 36 / auto_completed 9 | 【实测】 |

**「接受率无法计算」✅ 成立**：293 条提议中 `accepted` = **0 条**（三态中的 accepted/dismissed/timeout 从未写入），`feedback.jsonl` 9 行不足以补算。

**「拦截计数落库 0 条」✅ 成立**：`session.py:40 self.suppressed = 0` 是**纯内存**变量（仅 `:132 self.suppressed += 1` 自增），在 `perceive/decisions.jsonl`（264 行）中**不存在任何 `suppressed` 字段**。

### 2.6 北极星与守门指标（§六）

| 指标 | 方案宣称 | 本轮实测 | 判定 |
|---|---|---|---|
| 开口率 `(offer+companion)/decisions` | 33.5% | **89/264 = 33.7%** | 🟡 漂移 +0.2pp |
| 气泡长度 P50 | 121 字 | **121 字**（P75 146 / min 13 / max 197） | ✅ 精确 |
| ≤60 字达标率 | 13.7% | **40/293 = 13.7%** | ✅ 精确 |
| 24h 重复文本 | 8 | **17**（原始重复行） | 🟡 口径不同，见下 |
| 拦截计数 | 0 | **0** | ✅ |
| 撤销可回放率 | 0.4% | 见 §2.1 | 🟡 |
| 决策延迟 max | 201.9s | **201.9s** | ✅ 精确 |
| 决策延迟 P50 | 15.9s | **16.6s** | 🟡 漂移 +0.7s |
| 通道故障 SSLEOF/retry | 200 / 102 | **200 / 102** | ✅ 逐数相同 |
| 崩溃重启 / 热更新 | 411 / 177 | **411 / 177** | ✅ 逐数相同 |
| `runs/` | 1,827 张 / 242.4 MB；总 675.2 MB | **1,897 张 / 250.9 MB；总 693.8 MB** | 🟡 漂移（与"单调增长"一致） |

**测量命令（全部只读，可复制）**：

```powershell
# 通道故障（child_brain.log，500,770 B，mtime 08:38）
Select-String -Path E:\OpenLookout\sprite_home\perceive\child_brain.log -Pattern "SSLEOF" | Measure-Object   # 200
Select-String -Path E:\OpenLookout\sprite_home\perceive\child_brain.log -Pattern "retry"  | Measure-Object   # 102

# 崩溃 / 热更新（supervisor.log，72,737 B，mtime 08:32）
Select-String -Path E:\OpenLookout\sprite_home\perceive\supervisor.log -Pattern "brain 退出，已自动拉起" | Measure-Object  # 411
Select-String -Path E:\OpenLookout\sprite_home\perceive\supervisor.log -Pattern "检测到代码改动，热更新：重启全部子进程" | Measure-Object  # 177

# 决策延迟（per-model-segment）
Select-String -Path E:\OpenLookout\sprite_home\perceive\child_brain.log -Pattern "elapsed[=: ]+([0-9.]+)"
# n=650 → min 3 / P50 16.6 / P95 59.5 / max 201.9
```

**关于「热更新 177」的重要澄清（口径必须写死）**：`supervisor.log` 里含「热更新」子串的行共 **441** 条，方案宣称的 **177 只有在精确匹配「检测到代码改动，热更新：重启全部子进程」时成立**；另有 **264** 条是「其它代码变了：只热更新窗口，brain 的持续视觉上下文保留」（不重启 brain）。**177 正确，但必须附模式串，否则同一日志可数出 441。**

**关于「决策延迟」的口径警告**：`child_brain.log` 只提供 `[brain] model segment=N elapsed=NN.Ns` —— 这是**单个模型分段**耗时，**不是方案 §六 所写「每回合端到端」**。最大值 201.9s 与方案完全一致，说明方案用的是同一批数据；但**指标名与实测口径不符**，应改称「模型分段耗时 P50/P95/max」。**真正的端到端决策延迟：未测，【未知】。**

### 2.7 `runs/` 路径澄清

方案 §六 写「`runs/` 目录」。实测存在**两个** `runs/`：

| 路径 | 实测 | 是否方案的 | 说明 |
|---|---|---|---|
| `sprite_home\companion\runs` | **7,229 files / 693.8 MB**；图片 **1,897 张 / 250.9 MB** | ✅ 是（数字对应） | 与方案 1827 张/242.4MB、总 675.2MB 同口径，**08:07→08:38 增长** |
| `src\openlookout\runs` | 195 files / 1.3 MB；图片 0 | ❌ 不是 | 无关小目录 |

**方案应把路径写全为 `sprite_home/companion/runs/`**，否则 `runs/` 在仓库中出现两次歧义。

**辅助实测**：`sprite_home` 合计 **13,617 files / 6,431.2 MB**；构成 `quarantine` 5,462/5,370.3 MB、`companion` 7,252/693.7 MB、`bin` 1/262.3 MB、`desktop_runs` 587/84.1 MB、`perceive` 252/17.3 MB。
**磁盘**：C: free **3.28 GB**（used 146.03）、D: free 55.35 GB、E: free 90.98 GB。

---

## 3. 门命令实测（§十 与 §七）

§十 的可复制清单逐条执行（**只读命令照跑；`git add`/`git commit` 是写操作，未执行**）：

| # | §十 命令 | 期望 | 实测（08:36–08:37） | 判定 |
|---|---|---|---|---|
| 1 | `git -C $root ls-files -- src/openlookout/vista \| Measure-Object` | > 0 | **0** | ❌ 门不成立（与方案一致） |
| 1 | （前置）`git add ... commit ...` | 执行 | **未执行**（写操作，超出核验边界） | — |
| 2 | `git -C $root grep -n "shell=True" -- .../actions.py` | 命中 | **exit=1、零输出** | 🔴 **门命令失效，见 §4.4** |
| 3 | `git -C $root check-ignore -v tmp_inv` | 非空 | **空、exit=1** | ❌ 门不成立（与方案一致） |
| 5 | 05b 附录 A（21 条，全部只读） | — | **确为 21 条（A1–A21），逐条检查均为只读** | ✅ |

### 3.1 `git grep` 失效的完整实测

```
$ git -C E:\OpenLookout grep -n "shell=True" -- src/openlookout/vista/benchmarks/desktop/actions.py
（无输出）  exit=1

$ git -C E:\OpenLookout grep -n --untracked "shell=True" -- src/openlookout/vista/benchmarks/desktop/actions.py
src/openlookout/vista/benchmarks/desktop/actions.py:674:  subprocess.run(r["undo_cmd"], shell=True, timeout=180)
src/openlookout/vista/benchmarks/desktop/actions.py:676:  subprocess.run(r["undo_cmd"], shell=True, timeout=20)
src/openlookout/vista/benchmarks/desktop/actions.py:678:  subprocess.Popen(r["undo_cmd"], shell=True, cwd=..., creationflags=DETACHED,
exit=0
```

**后果（这是本轮最有实操价值的发现）**：`actions.py` **当前未被 git 跟踪**，而 `git grep` 默认只搜已跟踪文件 → §十 step 2 **在 S0.1 完成前永远零输出**。于是：

- 执行者按清单跑第 2 步会看到「没有任何 `shell=True`」，从而**误判问题不存在**；
- 更严重：S0.2 的**验收判据**「`git grep -n "shell=True"` 在撤销路径无自由字符串」在 S0.1 完成前是**真空满足**（trivially true），一个把 `shell=True` 留在原处的改动也会"通过验收"。

> **修正建议**：step 2 改为 `git -C $root grep -n --untracked "shell=True" -- src/openlookout`；S0.2 的验收判据加上前置「**必须在 S0.1 提交后执行**，且 `git ls-files -- <actions.py>` 非空」。
> **顺带**：这也**反向印证了方案自己 §九 的判断**——S0.1 必须排在 S0.2 之前。

### 3.2 跨仓库 `shell=True` 全景（独立复核）

`grep "shell=True"` 扫 `E:\OpenLookout\src` 全树，**共 5 处命中**：

| 位置 | 性质 |
|---|---|
| `vista/benchmarks/desktop/actions.py:674 / 676 / 678` | 撤销路径自由字符串执行（方案已列） |
| `sprite/proactive/trigger.py:116` | 第二处自由字符串执行（方案已列） |
| `lookout/insight/closed_loop/catalog.py:203` | **仅为生成代码里的字符串字面量**，非真实执行点 |

→ **方案「两处 `shell=True` 执行点」的说法准确，无遗漏、无误报。**

---

## 4. 代码引用抽查（20 处）

**抽查方法**：`read` 工具与 `Select-String -Path` 双确认（见 §1）。**18 处准确，2 处不可解析。**

### 4.1 ✅ 准确（18 处）

| 方案引用 | 实测内容 | 判定 |
|---|---|---|
| `actions.py:674 / 676 / 678` | `subprocess.run/Popen(..., shell=True, ...)` 三连 | ✅ |
| `actions.py:681` | `JOURNAL.rename(JOURNAL.with_suffix(f".{int(time.time())}.done"))` | ✅ |
| `actions.py:639-642` | `rows = [json.loads(l) for l in JOURNAL... ]` → `done=[]` → `failed=[]` → `for r in reversed(rows):`（整本回放） | ✅ 语义精确 |
| `actions.py:812` | `if not advapi.LookupPrivilegeValueW(None, "SeDebugPrivilege", ctypes.byref(luid)):` | ✅ |
| `trigger.py:116` | `subprocess.Popen(cmd, shell=True, cwd=cwd or None, creationflags=DETACHED,` | ✅ |
| `gui.py:187` | `self.hide_job = self.win.after(wait * 1000, lambda: self.hide(expired=True))` | ✅ |
| `gui.py:189` | `def hide(self, expired=False):` | ✅ |
| `gui.py:193-200` / `:198` | `_buttons()`；`:198` = `if m.get("action_id"): return [("撤销", ...), ("好", ...)] + det` → **确无「不用」按钮** | ✅ |
| `live.py:16` | `ROOT = Path(__file__).resolve().parents[2]  # src/openlookout` | ✅ |
| `live.py:114` | `ROOT = Path(__file__).resolve().parents[2]  # src/openlookout（-m sprite... 的工作目录）` | ✅ |
| `live.py:162` | `return subprocess.Popen([exe, *CHILDREN[name]], cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"),` | ✅ |
| `live.py:252-257` | `def on_choice(i, ok=False) -> None:` 体仅 `w.hide(expired=False)` → **accepted 被丢弃** | ✅ |
| `live.py:275` | `w = SpriteWindow(root, DIR, on_choice, on_undo, lambda: None)` → **timeout 被丢弃** | ✅ |
| `live.py:360` | `def record_offer_result(offer: dict, result: str, **extra) -> None:`（`:362` 写入 `offers.jsonl`） | ✅ |
| `help.py:21-24` | `TICK_S, CHECK_EVERY_S = 20, 120` / `MIN_CONF = 0.7` / `OFFER_COOLDOWN_S = 300` / `COMPANION_COOLDOWN_S = 600` → 5/10 分钟，`86400/300 = 288` | ✅ 「松 288 倍」成立 |
| `help.py:111` / `:109` | `if r.get("result") in {"accepted","auto_started","auto_completed","undone"}:` / `if r.get("result") == "dismissed" and now - r.get("t", 0) < DISMISS_S:` → **读取端确已就位** | ✅ |
| `GUIDE.md:15` | `E:\OpenLookout\sprite_home\companion\GUIDE.md:15` = 「**先做完再汇报，不要事前询问**（2026-10-10 明确反馈）」 | ✅ |

**顺带复核**：`live.py:259-262 on_undo` 确实写入 `record_offer_result(offer, "undo_requested")`，`:270` 写 `"undone"` → 方案「缺的只是写入端三个调用点」表述准确（实际是 `accepted` / `timeout` / `dismissed` 三处）。

### 4.2 🔴 `actions.py:1073` —— 引用错误

方案 §事实3 第 2 行写：**工具描述 `actions.py:1073`** vs 实现 `:639-642` + `:681`。

**实测**：

| 行 | 实际内容 |
|---|---|
| `actions.py:1073` | `"label": {"type": "string", "minLength": 1, "maxLength": 100},` —— 属于 `desktop_capture_evidence`（`:1068` 起）的**参数 schema**，与撤销无关 |
| `actions.py:1109` | `"desktop_undo": (undo, _spec("desktop_undo", "还原本次任务中所有已记录的操作（把桌面归类的文件放回原处、把隔离区文件恢复、恢复挂起的进程）。", ...))` ← **这才是撤销工具描述** |

**结论**：**行号错，但结论对，且实测证据比方案写的更强** ——

- 描述原文承诺「还原**本次任务**中所有已记录的操作」；
- 实现在 `:637-681` 对 `JOURNAL` **全量 `reversed(rows)` 回放**，并在 `:681` 把**整本 journal** 改名为 `.done`。

即：**"点一次撤销 = 回放全部历史 + 永久销毁整本 journal"**，不只是"回放整个 journal"，而是**回放后连账本都没了**。这与 §2.2 实测的 `undo.1791641174.done` 相互印证。**建议把引用改成 `actions.py:1109`（描述）vs `actions.py:637-681`（实现）。**

### 4.3 🔴 `session.py:37/105` —— 引用错误

方案 §事实4 末行写：拦截计数「只有内存变量（`session.py:37/105`）」。

**实测**（文件 = `src/openlookout/vista/benchmarks/desktop/session.py`，12,415 B，mtime 08:31:25）：

| 方案引用 | 实际内容 | 正确位置 |
|---|---|---|
| `:37` | `ToolBinding(actions.PLAN_SPEC, self._plan),` | `:40 self.suppressed = 0   # 因「刚说过/他拒绝过」被压掉的次数（时机质量的数据）` |
| `:105` | companion `next_step` dict 的收尾 `}` | `:132 self.suppressed += 1`、`:134 boundary="decision_complete", event_text="decision:suppressed"` |

**结论**：**引用不可解析，但结论对**——`suppressed` 确实是纯内存变量，`perceive/decisions.jsonl` 中 0 条落库（§2.5 已验证）。建议引用改为 `session.py:40 / 132-134`。

### 4.4 关于这 2 处错误：漂移还是笔误？

**必须记录的事实**：被误引的 `actions.py` 与 `session.py`，**mtime 均为 `2026-10-12 08:31:25`**，晚于方案写作时刻 `08:30:41` —— 即**核验时有其他 agent 正在实时改这两个文件**。

但是：**不能用"整体行号漂移"解释** —— 同一份 `actions.py` 里方案的其他 4 处引用（`674/676/678`、`681`、`812`）在 08:36 仍然**完全准确**；若发生过足以把 1073 推到 1109 的 +36 行插入，这些引用必然同时失效。

→ **【推断】这 2 处更可能是写作时的引用错误，而非漂移。但因无法回溯 08:30:41 的文件快照，不能 100% 排除"部分区域插入"，故记为「需人工复核的引用错误」而非「笔误」。** 无论归因如何，**处理动作相同：改引用**。

---

## 5. 🟡 「24h 重复文本 = 8」的口径分歧

| 口径 | 值 |
|---|---|
| 方案 §六 | **8** |
| 05b 的定义 | 「**去重后**仍为 8 条真重复」（先按 id 去重，再按文本指纹） |
| 本轮原始口径 | 24h 内 `offers.jsonl` 187 条、unique topic 55、**重复行 17** |
| 全时段重复 | 108 条；最高重复文本（13 字）出现 **9 次**；Top5 主题各重复 3 次 |

**判定**：**8 不是错，但它是一个"去重后的指纹重复"口径，方案 §六 表头却写成「去重后重复行数」而未给出指纹算法** → 执行者用最直觉的写法（统计重复行）会得到 17，从而**无法复现方案的 8**。

**建议**：把定义写全 —— 「同一 24h 窗口内，按 `offer.id` 去重后，再对 `text` 做指纹（`help.py:_fingerprint`）分组，组内条数 >1 的**冗余条数**之和」。

---

## 6. 需修正清单（最小改动，可直接照改）

| # | 位置 | 现状 | 建议改为 | 依据 |
|---|---|---|---|---|
| 1 | §三 M3.1 行（`:98`） | `sprite/risk.py` 接入主线 `actions.py` → **❌ 未接入** | **⚠️ 已接入（至少 reclaim/trim 路径）**，或重写口径为"决策层未在选动作前调用 risk" | `actions.py:702 from sprite.risk import Env`（`_real_env()`，698-710，真实机器目录+`provenance_win`，docstring 称"和通用引擎同一份口径"）；`actions.py:756 from sprite import risk as R`（`reclaim()`，docstring `:751`"risk 判 safe 才动；medium/high 一律不碰"）；`src/openlookout/sprite/risk.py` 存在（8,487 B，2026-10-09 21:28:50） |
| 2 | §事实3 `:65` | 工具描述 `actions.py:1073` | **`actions.py:1109`**；实现写 `actions.py:637-681` | §4.2 |
| 3 | §事实4 `:81` | 内存变量（`session.py:37/105`） | **`session.py:40 / 132-134`** | §4.3 |
| 4 | §十 step 2（`:253`） | `git grep -n "shell=True" -- .../actions.py` | 加 `--untracked`，或注明**须在 S0.1 提交后执行** | §3.1（当前 exit=1 零输出） |
| 5 | §七 S0.2 验收判据（`:171`） | `git grep -n "shell=True"` 在撤销路径无自由字符串 | 前置条件「`git ls-files -- <actions.py>` 非空」+ `--untracked` | §3.1（否则真空满足） |
| 6 | §六 撤销可回放率（`:154`） | `隔离区原始路径仍存在的比例` | 改为「**原路径存在且 SHA256 与入库记录一致的比例**」 | §2.1（路径法随时间虚高 5.8 倍：23→156） |
| 7 | §六 决策延迟（`:155`） | 「每回合端到端」 | 「**模型分段耗时**（`child_brain.log` `elapsed=`）」 | §2.6（日志无端到端字段） |
| 8 | §六 重复文本（`:151`） | 「去重后重复行数」 | 补全指纹算法 | §5 |
| 9 | §六 `runs/`（`:158`） | `runs/` 目录 | **`sprite_home/companion/runs/`** | §2.7（仓库内有两个 `runs/`） |
| 10 | §六 崩溃/热更新（`:157`） | 热更新 177 次 | 附模式串「检测到代码改动，热更新：重启全部子进程」 | §2.6（裸子串 441） |
| 11 | 全卷 | 行号引用 | 声明「行号由 `Select-String -Path`/`git grep` 产生」 | §1（`Get-Content` 索引 −2 偏差） |

---

## 7. 未复测 / 未知（明确标注，不以证词代替）

| 项 | 状态 |
|---|---|
| 决策延迟「端到端」 | **【未知】** 日志只有 per-model-segment `elapsed=`，无每回合总时长字段 |
| M3.3 端到端「发现→动手→汇报→撤销」 | **【未知】** 无对抗用例可跑；且属写操作，超出只读核验边界 |
| M3.4 单场景连续 7 天 | **【未知】** 时间未到 |
| 「撤销可回放率 ≥ 95%」目标 | **【未知】** 无实现，无可测对象 |
| §十 step 1 的 `git add/commit` | **未执行**（写操作，违反只读边界）；只核验其**前置条件**（`vista` tracked = 0，尚未满足） |
| 08:30:41 时刻的文件快照 | **【未知】** 无法回溯，故 §4.4 的归因只到「推断」 |
| 长时间窗日志（>08:38 之后） | 目标系统**正在运行并持续写入**（`child_brain.log` mtime 08:38，5 分钟内增长），所有计数**必然继续漂移** |

---

## 8. 总体判定

1. **方案的四条载荷性事实全部成立**：核心代码 `vista`/`docs` tracked = 0（记忆不可回滚）；隔离区 5,461 文件 / 5,368 MB 且真实可回放率 0.49%；撤销路径两处 `shell=True` + 全量回放 + journal 一次性销毁（**且实测已被触发过一次**）；三态反馈 0 条落库 → 接受率无法计算。
2. **方案的绝大多数数字可精确复现**，包括最关键的 `SSLEOF 200 / retry 102`、`崩溃 411 / 热更新 177`、`延迟 max 201.9s`、`气泡 P50 121`、`达标率 13.7%`、`隔离区 5466/5461/5368.0MB` —— 这些**逐数相同或完全一致**，说明作者不是估的。
3. **发现 1 条与代码直接矛盾的门判定（M3.1）**：`sprite/risk.py` **已被 `actions.py` 导入并用于 `_real_env`/`reclaim`**，标「未接入」不成立。这是本轮最需要作者回应的实质分歧。
4. **发现 2 处行号引用不可解析**（`actions.py:1073`、`session.py:37/105`），**行错但结论对**；因两文件 mtime 晚于方案写作时刻，无法区分漂移与笔误，一律按"需修正"处理。
5. **发现 1 条方案自带门命令在今天的仓库状态下失效**（§十 step 2 的 `git grep` 恒零输出），并由此证明 S0.2 的验收判据在 S0.1 前**真空满足** —— 这**反向支持**了方案"S0.1 必须最先做"的排序，是该方案最稳健的判断。
6. **1 条指标口径应替换**：撤销可回放率用路径存在性会被系统自动重建污染（08:07 的 23 → 08:35 的 156，虚高 5.8 倍），必须改内容哈希。

**结论**：`DEVELOPMENT-PLAN.md` 作为**诊断**可采信（事实成立、数字可复现）；作为**工作单**需先做 §6 的 11 处修正，其中 **#1（M3.1 门判定）与 #4/#5（门命令失效）会直接误导执行**，优先级最高。

---

*核验员：plan-verifier ｜ 全部数据采集于 2026-10-12 08:31:43–08:38:30 ｜ 只读核验，未触发任何写操作 ｜ 目标系统核验期间持续运行，计数仍在漂移*
