# 独立验证报告：开口结果信号（沉默≠拒绝 / 门槛方向 / 实机安全）

- 验证者：`verifier`（独立验证者，只读 + 跑命令，**不修改任何源码或测试**）
- 任务：共享任务板 `task-3`
- 被验证对象：`sprite/proactive/` 下的「开口结果信号」改动 —— T1（`signal-fixer`：结果标签语义 + 门槛方向）与 T2（`metric-builder`：结果度量报告）
- 报告时间：2026-10-12 ~12:59（所有时间均为本机本地时间）
- 代码根：`E:\OpenLookout\src\openlookout`；测试解释器 `D:\python3.11\python.exe`（pytest 9.0.2）
- 声明：本报告全部结论来自**我自己跑的命令/我自己读的原文**，不引用队友的转述；结尾单列「我没能验证的」。

---

## 0. 一句话结论（先说人话）

1. **T2 的度量报告成立**：它的核心主张「沉默不算拒绝、5 条真实账本全是无证据、此时不能说开口质量变好」我实测复现，结论确实写的是「不能」。
2. **T1 的方向修好了，但没验完**：旧代码确实「越没人理越爱开口」（我一独立复现到 benefit=300、门槛对全部 app 变松）；新代码在同一合成数据上回到出厂先验 60.0、不再变松。但 **T1 落地后 `pytest sprite/proactive` 不是全绿：`1 failed, 58 passed`**，失败的是 T2 的测试（跨任务测试污染，**不是生产代码缺陷**）。
3. **实机没被弄坏**：brain（pid 39156）自 11:38:50 起未被重启；今天 12:53:33 的 GUI 子进程更替是**队友改代码触发的热更新**，不是崩溃；supervisor.log 尾部无崩溃重启循环。

---

## 1. 产物指纹（我实测，供复核对账）

行数一律用 Python `splitlines()` 数（PowerShell `Measure-Object -Line` 对混合换行文件会少数，Lead 已确认过一次踩坑）。

