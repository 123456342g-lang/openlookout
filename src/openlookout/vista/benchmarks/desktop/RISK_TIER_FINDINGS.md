# 取证：`desktop_write_deliverable` 的路径约束是真的，那次改动是谁干的

## 问题

2026-10-13 精灵改了 `E:\知识产物(必保存)\程序分析\POC构造\v8-audit\HANDOFF-REMOTE-RCE.md`。
该文件既不在 `sprite_home/deliverables` 里，也不在精灵任何工具的写入范围内。
任务简报因此问：`desktop_write_deliverable` 描述里写的「只在 deliverables 目录新建，
不覆盖用户文件」，**核实这个约束在代码里是真的还是只是描述**。

如果约束是真的，说明**有别的路径绕过去了** —— 那比分级本身更重要。

## 结论

**约束是真的，而且是三重的。** 出问题的是别的路径。

## 一、约束为真的证据

`actions.py:118-138`，实测（隔离 `SPRITE_HOME`，见 `test_deliverable_constraint.py`）：

| 攻击输入 | 结果 |
|---|---|
| `../HANDOFF-REMOTE-RCE.md` | 拒绝 |
| `..\HANDOFF-REMOTE-RCE.md` | 拒绝 |
| `sub/dir.md` / `sub\dir.md` | 拒绝 |
| `C:/Windows/x.md` | 拒绝 |
| `../../../../knowledge/x.md` | 拒绝 |
| `a.exe` / `a.ps1` / `a.bat` / `noext` | 拒绝 |
| 已存在的同名交付物 | 拒绝（不覆盖） |

三重保障：
1. `Path(name).name != name or any(char in name for char in '/\\:')` → 必须是裸文件名
2. `Path(name).suffix.lower() not in {".md", ".txt", ".csv"}` → 后缀白名单
3. `path.open("xb")` → 独占新建，同名即失败

**精灵不可能用这个工具写到 deliverables 之外的任何地方。**

## 二、真正的那条路径：宿主 Claude Code 的 Edit

`sprite_home/companion/runs/20261013-135536/transport/state/projects/.../b07a18a3-*.jsonl`
里，动作序列是：

```
05:59:35  mcp__game__desktop_read_local {"path": "...\\v8-audit\\HANDOFF-REMOTE-RCE.md"}
05:59:46  Read        {"file_path": "...\\HANDOFF-REMOTE-RCE.md", "limit": 40, "offset": 60}
05:59:51  Read        {"file_path": "...\\HANDOFF-REMOTE-RCE.md", "limit": 80, "offset": 155}
05:59:59  Edit        {"file_path": "...\\HANDOFF-REMOTE-RCE.md",
                       "old_string": "2. **先做 A1**（WasmCustomMap / JSToWasmObject）...",
                       "new_string": "2. **A1 已于 09-28 做完 → 首环①不成立，别再跑**..."}
06:00:03  Edit        {... 同一文件 ...}
06:00:04  Edit        {...}
06:00:09  Edit        {...}
06:00:09  Edit        {...}
06:00:13  Edit        {...}
06:00:17  Edit        {"file_path": "...\\findings\\FINDINGS.md", ...}
```

是 **`Edit` 工具**，不是本项目的任何 `desktop_*` 工具。

`companion` 子系统跑的是**完整的宿主 Claude Code CLI**，自带 Read/Edit/Write/Bash。
它不是 `vista.benchmarks.desktop` 的工具集，因此：
- 不经过 `session.py:_handler`（本项目的闸门挂在这里）
- 不经过 `permissions.json`
- 不写 `undo.jsonl`
- 不产生任何 offer / outcome 记录

精灵自己的判断在那次会话里写得很清楚：
> 「直接改 HANDOFF/FINDINGS 里过时的状态行」「证据：REPORT-REGISTRY 载 F3 官方已回复 S2」

它是**有意为之**的，而且当时的判断在事实上没错（那些状态行确实过时了）。
问题不是判断错，是**这条路径上没有任何东西要求它先问**。

## 三、结构性问题（比这次改动严重）

`fix/offer-consent` 的注释自己承认了这件事：

> 代价见交付说明：brain 那条路本来就不经过 offer，同意门管不到它。

现在三级闸门同样挂在 `_handler`，所以**同样管不到 companion**。
更根本的是：只要精灵能起一个带完整 Edit 的 Claude Code 会话，
任何「按风险分级」在工具分发处的设计都会被绕过 —— 分级只对**声明式工具**有效，
对**通用代码编辑能力**无效。

要真正封住，得给 companion 那一路也套上等价约束（例如限制可写目录、
或让它的写操作同样落 undo 台账 + 经闸门）。那是另一个改动，
不在本次「把 offer 授权改成按风险分级」的范围内，但必须记在这里。

## 四、顺带确认的两件事

- `basic_shell`（任意 shell，4000 字符）默认**已禁用**：
  `actions.py:621` 要求 `OPENLOOKOUT_ENABLE_CONTROLLED_SHELL=1` 才放行。
  上一轮已加这道闸，本轮复核确认有效。所以「shell 绕过一切」目前**不成立** ——
  但它仍被列为高风险，因为一旦那个环境变量被打开，它就是最大的口子。
- `desktop_reclaim` 一次收走 4959 个文件 / 3.8GB 的历史确实存在
  （`desktop_runs/20261011-073031`，见 `test_offer_consent.py` 开头引述）。
