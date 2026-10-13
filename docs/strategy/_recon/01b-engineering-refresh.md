# 01b · 工程事实复测（重建丢失卷宗 01-engineering-reality.md）

| 项 | 值 |
|---|---|
| 采集者 | repo-auditor（task-3） |
| 采集窗口 | 2026-10-12 08:06:58 – 08:12:31（+08:00） |
| 冻结时刻 | 2026-10-12 08:11:58 – 08:12:22 |
| 仓库 | `E:\OpenLookout` |
| HEAD | `dd697a51a329b8661109955fb7e2026500d8d7d0`（master） |
| git | `git version 2.50.0.windows.1` |
| 磁盘 | C: 可用 4.67 GB（已用 144.64 GB）；E: 可用 91 GB |
| 前序卷宗 | `docs/strategy/_recon/01-engineering-reality.md` **确认不存在**（`docs/strategy/_recon/` 为空目录） |
| 硬约束遵守 | 未删除/移动/重命名任何文件；未杀进程；未执行 `docker`；未 `pip install`；未建 venv；未写入 `sprite_home/`。仅写本文件。 |

### ⚠️ 采集期间仓库处于并发编辑状态（必须知道）

08:06–08:12 期间，**其他成员正在实时修改源文件**（brain.py 08:10:39、decision_engine.py 08:08:40、test_decision_engine.py 08:08:20、test_brain_wiring.py 07:53:01、test_natural_conversation.py 07:58:30、test_reclaim.py 07:45:23）。

后果：`sprite_home/perceive/supervisor.log` 出现连续热更新重启（08:09:41 / 08:10:23 / 08:10:31 …），`sprite_home/companion/runs/` 每 ~40 秒建一个新 run 目录。**这是别人的编辑触发的，不是本任务造成的**（本任务未创建、未修改任何受监视文件）。所有数字都带采集时刻，跨时刻不可直接比较。

**两个由此产生的方法论要求**：
1. **源码行号会漂移**。`brain.py` 在 08:07–08:14 之间从 902 行涨到 999 行，本文件所有 `brain.py` 行号已在 **08:14:35 逐条复核**（`live.py`、`preflight.py` 行号未变）。引用行号前请重跑 §7 的 `Select-String`。
2. **结论需要二次复核**。本次在二次复核时发现并修正了一处初判错误：`src/openlookout/observe/` **不是**死代码 —— 活的 `vista/benchmarks/desktop/historyfacts.py:14` 会 `from observe.eventlog import _parse_ts`（详见 §2.3）。**「文件在某目录下」不等于「它不在运行路径上」；必须以实际 import 为准。**

---

## 0. 结论摘要（先看这 8 条）

| # | 结论 | 证据 | 状态 |
|---|---|---|---|
| 1 | `src/openlookout/vista/` **116 个 .py / 25,730 行，git 里 0 个文件** —— 这是主线大脑本身（brain/actions/session/runtime/core/backends） | §1.2 | 实测 |
| 2 | 「7 个文件以字面引号开头入库」**不成立，是误判**。那是 git `core.quotepath` 的**显示转义**，索引里的真实文件名没有引号 | §1.4 | 实测（推翻了前序判断） |
| 3 | 真正在跑的是 `src/openlookout/sprite/`；根目录 `sprite/` 是**跑不起来的陈旧副本**（缺 `proactive/`，`-m sprite.proactive.live` 会 ModuleNotFoundError） | §2.3 | 实测 |
| 4 | `observe/`↔`src/.../observe/`、`recorder_ext/`↔`src/.../recorder_ext/` 均**逐字节全同**；`src/.../observe/observe/`、`recorder_ext/recorder_ext/`、`sprite/sprite/` 是自嵌套副本 | §2.1、§2.2 | 实测 |
| 5 | 主线测试 **234 passed / 0 failed / 0 error**（desktop 182 + proactive 22 + lookout 30，21.16s） | §3.2 | 实测 |
| 6 | `.venv312` **装不了 pytest，也缺 psutil**，无法执行本任务要求的测试；改用真实运行解释器 `D:\python3.11\python.exe`（pytest 9.0.2） | §3.1 | 实测 |
| 7 | **Windows 上代码根本不走容器通道**：`brain.build()` 在 `os.name == "nt"` 时直接返回直连后端；即使强制 `OPENLOOKOUT_NATIVE_CLAUDE=1`，容器预检也会抛 `TypeError`（8 个必填形参全部未传） | §4.2 | 实测（日志 + 签名 bind + 源码行号） |
| 8 | 真实凭据**未入库**；`.env`（untracked、已 gitignore）内有 1 个真实 API key；`provider.json` 内**不含** key | §5 | 实测 |

---

## 1. git 覆盖率

### 1.1 方法与口径

```powershell
# 采集时刻 2026-10-12 08:08:20
# 磁盘：排除 __pycache__ / .ruff_cache / .pytest_cache
Get-ChildItem <dir> -Recurse -File | Where-Object { $_.FullName -notmatch '\\__pycache__\\|\\\.ruff_cache\\|\\\.pytest_cache\\' }
# 行数：Get-Content | Measure-Object 逐文件累加（按行计，含空行、含注释）
# git：git -C E:\OpenLookout ls-files -- <dir> | Measure-Object
```

* 总盘子：`src/ + sprite/ + observe/ + recorder_ext/ + agents/ + research/` 下 **505 个 .py / 79,921 行**（08:12:00 口径，排除 third_party / .venv312 / 各类 cache）。
* 全仓 tracked 文件仅 **161 个**（08:07 口径）。
* `third_party/` 有 2,667 文件 / 542,042 行（内含 1 个子目录 `rea`），**0 tracked**；本表不计入主线判断。

### 1.2 各功能目录：磁盘 vs git（采集时刻 08:08:20）