**before（我抢先冻结的快照）** `%TEMP%\olv_verify\before\`

| 文件 | 行 | 字节 | sha256(前16) | mtime |
|---|---|---|---|---|
| `sprite/proactive/timing.py` | 546 | 24312 | `cba94c377c800351` | 2026-10-12 11:05:02 |
| `sprite/proactive/live.py` | 487 | 21742 | `1fd50767…` | 2026-10-12 10:41:33 |

- 交错核对：`E:\OpenLookout\tmp_team_t1\orig\timing.py`（`signal-fixer` 自己留的 before 副本）与我的快照 **sha256 一致**（都是 `cba94c37…`，24312 字节）。
- 补充事实：`sprite/proactive/` **整个目录不在 git 跟踪内**（`git ls-files src/openlookout/sprite/proactive/` 为空，仓库 HEAD `dd697a5`）→ **拿不到 HEAD 版当 before**，我抢在队友写入前落盘的这份快照就是 before 证据。

**after（T1/T2 落地后）**

| 文件 | 行 | 字节 | sha256(前16) | mtime |
|---|---|---|---|---|
| `sprite/proactive/timing.py` | 572 | 26802 | `37e68ed2…` | 2026-10-12 12:54:40 |
| `sprite/proactive/live.py` | 510 | 23056 | `39edc5f6…` | 2026-10-12 12:55:01 |
| `sprite/proactive/outcome_report.py` | 819 | 40667 | `f4b2b67e…` | 2026-10-12 12:53:32 |
| `sprite/proactive/test_outcome_report.py` | 390 | 18756 | `23e2c297…` | 2026-10-12 12:51:56 |
| `sprite/proactive/test_outcome_labels.py`（T1 自写） | 144 | 6786 | `225b349b…` | 2026-10-12 12:55:59 |
| `sprite/gui.py`（**未被改动**） | — | — | `56eae9c1…` | 2026-10-11 13:57:33 |

注：`outcome_report.py` 我第一次读到的是 `ed01020a…`（814 行，12:50:23），12:53:32 又被队友改成 819 行；**下面所有 T2 结论都基于 12:53:32 的 819 行版本重测过**。

---

## 2. 复核 1：病根独立复现 + before/after 对比 —— ✅ 复现成立

**方法**：我自写探针（只写自己的临时目录，不碰仓库数据），构造合成 `outcomes.jsonl`，直接调用
`timing.learned_benefit_s(path)` 与 `timing.stop_threshold(app, benefit_s=...)`，再与出厂先验 `BENEFIT_S=60` 比较。
探针脚本：`%TEMP%\olv_verify\probe1.py`；运行命令：

```powershell
cd E:\OpenLookout\src\openlookout
D:\python3.11\python.exe C:\Users\q\AppData\Local\Temp\olv_verify\probe1.py <case> <tmpdir>
```

### 2.1 before 原始数字（旧 timing.py，sha `cba94c37…`）

- `A_20ignored`（20 行 outcome="ignored"）：
  - `benefit = 300.0`，why = `"观测有效率下界为 0（0/20），门槛取上限，保守到几乎不开口"`
  - `p* = cost/benefit`：tabbit `0.59` vs 先验 `0.95`；microsoft-edge `0.5567` vs `0.95`；default `0.09` vs `0.45`；notepad `0.13` vs `0.65` → **四个 app 全部 LOOSER**
- `E_10_10`（10 accepted + 10 ignored）：`benefit = 130.31` → default `p*=0.2072` vs `0.45` → **LOOSER**

**关键矛盾（病根）**：注释自称「保守到几乎不开口」，但 `p* = COST_S_DEFAULT / benefit`（`timing.py:148`）随 benefit **增大而变小**，也就是门槛更**容易**触发 —— 实际效果与注释相反。这是我在旧代码上**独立复现**出来的。

### 2.2 after 原始数字（新 timing.py，sha `37e68ed2…`）

- `A_20ignored`：`benefit = 60.0`（= 出厂先验），why = `"可判定的结果行只有 0 条（<20；另有 20 条沉默/仅确认（无证据），不计入）"` → 四个 app 全部 **SAME**
- `E_10_10`：`benefit = 60.0` → **SAME**（不再变松）
- `C_20accepted`（20 行 accepted，纯正面证据）：`benefit = 46.49` → tabbit/notepad **TIGHTER**（真信号仍能校准门槛，学习功能没被一并关掉）

### 2.3 对照表

| 合成用例 | before benefit | before 方向 | after benefit | after 方向 |
|---|---|---|---|---|
| 20×ignored | 300.0 | LOOSER（4/4 app） | 60.0 | SAME |
| 10 accepted + 10 ignored | 130.31 | LOOSER | 60.0 | SAME |
| 20×accepted | — | — | 46.49 | TIGHTER |

**判定：检查 1 通过。** 病根被独立复现，方向已修正。

---

## 3. 复核 2：companion 超时 → ignored 的路径 —— ✅ 读码成立，⚠️ 未做行为验证

### 3.1 path 的每一段（before，我逐行读的原文）

- `sprite/gui.py:186-187`
  `wait = seconds * (5 if msg.get("options") else 1)`
  `self.hide_job = self.win.after(wait * 1000, lambda: self.hide(expired=True))`
- `sprite/gui.py:190` `if self.msg and expired: self.on_expire()`
- `sprite/proactive/live.py:303-305`（before）：companion 分支 `present(..., 180, ...)`（无 options）
- `sprite/proactive/live.py:269-271`（before）：
  ```python
  def on_expire() -> None:
      record_outcome(offer_state.get("offer"), "ignored")
  ```
  **不看 kind、不看有没有 options** → companion 气泡 180s 超时（无选项 ×1）也记一次 `ignored`。
- 而 `timing.py:107`（before）`_NEGATIVE = {"ignored", "rejected"}` → companion 的沉默被当成负例。

**结论：路径成立**，`companion → present(180s) → 超时 → hide(expired=True) → on_expire() → record_outcome("ignored") → timing 当负例`。

### 3.2 我没做的部分（诚实披露）

**我没有做依赖 GUI 的行为验证** —— 没有点过真实气泡，也没有让一个真实气泡超时。上面结论是**纯代码路径阅读**。
替代证据（不是同一件事）：我读了已存在的行为测试 `vista/benchmarks/desktop/test_natural_conversation.py:179` `test_unanswered_opening_is_not_evidence_of_interest`，它断言 brain 的 `conversation_fact` 文案含「没有回应不等于拒绝」—— 说明「沉默≠拒绝」在 **brain 层**早有约束，而当时的**账本层**（`timing._NEGATIVE` 含 `ignored`）与之相矛盾。矛盾是阅读得到的，不是我跑出来的。

---

## 4. 复核 4：回归验证与「224 passed」 —— ⚠️ 224 不可复现；当前 1 failed

命令（统一带上 `--basetemp`，与我自己的临时目录隔离；**原出处用的 `--basetemp E:/OpenLookout/tmp/...` 落在仓库里，我按只读纪律改用 `%TEMP%`**）：

```powershell
cd E:\OpenLookout\src\openlookout
D:\python3.11\python.exe -m pytest vista/benchmarks/desktop sprite/proactive -q --basetemp C:\Users\q\AppData\Local\Temp\olv_verify\bt
```

| 时刻 | 结果 |
|---|---|
| T2 落地前 | `242 passed in 18.86s`（exit 0） |
| T2 测试进来后 | `267 passed` |
| 12:55（T1 正在被写入的中途） | `11 failed, 268 passed`（**瞬时态，文件在变**，不作数） |
| 12:56:44 | `2 failed, 277 passed` |
| 12:57:40 | `1 failed, 278 passed` |
| 12:58:02（harness 稳定、前后哈希一致） | `1 failed, 278 passed` |
| `pytest sprite/proactive -q` 单独（= T1 自己的验收） | **`1 failed, 58 passed`** |

**「224 passed」判定：当前树上不可复现。** 同一类命令现在给 `278 passed / 1 failed`；STATUS.md 那条是**历史快照**（用例集合此后增长了：T2 新增约 25 个、其它约 +18）。这不说明当时那条是假的，但**它不是当前真值**。另注意 STATUS.md 历史条目里 `150/151/149/77/109/20` 的口径各不相同（带不带 basetemp、跑哪个子目录），互相不可直接比较。

**失败归属**：`sprite/proactive/test_outcome_report.py::test_calibration_degrades_when_timing_unimportable`
- 属**改动导致**，不是环境导致：单独跑 `pytest sprite/proactive/test_outcome_report.py -q` → `25 passed`（全过）；一旦同一次运行里也收集到 T1 的 `test_outcome_labels.py` 就失败。
- 顺带：曾经失败过的 `test_systemfacts.py::test_mem_reading_matches_psutil` 单独与复跑均通过 → 瞬时/环境（内存读数波动，STATUS.md:17 记过同类）。

**失败机理（我用自写探针 decisively 复现，`%TEMP%\olv_verify\probe4.py`）**：该测试假定「把 `sys.modules["sprite.proactive.timing"] = None` 就能让 `outcome_report.calibration` 降级」；但 `outcome_report.py` 用的是 `from . import timing as mod`，它解析的是**父包的属性** `sprite.proactive.timing`，而 poison 只挡 `sys.modules`。

```
A) 父包属性尚未绑定 + sys.modules poison
   before: 'timing' in dir(sprite.proactive) = False
   calibration.available = False | status = 校准状态未知      ← 测试期望的行为