| 目录 | 磁盘文件 | 其中 .py | 磁盘总行 | .py 行 | `git ls-files` | 覆盖率 | 判定 |
|---|---:|---:|---:|---:|---:|---|---|
| `src/openlookout/vista` | 125 | 116 | 25,942 | **25,730** | **0** | 0% | 🔴 **运行时关键 · 零版本控制** |
| ├ `vista/benchmarks/desktop` | 36 | 35 | 6,991 | 6,934 | 0 | 0% | 🔴 大脑主线 |
| ├ `vista/core` | 17 | 15 | 3,670 | 3,656 | 0 | 0% | 🔴 运行时核心 |
| ├ `vista/backends` | 20 | 20 | 5,817 | 5,817 | 0 | 0% | 🔴 模型传输通道 |
| └ `vista/benchmarks`（其余 4 个） | 46 | 43 | 9,379 | 9,377 | 0 | 0% | ⚪ 非主线 |
| `src/openlookout/sprite` | 196 | 170 | 26,453 | 25,480 | **25** | 13% | 🟠 混合 |
| ├ `sprite/proactive` | 21 | 16 | 1,870 | 1,848 | **0** | 0% | 🔴 **监督进程 + provider** |
| ├ `sprite/scenarios` | 12 | 11 | 3,525 | 2,894 | 3 | 25% | 🟠 |
| ├ `sprite/demo_live` | 17 | 9 | 629 | 528 | 13 | 76% | 🟢 |
| └ `sprite/sprite`（自嵌套） | 87 | 77 | 11,973 | 11,813 | **0** | 0% | 🔴 冗余副本 |
| `src/openlookout/lookout` | 49 | 43 | 7,658 | 6,905 | 39 | 80% | 🟢 |
| `src/openlookout/observe` | 14 | 14 | 1,226 | 1,226 | **0** | 0% | 🔴 **运行时依赖**（`vista/benchmarks/desktop/historyfacts.py:14` `from observe.eventlog import _parse_ts`）· 零版本控制 |
| `src/openlookout/recorder` | 9 | 2 | 1,445 | 203 | 6 | 67% | 🟢 |
| `src/openlookout/recorder_ext` | 8 | 0 | 306 | 0 | **0** | 0% | 🟠 |
| `src/openlookout/opportunities` | 33 | 11 | 10,571 | 1,430 | 33 | 100% | 🟢 |
| `src/openlookout/demo` | 29 | 0 | 12,833 | 0 | 29 | 100% | 🟢 |
| `src/openlookout/backfill_win` | 4 | 3 | 977 | 917 | 4 | 100% | 🟢 |
| `src/openlookout/real_data` | 6 | 5 | 1,198 | 1,155 | 6 | 100% | 🟢 |
| `observe/`（根） | 7 | 7 | 613 | 613 | **0** | 0% | 🟠 副本 |
| `recorder_ext/`（根） | 4 | 0 | 153 | 0 | **0** | 0% | 🟠 副本 |
| `sprite/`（根） | 89 | 78 | 12,698 | 11,907 | **0** | 0% | 🔴 陈旧副本 |
| `agents/` | 2 | 1 | 339 | 311 | **0** | 0% | ⚪ |
| `research/` | 7 | 3 | 460 | 324 | **0** | 0% | ⚪ |
| `third_party/` | 2,667 | 29 | 542,042 | 6,239 | **0** | 0% | ⚪ 外部 |

### 1.3 运行时关键代码零版本控制（按运行路径排）

运行路径由 §2.3 的进程证据确定；调用链：`live.py` → `vista.benchmarks.desktop.brain` → `vista.core.runtime` / `vista.backends.claude.*`。

| 优先级 | 路径 | .py 行数 | tracked | 后果 |
|---|---|---:|---:|---|
| P0 | `src/openlookout/vista/benchmarks/desktop/` | 6,934 | 0 | 大脑全部行为（companion 决策、桌面动作、撤回日志）无历史、无 diff、无法回滚 |
| P0 | `src/openlookout/vista/core/` | 3,656 | 0 | `TaskRuntime`、契约、会话循环无版本 |
| P0 | `src/openlookout/vista/backends/` | 5,817 | 0 | `claude/runner.py`（62 KB！）、Windows TCP 适配全部无版本 |
| P1 | `src/openlookout/sprite/proactive/` | 1,848 | 0 | 监督进程、热更新 `CHILDREN`、`provider.py`（key 读取）无版本 |
| P1 | `src/openlookout/vista/benchmarks/{arc3,babyvision,gameworld,aigamestore}/` | 9,377 | 0 | 非当前主线，但占体量 |
| P1 | `src/openlookout/observe/` | 1,226 | 0 | **活的运行时依赖**（`historyfacts.py:14 from observe.eventlog import _parse_ts`）却零版本 |
| P2 | `src/openlookout/sprite/sprite/`、根 `observe/`、`recorder_ext/`、根 `sprite/` | 11,813 + 613 + 0 + 11,907 | 0 | 副本/死代码，见 §2 |

**合计：主线运行时关键 .py ≈ 6,934 + 3,656 + 5,817 + 1,848 + 1,226 = 19,481 行，0 个文件受版本控制。**（其中 `observe/` 只被用了 1 个函数，但它是硬 import，缺了就 ImportError。）

**对照前序卷宗数字（诚实标注：无法精确复现）**

| 前序断言 | 本次实测 | 判定 |
|---|---|---|
| `vista/benchmarks/desktop/` 约 5,641 行、git 0 文件 | 08:08:20：6,991 总行 / 6,934 .py 行 / 0 tracked；08:11:58：**7,212 .py 行**（36 个 .py，含 17 个 `test_*.py`） | **「0 tracked」实测成立**；「5,641 行」**无法复现** —— 口径不明。敏感度：非测试 .py 仅 4,430 行、`vista/benchmarks` 全量 16,208 行，均不等于 5,641。判定：**未知**（可能是另一时点快照或另一口径） |
| `sprite/` 约 22,152 行不在运行路径上 | `src/openlookout/sprite/` .py 25,480 行；根 `sprite/` .py 11,907 行 | **「不在运行路径上」实测成立（见 §2.3）**；「22,152 行」**无法精确命中**。候选口径：去掉 `scenarios/` = 22,586；去掉 `proactive/` = 23,632；去掉 `proactive/`+`demo_live/` = 23,104；去掉 `proactive/`+`scenarios/`+`demo_live/` = 20,210。判定：**未知** |

> 结论：两条断言的**定性结论（0 tracked / 不在运行路径）本次全部实测复现**；**定量数字均无法复现**，建议后续引用时一律改用本卷实测值并附采集时刻。

### 1.4 「7 个文件以字面引号开头入库」—— 核验结论：**误判，不存在此异常**

**实测证据（采集时刻 08:09:10）**

```powershell
git -C E:\OpenLookout ls-files | Where-Object { $_ -match '"' }   # → 7 条，形如 "src/openlookout/demo/...
git -C E:\OpenLookout config --get core.quotepath                 # → 空（未设置，git 默认 = true）
```

**关键反证：用 `-z`（NUL 分隔、原始字节）读同一份索引**

```
total entries: 161
entries containing doublequote: 0        ← 索引里没有任何路径含 "
entries containing octal escape: 0       ← 索引里没有 \345 这类八进制转义
# demo 条目实际形态：
src/openlookout/demo/prepared/F11/可能受影响的记录.xlsx
src/openlookout/demo/结果报告.md
```

再叠加 `-c core.quotepath=false` 重放，7 条全部还原为不带引号的中文路径；磁盘上 7 个文件**逐个 Test-Path = True**。

**成因（实测，非推断）**：git 默认 `core.quotepath=true`。当路径含非 ASCII 字符时，`ls-files` / `status --porcelain` 会
1. 把非 ASCII 字节转成 `\NNN` 八进制转义；
2. 因为产生了特殊字符，**整条路径用双引号包裹**。

所以 `"src/...` 的 `"` 是 **git 的输出外壳**，不是文件名的第 1 个字符。（同一现象也出现在 `git status --porcelain -uall` 的 `?? "sprite_sandbox/demo/Documents` 等条目上。）

**影响（实测 + 推断）**
* 实测：仓库内容、索引、工作树**均无损坏**；`git add/commit/checkout` 对这些文件行为正常。
* 推断（风险）：任何**解析 `git ls-files` 文本输出**的脚本，若自己拼接路径，会把 `"` 和 `\345` 当成真实路径 → 找不到文件或创建垃圾文件。这类脚本是本仓库唯一真实受害者。**未发现此类脚本**（`grep` 未命中解析 `ls-files` 的代码）。

**修复命令（只给命令，不执行）**

```powershell
# A. 推荐：仅改变显示，不动仓库内容（一次性）
git config core.quotepath false

# B. 不改用户配置，仅本次命令生效
git -c core.quotepath=false ls-files
git -c core.quotepath=false status

# C. 仓库级、可随仓库分发（需团队同意，会新增 .gitattributes 文件）
#    注意：core.quotepath 是 config，不是 attributes；要固化只能靠 A 或文档
```

**不需要** `git mv`、不需要重命名任何文件。以下是**条件分支，本仓库不适用**（仅当未来真的出现字面引号文件名时使用）：

```powershell
# 仅当 `git ls-files -z` 的原始字节真的以 0x22 开头时：
# git mv '"src/openlookout/demo/xxx.xlsx' 'src/openlookout/demo/xxx.xlsx'
```

**自检命令（今后验收用）**：

```powershell
# 期望输出 0
git -C E:\OpenLookout ls-files -z | python -c "import sys;d=sys.stdin.buffer.read().split(b'\0');print(sum(1 for p in d if p.startswith(b'\x22')))"
```

---

## 2. 重复副本

### 2.1 同名目录：逐字节比对（MD5，采集时刻 08:10:05）

| A | B | A 文件数 | 逐字节相同 | 不同 | 仅 A 有 | 结论 |
|---|---|---:|---:|---:|---|---|
| `observe/` | `src/openlookout/observe/` | 7 | **7** | 0 | 0 | 完全相同的两份 |
| `recorder_ext/` | `src/openlookout/recorder_ext/` | 4 | **4** | 0 | 0 | 完全相同的两份 |
| `sprite/` | `src/openlookout/sprite/sprite/` | 89 | **87** | 0 | 2 | 同源；A 多 `demo_final_e2e.py`、`scenarios/network.py.bak_httpreach` |
| `sprite/scenarios/` | `src/openlookout/sprite/scenarios/` | 12 | **12** | 0 | 0 | 完全相同的两份 |
| `sprite/` | `src/openlookout/sprite/` | 89 | 76 同 / 2 异 | 2 | 3 | 见下表 |

**根 `sprite/` vs `src/openlookout/sprite/` 的差异（全量）**

| 相对路径 | 状态 | 根 mtime | src mtime |
|---|---|---|---|
| `demo_final_e2e.py` | 仅根有 | 2026-10-10 08:14 | — |
| `gui.py` | **内容不同** | 2026-10-10 08:14 | **2026-10-11 13:57** |
| `procctl.py` | **内容不同** | 2026-10-10 08:14 | **2026-10-10 22:23** |
| `proactive/**`（16 个 .py） | **仅 src 有** | — | — |
| `sprite/**`（自嵌套 77 个 .py） | **仅 src 有** | — | — |

### 2.2 自嵌套结构（实测）

```
src/openlookout/sprite/sprite/          87 文件 · 11,973 行   ← 根 sprite/ 的拷贝
src/openlookout/sprite/sprite/scenarios/ 11 文件 · 逐字节 == src/openlookout/sprite/scenarios/
src/openlookout/observe/observe/         7 文件 · 逐字节 == src/openlookout/observe/
src/openlookout/recorder_ext/recorder_ext/ 4 文件 · 逐字节 == src/openlookout/recorder_ext/
```

**同一份代码最多存在 4 份。** 以 `win_ctrl.py` 为例（MD5 全同，`E15157BA…`，11,399 B，采集 08:15:20）：

| # | 路径 | 目录文件数 |
|---|---|---:|
| 1 | `sprite\scenarios\win_ctrl.py`（根，陈旧） | 12 |
| 2 | `src\openlookout\sprite\scenarios\win_ctrl.py`（**活的**） | 12 |
| 3 | `src\openlookout\sprite\sprite\scenarios\win_ctrl.py`（自嵌套） | 11 |
| 4 | `_bak_20261010_081350\sprite\scenarios\win_ctrl.py`（备份目录，untracked） | 9 |

（完整 `scenarios/` 目录对比：根 12 文件 == `src/…/sprite/scenarios/` 12 文件逐字节相同；`src/…/sprite/sprite/scenarios/` 的 11 文件是它的子集、逐字节相同。）

成因（**推断**）：某次「把 `sprite/` 整体复制进 `src/openlookout/`」的迁移在错误层级重复执行了一次（`copy sprite → src/openlookout/sprite`，而当时 CWD 已经是 `src/openlookout`），于是产生了 `sprite/sprite`；`_bak_20261010_081350/` 是 2026-10-10 08:13:50 的一次手工备份。**未在任何脚本中找到该复制命令**，故标为推断。

### 2.3 哪一份在跑？——证据链（全部实测）

**证据 1 · 进程命令行（08:07:00）**

```
PID 25288  D:\python3.11\python.exe -m sprite.proactive.live
PID 26520  D:\python3.11\pythonw.exe -m sprite.proactive.live --gui
PID 24804  D:\python3.11\python.exe -m vista.benchmarks.desktop.brain
PID 12488  D:\python3.11\python.exe E:\OpenLookout\record_win.py --out E:\OpenLookout\sprite_home\perceive\operations.jsonl --ext-port 0 --parent-pid 25288 --heartbeat 60
PID 24348  D:\python3.11\pythonw.exe E:\OpenLookout\record_win.py --out E:\OpenLookout\data\events.jsonl
```

**证据 2 · `-m` 的解析只能指向 src**（08:10:20，`importlib.util.find_spec`，逐 CWD 实测）

| CWD | `sprite` → | `sprite.proactive` → | `vista` → |
|---|---|---|---|
| `E:\OpenLookout` | `E:\OpenLookout\sprite\__init__.py` | **None（不存在！）** | None |
| `E:\OpenLookout\src` | None | None | None |
| `E:\OpenLookout\src\openlookout` | `E:\OpenLookout\src\openlookout\sprite\__init__.py` | `...\sprite\proactive\__init__.py` ✅ | `...\vista\__init__.py` ✅ |

`PYTHONPATH` 为空（进程/用户/机器三级均为空）；`D:\python3.11\Lib\site-packages` 无任何指向本仓库的 `.pth` / editable install；`E:\OpenLookout\.venv312\Lib\site-packages` 无 `.pth`。
→ **唯一能让 `-m sprite.proactive.live` 成功启动的 CWD 是 `E:\OpenLookout\src\openlookout`。** 根 `sprite/` 里根本没有 `proactive/` 包。