B) 先绑定父包属性（= T1 的 test_outcome_labels.py:27 `from sprite.proactive import live, timing` 在 import 期所做的事）
   after : 'timing' in dir(sprite.proactive) = True
   calibration.available = True  | status = 校准状态未知      ← poison 被绕过，断言失败
```

即：**T1 的新测试模块一旦被收集（collection 期就会 import），就永久绑定了父包属性，之后 T2 那个测试的 poison 再也无效**。这也解释了为什么把两个文件顺序对调（先跑 `test_outcome_report.py`）**仍然失败** —— pytest 在跑任何测试之前就已经 import 了参数里列出的全部模块。**生产代码的降级路径本身是好的**（A 情形下 `available=False`，工作正常），坏的只是这个测试的隔离手法。

---

## 5. 复核 5：对抗性误判情形（每条给触发条件 + `file:line`）

1. **任何打字都算 `responded`**：`sprite/proactive/live.py:216`（新行号；before 为同函数）`record_outcome(CURRENT_OFFER.get("offer"), "responded", said=text[:200])` —— 用户回一句**无关内容**也会给当前 offer 记一个正样本（`responded ∈ _POSITIVE`）。
2. **先到者通吃，后到的真信号被静默丢弃**：`sprite/proactive/live.py:453` `if offer_id in _RECORDED: return`（`_RECORDED` 由 `live.py:387 _load_recorded()` 从磁盘恢复，`:455` 落盘）。触发：companion 180s 先超时落 `ignored`，用户在 200s 后才打字 → `responded` 被丢弃。**真实账本就发生过**：11:59:33 那条（用户后来确实说了「清了 Temp…C盘 1.96G→3.04G」）被记成 `ignored`，T2 报告把它标为 `suspected_timeout=true`。
3. **`acknowledged` 两个分母都不进**：`live.py:266` 用户点「好」→ `acknowledged`；而 timing 只数 `accepted/responded/rejected`（after）→ 「看过了」既不算正面也不算负面，无法区分「看见了但不想」与「根本没看见」。
4. **undo 完全不在学习账本里**：`live.py:280` / `live.py:288` 走 `record_offer_result(offer, "undo_requested"/"undone")` 写的是 `offers.jsonl`；`timing` 只读 `outcomes.jsonl`（真实账本 5 行，0 条 undo 类）→ **最强的负反馈（用户撤回）对门槛完全不可见**。
5. **latency 可超过 180s 上限**：真实 `outcomes.jsonl` 第 2 行 `latency_s = 237.191`，而 companion 显示上限是 180s（`gui.py:186-187`）→ 不能把 `ignored` 的 latency 读成「用户有 180s 没回应」，UI 线程/热更新会推迟 `after` 回调。
6. **热更新会重置回应窗口**：`live.py:136-137` `watched_stamp()` 只监听 `sprite/proactive/*.py`、`vista/benchmarks/desktop/*.py`、`sprite/gui.py` 的 mtime；`:167 supervise()` 在变更时 `:193 g.terminate()` 重启 GUI 子进程（今天 12:50:25 / 12:51:09 / 12:51:57 / 12:53:33 共四次）。重启后 `tick()` 会按同一个 offer id 重新 present（`live.py:300-305`），等于**给待回应气泡重置计时**；不产生重复账（按 id 去重），但 latency 失真。
7. **大小写/空白不统一**：T2 的 `classify()` 会 strip+lower（我实测：`'  IGNORED  '` → silence、`'Accepted'` → positive）；而 timing 用原样比对（before 版 `timing.py:134` 附近 `str(row.get("outcome") or "")`）→ 写进账本的 `'Ignored '`/大小写变体会**既不进正例也不进负例**（静默失效）。建议 T1/T2 统一 normalize。**after 版 timing 是否加了 normalize 我未逐行确认**（见第 7 节）。

---

## 6. 复核 6：实机是否被弄坏 —— ✅ 没被弄坏

| 项 | 实测 |
|---|---|
| pid 38316（`pythonw -m sprite.proactive.live --gui`） | **NOT RUNNING**（Lead 给的 pid 已过期） |
| pid 39156（brain） | **ALIVE**，StartTime **2026-10-12 11:38:50**，CPU 113.6s（至今未重启，视觉上下文保留） |
| 当前 GUI 子进程 | pid **12264**（pythonw），StartTime **12:53:33** |
| `supervisor.log` 尾部四条 | 12:50:25 / 12:51:09 / 12:51:57 / 12:53:33 —— 全部是「其它代码变了：只热更新窗口」 |
| 崩溃重启循环 | **无**。最后一条「退出」是今天 **08:54:22**；今晨 08:53:33–08:54:22 有一段 brain 2 秒级重启循环，**早于** T1/T2 的修改 |
| 数据在动 | `decisions.jsonl` / `child_brain.log` / `residual.jsonl` 12:53:41；`operations.jsonl` 12:53:29 |
| 我的操作是否触碰实机 | 否。只读文件 + 用独立解释器跑 pytest/探针；supervisor 只监听 `.py` 的 mtime（`live.py:136-137`），pytest 写的 `.pyc`/`.pytest_cache` 不在监听集合内 |

**一个不能排除的点**：12:53:33 那次 GUI 重启由 `outcome_report.py`（写出时间 12:53:32）触发 —— 也就是说**队友改代码确实动过实机的 GUI 进程**，但那是热更新机制的正常行为，不是崩溃。

---

## 7. 我没能验证的（必读）

1. **依赖 GUI 的行为验证没做**：没点过真实气泡、没让真实气泡超时（见 3.2）。检查 2 的结论只是读码。
2. **T1 在真实账本上的效果没被观察到**：真实 `outcomes.jsonl` 仍是 5 行全 `ignored`（都是 T1 落地前写的，不会被追溯改写）；新路径（companion 超时记 `unanswered`）目前**只有 T1 自己的单元测试覆盖**。真实世界里是否真的改了行为，我无法证明。
3. **没能验证 T1 的测试「在旧代码上会失败」**：按只读纪律我没有把旧文件放回仓库去跑 T1 的测试。我用自写探针在旧/新 timing 上跑同一组合成数据作为替代（before LOOSER/300 → after SAME/60），这**不是**同一件事。
4. **没能验证 T2 的 `--report` 在真实 `perceive/` 目录的行为**：我只在临时目录测了拒绝写入的守卫（`exit=2`，`拒绝写入 perceive/：…\guard\sneaky.md`，`wrote=False`；真实 perceive 目录 5 条记录、无新增文件）。真实目录我一次都没写。
5. **没能独立复核 T1 的完整 diff**：`sprite/proactive/` 不在 git 跟踪内，我没有逐行 diff 工具；我只逐行读了 after 的关键函数并做了行为比对。
6. **12:55 那次「11 failed」的逐条清单没有留存**（输出只留了尾部，且那次是写入中途的瞬时态，已被 12:57/12:58 的稳定两跑取代）。
7. **after 版 timing 的 `normalize` 是否加了、掉进了第 5 节第 7 条的那个 case 没有**，我未逐行确认（我实测的合成数据都是标准小写形态）。
8. **supervisor 对 `vista/benchmarks/desktop/*.py` 与 `sprite/gui.py` 的监听在真实写入时不会误杀 brain** —— 逻辑读过，未做实验。

---

## 8. 给 Lead 的三条（只是证据指向，不是裁决）

1. **STATUS.md 的「224 passed」应更新**为当前真值：`1 failed, 278 passed`，并写明失败测试名（`test_outcome_report.py::test_calibration_degrades_when_timing_unimportable`）。
2. **T1 的验收（`pytest sprite/proactive` 全过）当前未达成**：独立跑得 `1 failed, 58 passed`。失败**归因于跨任务测试污染**（T2 的测试没有在被污染后清理 `sprite.proactive.timing` 的父包属性；T1 的新测试模块 import 时绑定了它）。**最小修法在 T2 侧**，要不要改由 Lead 定。
3. **数据支持不了「开口质量在变好」**：T2 报告的结论是「不能」，`timing.learned_benefit_s` 在真实账本上返回证据不足（0 条有证据）——两者一致，且没有任何当前数据能推翻它。

### 附：原始命令清单（可复跑）

```powershell
# 行数/哈希（不要用 PowerShell 数行）
D:\python3.11\python.exe -c "import hashlib;b=open(r'sprite\proactive\timing.py','rb').read();print(len(b.decode('utf-8').splitlines()), hashlib.sha256(b).hexdigest()[:16])"

# 门槛方向 before/after（我自写的探针，只读 + 只写临时目录）
D:\python3.11\python.exe C:\Users\q\AppData\Local\Temp\olv_verify\probe1.py A_20ignored C:\Users\q\AppData\Local\Temp\olv_verify\out1

# T2 分类/合成/守卫探针
D:\python3.11\python.exe C:\Users\q\AppData\Local\Temp\olv_verify\probe2.py C:\Users\q\AppData\Local\Temp\olv_verify\out2

# 回归
D:\python3.11\python.exe -m pytest vista/benchmarks/desktop sprite/proactive -q --basetemp C:\Users\q\AppData\Local\Temp\olv_verify\bt
D:\python3.11\python.exe -m pytest sprite/proactive -q --basetemp C:\Users\q\AppData\Local\Temp\olv_verify\bt2
```