**证据 3 · `live.py` 的源码自证（`src/openlookout/sprite/proactive/live.py`）**

| 行 | 内容 | 含义 |
|---|---|---|
| 16 / 114 | `ROOT = Path(__file__).resolve().parents[2]` | `ROOT` = `E:\OpenLookout\src\openlookout`，注释直写「`-m sprite...` 的工作目录」 |
| 117–122 | `CHILDREN = {"brain": ["-m","vista.benchmarks.desktop.brain"], "gui": ["-m","sprite.proactive.live","--gui"], "recorder": [str(ROOT.parents[1] / "record_win.py"), ...]}` | `ROOT.parents[1]` = `E:\OpenLookout` → 记录器 = `E:\OpenLookout\record_win.py` |
| 162 | `subprocess.Popen([exe, *CHILDREN[name]], cwd=ROOT, env=dict(os.environ, PYTHONUTF8="1"), ...)` | **显式 `cwd=ROOT`**，子进程全部在 `src\openlookout` 下启动 |

证据 3 的 `recorder` 参数与证据 1 中 PID 12488 的命令行**逐字吻合**（`--parent-pid 25288` 正好是监督进程 PID）。三链互证。

**证据 4 · 运行时日志（`sprite_home/perceive/child_brain.log`，08:12:23）**

```
[brain] Windows 使用 VISTA 视觉直连 runtime（设置 OPENLOOKOUT_NATIVE_CLAUDE=1 才启用容器）
[brain] 会话已建立（direct通道）：持续视觉上下文开始
```

**判定**

| 副本 | 判定 | 依据 |
|---|---|---|
| `src/openlookout/sprite/` | ✅ **在跑（活代码）** | 证据 1–4 |
| `src/openlookout/sprite/proactive/` | ✅ **在跑** | 监督进程 25288/26520 本体 |
| `src/openlookout/vista/` | ✅ **在跑** | PID 24804 + `CHILDREN["brain"]` |
| `E:\OpenLookout\record_win.py`（根） | ✅ **在跑** | PID 12488/24348 |
| `sprite/`（根） | ❌ **陈旧，不可运行** | 缺 `proactive/` 与 `vista/` → `-m sprite.proactive.live` 必失败 |
| `src/openlookout/sprite/sprite/` | ❌ **陈旧自嵌套** | 无任何 import 路径指向 `sprite.sprite.*`（全仓 grep 未命中） |
| `src/openlookout/observe/` | ✅ **在跑（活代码）** | 🚨 **修正**：`vista/benchmarks/desktop/historyfacts.py:14` 有 `from observe.eventlog import _parse_ts`，而 CWD = `src/openlookout` → 解析到 **src 这份**（`find_spec('observe.eventlog')` = `E:\OpenLookout\src\openlookout\observe\eventlog.py`，08:14 实测；`from observe.eventlog import _parse_ts` 导入成功） |
| `observe/`（根）、`src/openlookout/observe/observe/` | ⚪ **未被引用** | 与 src 版逐字节相同；根版因 CWD 不在仓库根而**永远解析不到** |
| `recorder_ext/`（根）、`src/openlookout/recorder_ext/` 及自嵌套 | ⚪ **未被引用** | 全仓 grep `import recorder_ext` / `from recorder_ext` **命中 0**；`find_spec('recorder_ext')` = `None` |

### 2.4 「可以安全删除」的判据（**本任务不执行任何删除**）

对任一候选副本 `P`，**必须全部满足**才可判「安全删除」；任一不满足即为「不可删」：

| # | 判据 | 验证命令（只读） |
|---|---|---|
| C1 | 全仓没有任何代码/脚本/文档以该模块名引用 `P` | `Select-String -Path <repo> -Include *.py,*.bat,*.ps1 -Pattern '<模块名>' -Recurse` → 期望 0。**注意：不能只用 `find_spec`** —— `find_spec('sprite.sprite')` 会返回一个路径（包存在即解析得到），但**无人引用**它，两者必须一起看 |
| C2 | 全仓无任何代码/脚本/文档引用 `P` 的相对模块名 | `git grep -n "sprite\.sprite"` / `Select-String -Path E:\OpenLookout -Include *.py,*.bat,*.md -Pattern "sprite\.sprite" -Recurse` → 期望 0 |
| C3 | 没有任何运行中进程的文件句柄落在 `P` 内 | `Get-Process | Where-Object Path` + 启动命令行核对；必要时 `handle.exe -p <pid>`（本项目未安装 handle.exe → 用命令行核对） |
| C4 | `P` 的每个文件在活的副本里都有**逐字节相同**的对应件 | §2.1 的 MD5 比对脚本 → 期望 `differing=0` |
| C5 | `P` 独有文件已单独归档 | §2.1 表：「仅 A 有」列为空，或独有文件已复制到别处并 commit |
| C6 | 被删对象**不在** `.gitignore` 覆盖范围之外（即删除不会误删需要保留的运行时数据） | 逐条 `git check-ignore -v <path>` |
| C7 | 删除前已有一次可回滚的备份/commit | 当前 `vista/`、`proactive/` 是 0 tracked，**任何删除都不可回滚** |

**按上述判据的当前结论（只判，不删）**

| 候选 | C1 | C2 | C4 | C5 | 判定 |
|---|---|---|---|---|---|
| `src/openlookout/sprite/sprite/` | ✅ None | ✅ 0 | ✅ 87/87 同 | ❌ 根 `sprite/` 的 2 个独有文件在**根**副本里 | **暂不可删**（先处理 C5） |
| `src/openlookout/observe/observe/` | ✅ | ✅ | ✅ 7/7 | ✅ | 判据层面满足（父目录 `observe/` 是活的、且与它逐字节相同；无代码引用 `observe.observe`） |
| `src/openlookout/recorder_ext/recorder_ext/` | ✅ | ✅ | ✅ 4/4 | ✅ | 同上 |
| `E:\OpenLookout\sprite/`（根） | ✅ | ⚠️ `sprite/run_sprite.bat`、`sprite/scenarios/__init__.py` 等出现在 `git status -uall` 的 untracked 列表 | ❌ `sprite/gui.py`、`sprite/procctl.py` 与活的副本**内容不同**（根版更旧） | ❌ 有 2 个独有文件 | **不可删**：虽然它跑不起来，但 2 个独有文件 + 2 个旧版本是**唯一的历史样本**，且 `vista/` 全是 0 tracked —— 删了就无法回溯「改了什么」 |
| `E:\OpenLookout\observe/`、`E:\OpenLookout\recorder_ext/`（根） | ✅ | ✅ | ✅ | ✅ | 与 src 版逐字节相同，属**冗余**；但同样零版本控制 → 建议**先 commit 再删**，不要直接删 |

> **推荐顺序（不含删除动作，供后续决策）**：先把活的副本 `src/openlookout/vista/` + `src/openlookout/sprite/proactive/` 纳入 git（此时 HEAD 才有可回滚点）→ 再处理副本。**在 C7 不满足之前，任何副本都不应删除。**

---

## 3. 测试真状态

### 3.1 环境（**重要偏差声明**）

| 项 | 实测 | 影响 |
|---|---|---|
| `.venv312\Scripts\python.exe` | Python 3.12.10；**`ModuleNotFoundError: No module named 'pytest'`** | 🔴 **无法执行本任务要求的测试**。`pip install` 被硬约束禁止 → 未安装 |
| `.venv312` 缺 `psutil` | `import sprite.proactive.live` → `ModuleNotFoundError: No module named 'psutil'` | 🔴 该 venv 连主线包都导入不了 |
| `.venv312` 有的 | PIL/Pillow 12.2.0、certifi、tkinter、requests、python-dotenv、numpy 2.5.1、playwright 1.45.0、flask、jsonschema | — |
| **实际运行解释器** | `D:\python3.11\python.exe` = **Python 3.11.9**，pytest **9.0.2**，psutil **7.2.2**，PIL/certifi/tkinter/requests/dotenv/numpy 全 OK | ✅ 本文所有测试用它跑 |
| 依此判定 | AGENTS.md 第 66 行写「前置：Windows、Docker Desktop 已运行、**Python 3.11**」→ **`D:\python3.11` 才是被认可的解释器；`.venv312` 是半成品** | 见 §4 |
| C 盘 | 可用 **4.67 GB**（08:06:58） | 本次**无任何磁盘相关失败**。AGENTS.md 第 107 行记录的「C 盘仅剩 ~29MB，`sprite/` 大量测试因 `could not create` 失败」是**历史状态**，当前**不复现** |
| 依赖清单 | 仓内唯一 requirements：`src/openlookout/requirements-proactive.txt`（ddgs / trafilatura / winrt-*），**且该文件本身未被 git 跟踪** | 🔴 它**不含** psutil / pillow / certifi —— 主线依赖没有任何声明文件 |

**执行环境（原样记录）**

```powershell
Push-Location E:\OpenLookout\src\openlookout
D:\python3.11\python.exe -m pytest vista/benchmarks/desktop sprite/proactive lookout `
  -q -p no:cacheprovider --tb=line
```

`-p no:cacheprovider` 用于避免写入 `.pytest_cache`（遵守「只写自己的交付文件」）。测试使用 pytest `tmp_path`（系统临时目录 `pytest-of-q`），**未向 `sprite_home/` 写入任何文件**（08:12:31 核查：`sprite_home` 下 12 分钟内的所有变更均来自活的 brain/recorder 自身：`companion/runs/*/artifacts/*`、`decisions.jsonl`、`operations.jsonl`、`child_brain.log`、`supervisor.log`）。

### 3.2 结果（冻结时刻 08:12:22）

| 套件 | 路径 | collected | passed | failed | error | 耗时 |
|---|---|---:|---:|---:|---:|---:|
| A · 桌面大脑主线 | `vista/benchmarks/desktop/` | 182 | **182** | 0 | 0 | 13.47 s（08:09:39–08:09:50 首跑） |
| B · 主动监督线 | `sprite/proactive/` | 22 | **22** | 0 | 0 | 0.72 s |
| C · lookout（纯标准库为主，附加） | `lookout/` | 30 | **30** | 0 | 0 | 9.70 s |
| **合计（08:12:22 合并重跑）** | — | **234** | **234** | **0** | **0** | **21.16 s** |

```
........................................................................ [ 30%]
........................................................................ [ 61%]
........................................................................ [ 92%]
..................                                                       [100%]
234 passed in 21.16s
```

### 3.3 「真失败」vs「环境/依赖/磁盘缺失」

| 类别 | 数量 | 说明 |
|---|---:|---|
| 真失败（断言/逻辑错） | **0** | 234/234 通过 |
| error（收集期/夹具错误） | **0** | 两个目录 `--collect-only` 均干净（182 + 22） |
| 环境/依赖缺失导致**未能执行** | **2 处** | ① `.venv312` 缺 pytest → 本任务指定的解释器无法跑测试；② `.venv312` 缺 psutil → 无法导入 `sprite.proactive.live` |
| 磁盘导致 | **0** | C: 4.67 GB 可用；无 `OSError [Errno 28]`；AGENTS.md 记录的历史磁盘失败**本次不复现** |
| 网络/外部服务导致 | **0** | 测试用假后端（`test_help_e2e.py:1` 明确写「不需要 Docker，不改用户电脑」）；`test_weather.py` 用例显式断言「provider 失败时静默」 |

**测试安全性核查（08:08:50，确认不会打断运行中的系统）**

| 文件 | 危险调用 | 实际行为 |
|---|---|---|
| `test_help_e2e.py:119` | `subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])` | 起一个 30 秒自杀的假受害进程，随后 monkeypatch `psutil.Process.suspend` → **不真的挂起任何东西** |
| `test_trim.py:25-27` | 同上，假受害进程 | 隔离，会被回收 |
| `test_help_chain.py:146` | `monkeypatch.setattr(subprocess, "run", ...)` | 拦截，不真的起进程 |
| `test_basics.py:*` / `test_natural_conversation.py:108` | `monkeypatch.setattr("PIL.ImageGrab.grab", ...)` | 截屏被替换为内存图，**不抓真实屏幕** |
| 全仓库测试 | 无 `docker` / 无 `taskkill` | ✅ |

**未跑（明确不在本次范围）**

| 未跑 | 原因 |
|---|---|
| `src/openlookout/sprite/test_*.py`（19 个）/ `sprite/sprite/test_*.py` | 非本任务指定主线；且属于本卷 §2 判定的陈旧副本 |
| `vista/benchmarks/{arc3,babyvision,gameworld,aigamestore}` | 非主线且大量依赖外部资源/镜像 |
| `opportunities/`、`lookout/world_kits/`、`backfill_win/` | beyond scope（lookout 顶层已附加覆盖 30 例） |
| 全仓库 | 明确不跑 |

---

## 4. 分发与运行前置

### 4.1 「一个新人跑起来」实际需要的步骤（逐条验真）

| # | 步骤 | 文档出处 | 真实性 | 证据 |
|---|---|---|---|---|
| 1 | Windows | AGENTS.md:66 | ✅ **真** | 运行进程为 Windows `pythonw.exe`；`brain.build()` 有 `os.name == "nt"` 分支 |
| 2 | Python **3.11** | AGENTS.md:66 | ✅ **真**，但**文档没说是哪一个** | 活进程全部用 `D:\python3.11\python.exe`（3.11.9）。仓内 `.venv312`（3.12）**缺 pytest + psutil**，用它跑不起来 |
| 3 | 依赖：`psutil`、`Pillow`(PIL.ImageGrab)、`certifi`、`tkinter` | **文档未写** | 🔴 **缺失声明** | `sprite/proactive/perceive.py:14`、`vista/benchmarks/desktop/actions.py:17`、`systemfacts.py:24`、`watching.py:225` 硬导入 psutil；`session.py:8` 硬导入 PIL；`brain.py:15` 导入 certifi |
| 4 | `cd src\openlookout` 后 `python -m sprite.proactive.live` | AGENTS.md:69-72 | ✅ **真** | §2.3 证据 2/3；CWD 必须是 `E:\OpenLookout\src\openlookout`（按 AGENTS.md 从仓库根 `cd src\openlookout` 即得），根目录 `E:\OpenLookout` 下启动会 `ModuleNotFoundError: sprite.proactive` |
| 5 | 复制 `.env.example` → `.env`，填 `SPRITE_API_KEY` | AGENTS.md:77 | ✅ **真** | `provider.py:13` `ENV_KEY = "SPRITE_API_KEY"`；`.env.example` 内容 `SPRITE_API_KEY=PUT-YOUR-KEY-HERE` |
| 6 | 复制 `provider.example.json` → `provider.json`，填协议/地址/模型名 | AGENTS.md:77 | ✅ **真** | `provider.py:50` 读 `protocol/base_url/model` + `load_api_key()`；两文件键完全一致（protocol/base_url/model），**均不含 key** |
| 7 | 设置 `SPRITE_HOME`（默认 `E:\OpenLookout\sprite_home`） | AGENTS.md:46 | ⚠️ **硬编码** | `brain.py:20` `HOME = Path(os.environ.get("SPRITE_HOME", r"E:\OpenLookout\sprite_home"))` —— **绝对路径写死在源码里**，换机器/换目录必须设环境变量 |
| 8 | **Docker Desktop 已运行** | AGENTS.md:66 | ❌ **在 Windows 主线上是伪前置** | 见 §4.2：代码在 Windows 上直接短路到直连后端，**不碰 Docker**。Docker 只是装着的 |
| 9 | `docker build -f vista/Dockerfile.claude-player -t arc3-claude-player:0.1 vista` | AGENTS.md:75 | ❌ **当前无意义** | 同上 + §4.2 TypeError：镜像建好了容器通道也用不了 |
| 10 | Linux 版 Claude Code 2.1.220 放到 `sprite_home/bin/claude-linux-2.1.220` | AGENTS.md:76 | ⚠️ **文件在，但代码不用它** | 文件**存在**：`E:\OpenLookout\sprite_home\bin\claude-linux-2.1.220`，**275,012,592 字节**（2026-10-10 14:25）。但只有 `OPENLOOKOUT_NATIVE_CLAUDE=1` 才读它，而该分支必抛 TypeError（§4.2） |
| 11 | `record_win.py` 需自行运行 | 未写 | ✅ 由 `live.py:120-121` 自动拉起 | 活进程 PID 12488 |

### 4.2 容器通道核验：**确实会抛 TypeError，且 Windows 上根本不进去**

**（A）Windows 上第一道短路 —— 直连，不碰容器**

`src/openlookout/vista/benchmarks/desktop/brain.py:762-764`（行号于 **08:14:35 复核**；该文件在 08:07–08:14 间被其他成员从 902 行改到 999 行，行号曾位移）

```python
762:  if os.name == "nt" and os.environ.get("OPENLOOKOUT_NATIVE_CLAUDE") != "1":
763:      print("[brain] Windows 使用 VISTA 视觉直连 runtime（设置 OPENLOOKOUT_NATIVE_CLAUDE=1 才启用容器）", flush=True)
764:      return session, runtime, VisualDirectBackend(cfg, runtime), "direct"
```

**运行时日志实证**（`E:\OpenLookout\sprite_home\perceive\child_brain.log`，采集 08:12:23）：

```
[brain] Windows 使用 VISTA 视觉直连 runtime（设置 OPENLOOKOUT_NATIVE_CLAUDE=1 才启用容器）
[brain] 会话已建立（direct通道）：持续视觉上下文开始
```

`OPENLOOKOUT_NATIVE_CLAUDE` 在 process/user/machine 三级环境变量中**均为空**（08:11:00 实测）。
→ **本次运行的 brain 走 `direct` 通道，容器通道一次都没有被进入。**

**（B）即便强制打开容器开关，也必抛 TypeError —— 8 个必填形参全部未传**

`brain.py:772-775`（调用方）：

```python
772:  from vista.backends.claude.preflight import run_runtime_preflight
773:  binary = HOME / "bin" / "claude-linux-2.1.220"
774:  run_runtime_preflight(binary=binary, provider=MIMO_PROVIDER,
775:                        provider_credential=cfg["api_key"], provider_base_url=cfg["base_url"])
```

`vista/backends/claude/preflight.py:31-50`（函数签名，`*` 之后全为 **keyword-only 且无默认值**）：

```python
31: def run_runtime_preflight(
32:     *, visible_dir: Path, config_dir: Path, io_dir: Path, claude_bin: Path,
        model: str, effort: str, timeout: int, tool_interface: ToolInterface,
        oauth_token=None, ..., image: str = PLAYER_IMAGE, ...) -> tuple[ClaudeResult, str]:
```

**实测复现（未执行 docker，仅用 `inspect.signature().bind()` 复现调用点，08:10:50）**

```
params: ['visible_dir', 'config_dir', 'io_dir', 'claude_bin', 'model', 'effort', 'timeout',
         'tool_interface', 'oauth_token', 'rate_limit_observer', 'ca_bundle', 'image',
         'native_compaction', 'provider', 'provider_credential', 'provider_base_url', 'max_output_tokens']
TypeError -> missing a required keyword-only argument: 'visible_dir'
```

**二次复核（08:14:42，`brain.py` 已被他人改过之后重跑，结论不变）**

```
REQUIRED (no default): ['visible_dir', 'config_dir', 'io_dir', 'claude_bin', 'model', 'effort', 'timeout', 'tool_interface']
TypeError -> missing a required argument: 'visible_dir'
```

**缺失参数清单（形参共 17 个，其中 8 个无默认值，全部未传）**：`visible_dir`、`config_dir`、`io_dir`、`claude_bin`、`model`、`effort`、`timeout`、`tool_interface`。
另外 `binary=` 也**不是**形参名（真名是 `claude_bin`），所以即使补齐前 8 个，多余的 `binary` 关键字还会再抛一次 `TypeError`。

**为什么线上没崩？** `brain.py:782-784` 用**裸 `except Exception`** 兜住：

```python
782:  except Exception as e:                       # 容器/镜像/传输起不来，不该让整个 brain 死掉
783:      print(f"[brain] 容器通道不可用（{type(e).__name__}: {str(e)[:80]}），改走直连模型", flush=True)
784:      return session, runtime, VisualDirectBackend(cfg, runtime), "direct"
```

→ 结论：**容器通道在这份代码里是死代码**。文档把它写成「标准传输通道」（AGENTS.md:14 架构图）/「前置依赖」（AGENTS.md:66），与代码行为**不一致**；`OPENLOOKOUT_NATIVE_CLAUDE=1` 这个开关**打开即失败**，只是失败被静默降级吞掉了。

**（C）容器通道的非 Windows 路径同样依赖 Docker**（供交叉参考，本次未执行）

`vista/backends/preflight.py:43-52`

```python
43:  image = subprocess.run(
44:      ["docker", "image", "inspect", PLAYER_IMAGE, "--format", "{{json .Id}}"],
45:      check=True, capture_output=True, text=True, timeout=20)
```

以及 `claude/runner.py:188-190`、`:1146`（`docker run`）、`codex/runner.py:868`（`docker run`）。
→ 真正需要 Docker 的是 **arc3 / babyvision / codex** 等 benchmark 的 `check_transport()`，**不是** Windows 桌面主线。

### 4.3 外部依赖清单（按「是否真的被当前运行路径使用」排序）

| 依赖 | 是否真的需要 | 状态 | 证据 |
|---|---|---|---|
| Python 3.11（非 3.12） | ✅ 必须 | 已装 `D:\python3.11` (3.11.9) | 活进程命令行 |
| `psutil` | ✅ 必须（硬导入） | 已装 7.2.2 | `perceive.py:14`、`actions.py:17` |
| `Pillow`（`PIL.ImageGrab`） | ✅ 必须 | 已装 | `desktop/session.py:8` |
| `certifi`（CA bundle） | ✅ 必须 | 已装 2026.07.22 | `brain.py:15` |
| `tkinter`（GUI 气泡） | ✅ 必须 | 已装 | `sprite/gui.py` |
| `.env` + `SPRITE_API_KEY` | ✅ 必须 | **存在，含真实 key**（见 §5） | `provider.py:13,38` |
| `provider.json`（protocol/base_url/model） | ✅ 必须 | **存在** | `provider.py:50` |
| 可访问的模型端点 | ✅ 必须 | **未验证**（不发起真实请求） | `brain.py:368` 直接 POST `cfg["base_url"]` |
| **Docker Desktop** | ❌ **当前主线不需要** | 已装且运行中（`docker.exe` = `C:\Program Files\Docker\Docker\resources\bin\docker.exe`；`Docker Desktop`/`com.docker.backend` 共 7 个进程） | §4.2(A) |
| **`arc3-claude-player:0.1` 镜像** | ❌ 当前主线不需要 | **未知**（禁止执行 docker，无法验证是否存在） | §4.2(C) 需 Docker 的是 benchmark |
| **`sprite_home/bin/claude-linux-2.1.220`** | ❌ 当前主线不读 | **存在**，275,012,592 B | `brain.py:773` 在 `direct` 分支之后 |
| `SPRITE_HOME` 环境变量 | ⚠️ 换了机器才需要 | 未设置（源码硬编码兜底） | `brain.py:20` |

### 4.4 明确标为「未知」的项

| 项 | 为什么未知 |
|---|---|
| `arc3-claude-player:0.1` 镜像是否存在 / 多大 | 禁止执行 `docker`（会挂 120 秒），无法探测 |
| `provider.json` 里 `base_url` 是否可达 | 需要发起真实网络请求 → 未做（不属于只读核验范围） |
| 真实使用中「容器通道」在 Linux 上能否跑通 | 本机是 Windows，且调用点已证明缺参 → 只能在 Linux 侧另行验证 |

---

## 5. 密钥与隐私卫生

> 本节**只报告「有 / 无」与文件名**。任何 key 的值、片段、长度以外的信息均未写入本文件，也未写入任何消息。

### 5.1 已入库（tracked）文件里有没有真实 key？—— **没有**

```powershell
# 采集时刻 2026-10-12 08:11:10
git -C E:\OpenLookout grep -I -n -E <pattern> -- . ':(exclude)third_party'
```

| 模式 | tracked 命中数 |
|---|---:|
| `sk-ant-` | **0** |
| `sk-[A-Za-z0-9]{20,}` | **0** |
| `AAAAC3NzaC`（Anthropic OAuth） | **0** |
| `AIzaSy`（Google） | **0** |
| `xoxb-`（Slack） | **0** |
| `ghp_[A-Za-z0-9]{20,}`（GitHub PAT） | **0** |
| `eyJ...eyJ...`（JWT） | **0** |
| `api[_-]?key\s*[:=]\s*["'][A-Za-z0-9_-]{16,}` | **0** |

补充：对 `src/ sprite/ observe/ recorder_ext/ agents/ research/` 下**全部未跟踪源文件**（.py/.json/.js/.md/.txt/.bat/.yaml）做同一组模式扫描 → **命中 0**。

**判定：真实 key 未入库。** ✅

### 5.2 凭据文件清点

| 文件 | 存在 | git 状态 | 是否含真实凭据 | 依据 |
|---|---|---|---|---|
| `.env` | ✅ 是 | **untracked**，被 `.gitignore:16 *.env` 覆盖（`git check-ignore` 确认） | ✅ **有**（变量名 `SPRITE_API_KEY`，值长度 51，判定为真实 key：不匹配 `your/xxx/placeholder/changeme/<` 等占位特征） | 只读统计，未记录值 |
| `.env.example` | ✅ 是 | untracked | ❌ **无**（内容为 `SPRITE_API_KEY=PUT-YOUR-KEY-HERE`，占位符） | 明文模板 |
| `src/openlookout/sprite/proactive/provider.json` | ✅ 是 | **untracked**，被 `.gitignore:23` 精确忽略 | ❌ **无**（仅 3 个键：`protocol` len=9、`base_url` len=46、`model` len=15，**没有 key 字段**） | `load_api_key()` 从环境变量/`.env` 取 |
| `src/openlookout/sprite/proactive/provider.example.json` | ✅ 是 | untracked | ❌ **无**（同 3 键） | — |
| 全仓其他 `provider*.json` / `.env*` | 无（`third_party`、`.venv312` 外） | — | — | 递归搜索确认只有以上 4 个 |

### 5.3 结构判断

* key 的**唯一入口**是 `sprite/proactive/provider.py:13` `ENV_KEY = "SPRITE_API_KEY"` + `load_api_key()`（`:38`）→ `.env` 或环境变量。设计正确，且 `.env` 已被忽略。
* **风险（推断，未验证）**：`.env` 与 `provider.json` 都**零版本控制且只在本机**（`E:\OpenLookout`）→ 一旦机器丢失，配置无法重建；同时 `provider.json` 被 `.gitignore` 精确忽略意味着**新人必须手动创建**，文档（AGENTS.md:77）已覆盖此点。
* `.gitignore` 覆盖：`.env`、`*.env`、`*.pem`、`*.key`、`sprite_home/`、`src/openlookout/sprite/proactive/provider.json`、`agents/.locks.json` 均在列 ✅。
* **未见** `.env` 被误加入索引（`git ls-files --error-unmatch .env` → 报错「did not match」，即未跟踪）✅。

---

## 6. 断言台账：实测 / 推断 / 未知

| 断言 | 等级 | 依据 |
|---|---|---|
| HEAD=`dd697a5`，master | 实测 | `git rev-parse` |
| tracked 文件总数 = 161 | 实测 | `git ls-files \| Measure-Object`（08:07） |
| `src/openlookout/vista/**` tracked = 0，25,730 行 .py | 实测 | §1.2 |
| `src/openlookout/sprite/proactive/**` tracked = 0，1,848 行 .py | 实测 | §1.2 |
| 主线运行时关键代码 ≈19,481 行零版本控制 | 实测（求和） | §1.3 |
| 7 条 `"` 前缀是 git quotepath 显示转义，非文件名 | 实测 | `-z` 原始字节 0 命中 + 磁盘 7/7 存在 + `-c core.quotepath=false` 复现 |
| 根 `sprite/` 缺 `proactive/` → 不是活代码 | 实测 | `find_spec` 三 CWD + 目录清单 |
| 活代码 CWD = `E:\OpenLookout\src\openlookout` | 实测（三链互证） | 进程命令行 + `find_spec` + `live.py:16/117-122/162` + recorder 参数逐字吻合 |
| `sprite/sprite/`、`observe/observe/`、`recorder_ext/recorder_ext/` 为自嵌套冗余 | 实测 | MD5 全同比对 |
| `src/openlookout/observe/` **是**活的运行时依赖（`historyfacts.py:14`），根 `observe/` 不是 | 实测（**修正了初判**） | `find_spec('observe.eventlog')` = src 路径 + `from observe.eventlog import _parse_ts` 导入成功 + 全仓 grep 引用点 |
| `sprite.sprite` / `recorder_ext` 无任何代码引用 | 实测 | `Select-String` 全仓扫描：`sprite\.sprite` 0 命中、`import recorder_ext` 0 命中 |
| 234 passed / 0 failed / 0 error | 实测 | 08:12:22 pytest，`D:\python3.11` + pytest 9.0.2 |
| `.venv312` 无法跑测试（缺 pytest、缺 psutil） | 实测 | `ModuleNotFoundError` 两处 |
| C: 4.67 GB 可用，无磁盘相关失败 | 实测 | `Get-PSDrive` |
| 容器通道在 Windows 不进且必抛 TypeError | 实测 | `child_brain.log` + `signature.bind()`（08:10:50 与 **08:14:42 两次复核**）+ `brain.py:762/774` + `preflight.py:31` |
| `sprite_home/bin/claude-linux-2.1.220` 存在（275 MB） | 实测 | 文件列表 |
| Docker Desktop 已安装且运行 | 实测 | `Get-Command docker` + 7 个进程 |
| `arc3-claude-player:0.1` 镜像是否存在 | **未知** | 禁止执行 docker |
| `provider.json` base_url 是否可达 | **未知** | 未发请求 |
| 「sprite/sprite 由错误层级的复制产生」 | **推断** | 目录形态吻合；未找到执行该复制的脚本 |
| 「解析 ls-files 文本的脚本会因 quotepath 出错」 | **推断** | 机制成立；仓内未发现该类脚本 |
| 前序「desktop ≈5,641 行」/「sprite ≈22,152 行」的口径 | **未知** | 所有候选口径都不等于该值，无法复现 |

---

## 7. 复现命令清单（全部只读，可直接粘贴）

```powershell
$root='E:\OpenLookout'
# —— §1 覆盖率
git -C $root ls-files | Measure-Object
git -C $root status --porcelain=v1 -uall | Where-Object { $_ -like '??*' } | Measure-Object
# —— §1.4 quotepath 反证
git -C $root config --get core.quotepath
git -C $root -c core.quotepath=false ls-files -- src/openlookout/demo
git -C $root ls-files -z | python -c "import sys;d=sys.stdin.buffer.read().split(b'\0');print('entries',len([p for p in d if p]));print('literal-quote',sum(1 for p in d if p.startswith(b'\x22')))"
# —— §2.3 哪份在跑
Get-CimInstance Win32_Process -Filter "Name like '%python%'" | Select-Object ProcessId,CommandLine
Push-Location "$root\src\openlookout"; D:\python3.11\python.exe -c "import importlib.util as u;print(u.find_spec('sprite.proactive').origin)"; Pop-Location
Push-Location $root;               D:\python3.11\python.exe -c "import importlib.util as u;print(u.find_spec('sprite.proactive'))"; Pop-Location
Get-Content "$root\sprite_home\perceive\child_brain.log" -Tail 20 -Encoding UTF8
# —— §3 测试
Push-Location "$root\src\openlookout"
D:\python3.11\python.exe -m pytest vista/benchmarks/desktop sprite/proactive lookout -q -p no:cacheprovider --tb=line
Pop-Location
# —— §4.2 TypeError
Push-Location "$root\src\openlookout"
D:\python3.11\python.exe -c "import inspect;from vista.backends.claude.preflight import run_runtime_preflight as f;print(inspect.signature(f))"
Pop-Location
# —— §5 密钥
git -C $root grep -I -n -E 'sk-ant-|sk-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{20,}' -- . ':(exclude)third_party'
git -C $root check-ignore -v .env src/openlookout/sprite/proactive/provider.json
```

---

## 8. 给路线图的 5 条工程结论（不涉及任何文件改动）

1. **主线大脑（~19,481 行运行时关键代码）零版本控制，是本仓库最大的单点风险。** 任何一次「清理副本」或「重构」在此之前都**不可回滚**（§2.4 判据 C7 不满足）。建议把「`vista/` + `sprite/proactive/` + `observe/` 入 git」排在所有重构之前。
2. **前序卷宗的两条关键事实，定性成立、定量不成立。** 「`vista/benchmarks/desktop/` 0 个 git 文件」与「`sprite/` 不在运行路径上」本次均实测复现；但 5,641 / 22,152 两个行数**无法复现**，引用时应改用本文口径并附采集时刻（且仓库正被并发编辑，数字有分钟级漂移）。
3. **「7 个字面引号文件名」是误判，需从路线图前提中删除。** 它是 `core.quotepath` 的显示行为，仓库无损坏，不需要 `git mv`。真正需要修的只有「解析 `git ls-files` 文本的脚本」这一潜在风险（尚未发现实例）。
4. **分发叙事与代码行为不一致。** 文档把 Docker Desktop / 镜像 / Linux 版 Claude 二进制写成前置；实际 Windows 主线**完全不走容器**（`brain.py:762` 短路），而强制走容器会因 `brain.py:774` 少传 8 个必填参数抛 `TypeError`，被 `except Exception`（`:782`）静默吞掉。**「新人跑起来」的真实最小依赖 = Python 3.11 + psutil + Pillow + certifi + tkinter + `.env` + `provider.json`**，与 Docker 无关。
5. **`.venv312` 是陷阱。** 任务指定的 `.venv312` 既无 pytest 也无 psutil，连 `sprite.proactive.live` 都导入不了；真实解释器是 `D:\python3.11`（3.11.9 + pytest 9.0.2 + psutil 7.2.2）。主线依赖**没有任何声明文件**（唯一的 `requirements-proactive.txt` 未被跟踪，且内容与主线无关），建议补一份主线 requirements。
