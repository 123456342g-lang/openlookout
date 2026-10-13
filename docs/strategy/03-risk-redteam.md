# 03 风险红队：这个项目最可能怎么死

> 立场：本文件的任务不是评价项目好不好，而是**找出它最可能怎么死**，并且每条都要有可验证的证据锚点。
> 采集时间：**2026-10-12 07:25–07:50（Asia/Shanghai）**。采集时项目**正在运行**（brain PID 24344 / GUI pythonw 18088，由 Lead 提供，我未干扰任何进程，未执行任何桌面动作，未修改任何既有文件）。
> 标注约定：**【实测】**= 我本轮亲自跑了命令或读了运行时数据；**【已证实】**= 有可复现的文件/日志锚点；**【未能核实】**= 本会话工具或环境不允许核实，不装懂。

---

## 结论摘要

**一句话**：这个项目现在的死法不是"技术不够强"，而是**它正在被用户悄悄关掉**——因为它平均每 6 分钟说一次话、10-11 那天 147 条提议**没有一条**符合用户明确提出的 60 字要求，且 291 条提议里 283 条什么都没做；同时它**已经在用户的真实桌面上动过手**（79 个文件被移动、272 个文件被移进隔离区），而账本里查不到。

按「可能性 × 杀伤力」排序，最可能致死的五条：

| # | 失败模式 | 可能性 | 杀伤力 | 一句话证据 | 状态 |
|---|---|---|---|---|---|
| **R1** | **打扰 + 旁白化**：开口频率与长度双双失控，且说了不做 | **已发生** | 致命（一次烦到就卸载） | 40 小时 291 条开口；`offer` 类 147/147 全部超 60 字；同一句"要不要清 C 盘"**连发 9 次** | 已证实 |
| **R2** | **不可逆动作 / 误删**：`eval_all` 461/0 是真的，但它**没覆盖真正会动手的那条代码路径**；且真实改动已发生而账本没记 | 已发生（改动已有） | 致命（信任一次性） | `desktop_end_process` 直接 `terminate()+kill()`，不走任何闸门，零对抗用例；`undo.jsonl` 7 条真实改动 vs `offers.jsonl` 只有 1 条 `action≠none` | 已证实 |
| **R3** | **隐私**：全屏逐帧 base64 上传第三方，**零遮挡逻辑**；本地已囤 2,040 张截图 | 高（公开即触发） | 致命（Recall 式事件） | `brain.py:344-350`（**实际运行路径**）；`sprite_home` 下 2,040 张 / 257.3 MB | 已证实 |
| **R4** | **工程腐化**：核心代码不在版本控制里，且在运行中被热更新反复打碎 | 已发生 | 重（项目停止迭代） | `git ls-files` 共 161 个文件，`vista/` 下 **0 个**（22,684 行未入 git）；42 小时里 **brain 被重启 156 次**；395 个 Traceback | 已证实 |
| **R5** | **分发**：现在**不可能有普通用户装上**；而且 AGENTS.md 写的前置条件根本不是实际跑的那条路 | 必然 | 致命（若目标是产品） | 9 步前置、3 个硬卡点；`brain.py:673` 在 Windows 上默认关掉容器 → 前置是错的 | 已证实 |

后面 R6–R9 是次级但真实的死法（磁盘、撤销语义与账本安全、判断质量、文档互相矛盾）。

**三条对路线图有直接影响的判断：**
1. **P0 不是加功能，是加闸门。** R1 是唯一"已发生 + 致命 + 可在一个里程碑内测出改善"的问题。
2. **`eval_all` 的 461/0 不该再被当作安全论据引用**，除非把 `end_process` / `suspend` / `tidy` 补进同一条路径。
3. **必须先把核心代码提交进 git**，否则后面所有工作都建在一份可被一次误删抹掉的代码上——这个事故**已经发生过一次**。

---

## 关于 Lead 卷宗的交叉核对（含两处更正）

我读了 `docs/strategy/05-measured-reality.md` 并逐条独立复算。**大部分一致**，我先说一致的部分，再说我不同意的地方。

**我复算一致的部分：**
- `eval_all` 的 461/0/104/0 —— 我自己跑了一遍，**完全一致**（见 R2）。
- 气泡长度：291 条中位 **121** 字（Lead 记 124，日志在长，口径差 3 字），**≤60 字 40 条 = 13.7%**，与 Lead 完全一致。
- 按天 × kind：10-10 companion 21 / offer 20；10-11 companion 98 / **offer 147**；10-12 companion 3 —— **与 Lead 表格逐格一致**。10-11 `offer` 类 **147 条，0 条 ≤60 字**，中位 137 字 —— 与 Lead 的 "147/147" 完全一致。
- `auto_failed` 36 条：`action` 全为 `none`、`error` 全为 `"returncode:0"` —— 与 Lead 一致，**"80% 失败率" 是假警报，我确认这条更正成立**。
- GUIDE.md 有实质内容（3,283 字节，含用户原话）—— 与 Lead 一致，STATUS.md:102 的自述确实错了。
- 成本量级：我数出 390 个模型段、输入 1,826,828 / 输出 282,733 token（Lead 记 389 / 1,821,155 / 278,637）。差异来自**日志仍在写入**（我采集晚约 20 分钟）。方向一致：**钱不是瓶颈**。

**我不同意 Lead 的两处（我的证据在下面 R2）：**
1. **Lead §3 第 91 行「真正被尝试的自动动作：约 0 条」和「没有发生需要用户干预的损害记录」——这两句不成立。** 系统在用户真实桌面上**确实动过手**：`sprite_home/undo.jsonl` 有 7 条真实记录，`sprite_home/quarantine/restore_map.jsonl` 有 277 条，**272 条仍处于 held、共 201.1 MB、其中 240 条的原始路径已不存在**；另有一次"整理桌面 **79 个文件**"，把 `C:\Users\q\Desktop\1.党组织派人同入党申请人谈话记录表(1).pdf` 这类私人文件移进了 `Desktop\整理\文档\`。正确的结论不是"没动手"，而是**"动了手，但账本没记"**——这反而更严重。
2. **Lead §5 的「单段最大 130.1s」偏低。** 我的快照里最大是 **201.9s**、>30s 的段 **72** 个、累计等待 **8,180s**。同样是日志在长，但意味着**这个数字在恶化**，引用时应当写上采集时刻。

---

## R1（P0）信任 / 打扰 + 旁白化 —— 一次性卸载

**可能性：已发生。杀伤力：致命。** 项目自己的硬规则 3 就是「宁可安静。误打扰比漏提醒代价高」（AGENTS.md:90）——说明这是他们最怕的，而数据说明他们正在做最怕的事。

### 证据（全部【实测】）

| 证据 | 数值 | 锚点 |
|---|---|---|
| 开口总量 | 40 小时内 **291 条** | `sprite_home/perceive/offers.jsonl` |
| 单日峰值 | 10-11 **245 条** → 清醒时段约**每 6 分钟一次开口** | 同上，按 `t` 分桶 |
| 回合级命中率 | `quiet` 152 / `offer` 54 / `companion` 24 → **约 33% 的回合在说话** | `sprite_home/perceive/decisions.jsonl`（226 条） |
| 长度 | 291 条中位 **121 字**，≤60 字仅 **40 条 = 13.7%** | 对 `text` 逐条 `len()` |
| 长度（关键日） | 10-11 `offer` 类 **147 条，0 条 ≤60 字**，中位 137 字 | 同上 |
| 用户原话 | 「**短：单条气泡尽量 60 字上下**（2026-10-11 反馈：'看起来好长看不懂'）」 | `sprite_home/companion/GUIDE.md:13` |
| 用户原话 | 「它一直在说内存的事情，也挺烦的……一直摆到明面上其实不好」 | `GUIDE.md:19` |
| **最狠的一条** | 同一句 `C盘快满了，要我清一下吗？` **连发 9 次**（10-10 19:38:16 → 20:43:58），前 8 次 `shown` 且无回应，第 9 次才 `auto_started` | `offers.jsonl` 文本指纹计数 |
| 项目自述 | STATUS.md:62 只承认「同一句提议连发 **4** 次」——**自述把事故缩小了 2.25 倍** | `STATUS.md:62` |
| 旁白化 | 291 条里 `action=none` **283 条**，`tidy_desktop` 仅 **1** 条 | `offers.jsonl` |

**这三条合起来是同一个死法**：说得太多（每 6 分钟）、说得太长（137 字）、但几乎从来不做任何事（283/291）。用户看到的不是"有用的助手"，而是"一个话很多、还总在说内存的弹窗"。**这是最可能让用户直接右键退出并卸载的路径**，而且它已经发生了 40 小时。

### 未能核实
- 用户是否真的卸载/关闭过：**未能核实**（没有卸载日志、没有进程退出原因记录）。我只知道用户留下了 3 条明确不满原话，且 10-12 之后开口数骤降（10-12 只有 3 条，但样本太短，不能当证据）。

### 最便宜的缓释（一个 milestone 内）
1. **把长度与去重从"提示词"变成"代码闸"**（关键：现在两者都只写在 `profiles.py` 提示词里，模型可以不遵守）。落点：`sprite/proactive/help.py` 的 `publish()` 前加两道硬判：
   - `len(text) > 60` → 要么截断到 60 字后重发，要么强制降级为 `quiet`（**推荐降级**，因为截断会产生半句话，反而更烦）；
   - 同一 `topic` 或同一文本指纹在 24h 内已 `shown` → 直接拦截。**这个闸已经存在**（`help.worth_saying()`，STATUS.md:62 说是为修"连发 4 次"建的），但它显然没拦住 9 次连发——先查它为什么没生效，再谈新代码。
2. **验收（可测、无法造假）**：改完后 `offers.jsonl` 新增行的 `text` 长度 P50 ≤ 60；相同文本指纹重复 = 0；并记一个"被闸门拦截计数"以证明闸门在工作而不是模型恰好安静。
3. **不要**在这条上做 A/B 或攒数据——用户已经用原话把要求写清楚了，再攒数据就是把用户当实验品。

---

## R2（P0）不可逆动作 / 误删 —— `eval_all` 461/0 覆盖到哪、没覆盖到哪

**可能性：已发生。杀伤力：致命（信任不可逆）。**

这条是本报告最需要精确的一条，因为它直接关系到"能不能引用那个 0 误操作"。

### 先给结论
- **`eval_all` 的数字是真的，我复现了**：`python -m sprite.eval_all` → `{"traps":461,"wrongful":0,"wrongful_action_rate":0.0,"positives":104,"missed":0,"missed_rate":0.0}`，exit code 0。**【实测】**
- **但它评的不是"会动手的那条路"。** `eval_all.py:6-11` 导入的是 `sprite.framework / sprite.risk / sprite.scenarios / sprite.quarantine / sprite.sysstate(FakeController)`，全程在 `tempfile.mkdtemp` 沙箱里跑，**不碰真实系统**。
- **真正会改用户机器的工具全部在 `vista/benchmarks/desktop/actions.py`**，而 PRIVATE 主张里那句"同一套闸门跑过 461 个陷阱用例"（`actions.py:7`）**只对其中一个工具成立**。

### 逐工具核对覆盖情况【实测，逐个读代码】

| 模型可调用的工具 | 落点 | 是否走 `sprite.risk` / Engine 闸门 | 是否被 461 覆盖 | 备注 |
|---|---|---|---|---|
| `desktop_reclaim`（清缓存进隔离区） | `actions.py:748-786` | **是**（`R.classify_file`，且动手前逐个重新核对，:766/:775） | **是**（`eval_risk` 的 classify-file 用例计入 461） | 这条我认，覆盖是真的 |
| `desktop_end_process`（**结束进程**） | `actions.py:604-633`，工具表 `actions.py:1062` | **否**。唯一防线是 `_refusal()`（前台进程族 + `DENY_NAMES`），无价值闸、无 dry-run、无校验、无回滚、无信任账本 | **否**。`eval_all` 里没有任何 end_process 用例 | 见下 |
| `desktop_suspend`（挂起进程） | `actions.py:594-601`，`actions.py:1060` | **否**，同上 | 仅通过 `more.hung_cpu`/`resource` 场景间接测了"该不该挂"的**决策**，测的是 `FakeController.suspended`，不是 `actions.suspend` | — |
| `desktop_tidy`（移动桌面文件） | `actions.py:931-972` | **否**。`_tidy_files` 只按后缀白名单 / 隐藏属性 / 最近修改时间过滤，没有任何风险分类器 | **否**（只有 `test_tidy.py` 的单点测试） | 一次真实运行移动了 **79 个**用户文件 |
| `desktop_trim` | `actions.py:819` | 走 `procctl`，需 `SeDebugPrivilege`（`actions.py:808`） | 否 | 4096 字节以下见 `test_trim.py` |

**`end_process` 为什么不只是"覆盖不足"这么简单：**
- `actions.py:625-630`：`p.terminate()`，5 秒不退就 `p.kill()`。撤销方式是 `undo_kind="relaunch"`（`actions.py:617-624`）——**只能重启进程，不能恢复进程里未保存的东西**。而 `GUIDE.md:15` 记录用户的要求是"先做完再汇报"，也就是**不询问直接做**。
- `END_PROCESS` 的保护面就是 `_deny_names()`（来自 `sprite/procctl.py:8-13`，69 个名字）+ `foreground_family()`。**没有**"这个进程有未保存文档吗""它是不是在跑一个长时间任务"这类判断。
- 测试覆盖极薄且有反作用：全 `vista/benchmarks/desktop` 里只有 4 处碰到 `_refusal`/`suspend`/`end_process`，其中 **2 处直接把安全函数 monkeypatch 成永远允许**（`test_help_e2e.py:124`、`test_help_chain.py:113`），注释写的是"只验写入顺序"。也就是说：**没有任何对抗用例在验证 end_process 会拒绝什么**。
- **自我声明的不变量已经被打破**：`sprite/procctl.py:1` 的文档字符串写「真实进程动作：只"挂起/恢复"，**从不结束进程**」，而 `actions.py` 里有 `end_process` 且是模型可见工具。两条线对同一件事的承诺相反。

### 真实改动已经发生过（这是对 Lead 的更正）

**【实测】`sprite_home/undo.jsonl`（7 条）+ `sprite_home/quarantine/restore_map.jsonl`（277 条）：**

| 项 | 数值 |
|---|---|
| 隔离区条目 | **277**（`held` **272**、`restored` **5**） |
| 占用 | 原始大小 **201.1 MB**，隔离区实际 273 个文件 / 201.2 MB |
| **原路径已不存在** | **240 / 272** |
| 来源分布 | `%TEMP%` 86、`Chrome\User Data\Default\Cache` 71、`node-compile-cache\v24.7.0` 59 |
| 分类依据 | 「超过一天的临时文件」206、「浏览器缓存，可再生」71，**全部 `regen=True`** |
| 时间跨度 | 2026-10-10 20:02 → 2026-10-11 22:12 |
| 桌面整理 | `undo.jsonl` 第 1 条：**「整理桌面 79 个文件（只移动）」**，含 `C:\Users\q\Desktop\1.党组织派人同入党申请人谈话记录表(1).pdf` → `C:\Users\q\Desktop\整理\文档\` |

**诚实的两面：**
- 我倾向认为 **272 个隔离文件的分类是站得住的**（Temp >1 天、Chrome 缓存、node 编译缓存，且都走 `classify_file` 且动手前二次核对）。这一批**不构成误删证据**。
- 但 **79 个桌面文件的移动是另一回事**：`tidy` 没有风险分类器，它移的是**用户的私人文件**（入党材料、社会实践报告），判断依据只有"24h 没改过 + 后缀在白名单里"。撤销记录存在，但**用户如果不点撤销，文件就不在原处**。
- **账本对不上，这才是最严重的部分**：同期 `offers.jsonl` 里 `action != none` 只有 **1 条**（`tidy_desktop`），283 条是 `none`。也就是说 —— **"每次动手都记账"这个信任承诺没有实现**。出了事，你无法从账本回答"小精灵到底动过我什么"。
- `undo.jsonl` 每行**没有时间戳**（keys 只有 `cwd/desc/moves/undo_cmd/undo_kind`），**无法把一次改动对到用户当时的哪句不满**。

### 未能核实
- 272 个被隔离文件中有多少是用户真正需要的：**未能核实**（我不会去读取用户 Temp/Chrome 缓存的原始内容，也没有用户申诉记录）。
- `end_process` 被模型真实调用过的次数：**未能核实**（`offers.jsonl` 的 `action` 字段只出现过 `tidy_desktop`，不足以证明 end_process 从未被调用——恰恰说明账本不可信）。

### 最便宜的缓释（一个 milestone 内）
1. **一行改动先把最大的洞堵上**：把 `desktop_end_process` 从工具表（`actions.py:1062`）移除。理由：它提供的价值（结束一个后台进程）远小于它的最坏结果（用户丢掉未保存的工作），而 `desktop_suspend`（可恢复）已经覆盖了"省内存"这个真实需求。**删一个工具，风险归零，零新代码。**
2. **给账本补两件事**（这是所有后续安全工作的前提）：`undo.jsonl` 每行加 `ts` + `task_id`；`actions.py` 每次真实改动同时写一行到 `decisions.jsonl`，让 `offers.jsonl` 的 `action` 字段反映真实动作。验收：随机取一次真实动作，能从 `offers.jsonl → undo.jsonl → 文件系统` 三点对齐。
3. **给 `tidy` 接上已有的分类器**（`sprite.risk.classify_file` 已经存在且被 461 条用例覆盖）：桌面上"个人文档类"文件默认不自动移动，只建议。验收：`tidy` 在含 `.pdf/.doc/.docx` 的测试桌面上必须不动手。
4. **别再用 461/0 当作安全背书**，除非 1-3 做完并把 `end_process`/`suspend`/`tidy` 纳入同一条评测路径。

---

## R3（P1）隐私 —— 全屏逐帧上传第三方，零遮挡

**可能性：高（一旦公开即触发）。杀伤力：致命（公关型死亡，参考 Recall 类事件）。**

### 证据（全部【实测】）

| 证据 | 锚点 |
|---|---|
| **实际运行路径**把每一帧 base64 塞进请求体 | `brain.py:344-350`（`VisualDirectBackend._append_input`）：`for image in task_input.observation.images(): ... {"type":"image","source":{"type":"base64","media_type":...,"data":...}}` |
| 容器路径同样 | `vista/backends/claude/runner.py:1302-1309`：`"data": base64.b64encode(path.read_bytes())` |
| 落盘的截图 | `sprite_home` 下 **2,040 张**（png/jpg），**257.3 MB**，10-10 13:19 → 10-12 07:28；`perceive/frames/` 里单张 81 KB 全屏 jpg |
| 帧率量级 | 约 **48 张/小时**（2040 张 / 42.1 小时） |
| 模型端 | `sprite/proactive/provider.json` → `base_url: https://token-plan-cn.xiaomimimo.com/anthropic`，`model: mimo-v2.6-flash`（**第三方、境内**端点） |
| **零遮挡** | 对 `vista/benchmarks/desktop/` 与 `vista/backends/claude/` 全目录 grep `password|隐私|privacy|redact|遮挡|敏感`：**只命中** tool 文案（"不读取密码/Cookie/剪贴板正文"）与 URL 校验（`actions.py:255` 检查 `parsed.password`）。**没有任何**按窗口标题/进程屏蔽、没有暂停录屏、没有敏感页黑名单。 |
| 一条真实的缓解（值得肯定） | 剪贴板**正文不入库**：`perceive/operations.jsonl` 的 3 条 clipboard 记录只有 `src_app/src_title/len/hash/dst_app/dst_title`，无 `text`。有回归测试守着（`test_historyfacts.py:69-87`） |
| 但元数据仍在泄 | `src_title` 记录了上下文，例如 `"src_app":"cc-switch"`、`"src_title":"用户询问openocde的go订阅对应的API地址 - Tabbit"` —— 而 cc-switch 正是用户**复制 API key** 的地方。（`len` + 12 位 hash 对短密钥构成一个弱确认预言机，值得留意但非高危） |

**Recall 式的舆论反弹这个外部事实：未能核实。** 本会话 `web_search` 无凭证、`web_fetch` 被网络策略拒绝（`support.microsoft.com` 解析到非公网地址），所以**我不引用任何外部报道**。上面全部结论都只用本机证据，已经足够支撑"逐帧外传 + 无遮挡"这个判断。

### 最便宜的缓释（一个 milestone 内）
1. **加一个"暂停观察"开关**（托盘/气泡右键），不解释、不弹窗，一键生效。这是信任的第一道保险：用户至少能随时闭眼。
2. **前台进程/窗口标题黑名单**：取帧处（`brain.py` 组装 observation 的地方）已有前台进程信息——密码管理器、银行、`cc-switch` 这类 key 管理工具进入前台时**跳过该帧**。落点极小，不需要新框架。
3. **首启显式同意页**，一句话写明"你的屏幕画面会逐帧发送到 `<provider.json 里的 base_url>`"，并要求勾选。现在的行为是**默认开启且无告知**。
4. **本地截图保留上限**（见 R6）：默认只留 N 小时，否则 2,040 张截图本身就是一份本地隐私档案。

---

## R4（P1）工程可持续性 —— 核心代码不在 git 里，且在运行中被热更新打碎

**可能性：已发生。杀伤力：重（项目会静静停止迭代）。**

### 证据（全部【实测】）

| 证据 | 数值 / 锚点 |
|---|---|
| 提交数 | `git rev-list --count HEAD` = **6** |
| 被跟踪文件 | `git ls-files` 共 **161** 个（`src/openlookout` 下 153 个） |
| **VISTA fork 被跟踪文件数** | `git ls-files src/openlookout/vista` = **0** |
| 未入 git 的体量 | `vista/` = **115 个 .py / 22,684 行**，包含 `brain.py`、`actions.py`、`profiles.py`、`session.py` —— **安全最关键的那些文件全都不在版本控制里** |
| 不是 submodule | 全仓只有两个 `.git`：根目录和 `third_party/rea/.git`；`vista/` 下**没有** `.git` → 这是一份**没有上游历史的拷贝**，无法 `git pull` 吃上游更新 |
| 未跟踪条目 | `git status --porcelain -unormal` = **116** 项 |
| **已经发生过的事故** | `STATUS.md:63`：「中断中误删 `vista/benchmarks/desktop/reading.py`，该文件**从未入 git、无法恢复**」 |
| **热更新打碎核心前提** | `sprite_home/perceive/supervisor.log`：41.7 小时里 **「重启 brain」156 次**（平均每 **16 分钟**一次）、「只热更新窗口」231 次、涉及子进程退出 471 行。日志原文自己写着：「brain 代码变了：重启 brain（**视觉上下文会重来，这是必要代价**）」 |
| 崩溃密度 | `perceive/child_brain.log`（6,960 行）：**395 个 `Traceback`**；异常类型 AttributeError 107 / SyntaxError 88 / ImportError 82 / ValueError 79 / NameError 36 |
| 为什么 SyntaxError 这么关键 | 语法错误只可能来自**热更新忠实加载了一份写坏的活文件** —— 这直接证明"多 agent 边跑边改"是会真炸的 |
| 重复副本且**已经漂移** | `src/openlookout/sprite/` vs `src/openlookout/sprite/sprite/`：59 个同名文件，**2 个内容不一致**（`gui.py`、`procctl.py`）。`procctl.py` 的差异正是安全相关的 `DENY_NAMES`：外层（**当前被 import 的那份**）有 `vmmem`、`vmmemwsl`，内层**没有**。另有第三份 `_bak_20261010_081350/`。 |
| import 归属（实测） | `python -c "import sprite.procctl"` → `E:\OpenLookout\src\openlookout\sprite\procctl.py`（外层）→ **内层是"更弱的安全名单 + 死代码"** |

**这两件事叠起来是这个项目最安静的死亡方式**：产品定义是"持续视觉上下文"（AGENTS.md:24「视觉上下文由 VISTA 管」），而开发期每 16 分钟就把它清空一次；同时承载这个能力的那 22,684 行代码**一份备份都没有**（唯一的备份是那份已经漂移的 `_bak_` 和 `sprite/sprite/`）。

### 未能核实
- VISTA fork 相对上游 `joshhhhhan/VISTA` 改了多少：**未能核实**（无上游 remote、无网络搜索能力）。`AGENTS.md:79-84` 自述 Windows 适配改在 `backends/claude/{runner,mcp_host,mcp_bridge,provider}.py`，**这 4 个文件正是最需要避免手工合并冲突的地方**。

### 最便宜的缓释（一个 milestone 内）
1. **把 `vista/benchmarks/desktop/` 与 `vista/backends/claude/` 提交进 git。** 这是全项目**最高性价比的一次改动**：零行为变更、零架构讨论，直接把"下一次误删就永久丢失"变成"`git checkout` 就回来"。在做任何其它重构之前做。
2. **收敛重复副本**：删掉 `src/openlookout/sprite/sprite/` 与 `_bak_20261010_081350/`（或移出工作树），保证 `procctl.py` 只有一份。否则早晚有人改错那一份——而且改的是**没有 vmmem 保护**的那份。
3. **给热更新加一道语法闸**：`live.py` 在重启前对改动文件做一次 `compile()`，失败就**拒绝加载并告警**（现在的行为是加载坏代码然后崩溃-重启循环）。这一条能直接消掉 88 个 SyntaxError。
4. **把"brain 重启次数"做成看板指标**：它是"持续视觉上下文"这个核心主张的直接反面指标，现在被当作"必要代价"默默接受了 156 次。

---

## R5（P1）分发 —— 现在不可能有普通用户装上；而且 AGENTS.md 的前置条件是错的

**可能性：必然。杀伤力：致命（如果目标是"产品"而不是"我自己的工具"）。**

### 先更正 AGENTS.md：那条前置条件描述的不是实际跑的路径

- `AGENTS.md:66` 写「前置：Windows、**Docker Desktop 已运行**、Python 3.11」；`AGENTS.md:74-77` 要求构建 `arc3-claude-player:0.1` 镜像并把 **Linux 版 Claude Code 2.1.220** 放到 `sprite_home/bin/`。
- **但默认运行路径把它们全绕过了**：`brain.py:673-674` —— `if os.name == "nt" and os.environ.get("OPENLOOKOUT_NATIVE_CLAUDE") != "1": print("Windows 使用 VISTA 视觉直连 runtime（设置 OPENLOOKOUT_NATIVE_CLAUDE=1 才启用容器）")`。
- **日志证实**：`perceive/child_brain.log` 里有 **163 行**这条"直连 runtime"声明。也就是说，正在跑的是 `VisualDirectBackend`（直连 Anthropic 兼容 HTTP），**不是 AGENTS.md 架构图里那条 Docker + Claude Code 容器**。
- 容器路径**确实在崩**，只是被静默吞掉：**14 次**「容器通道不可用（`TypeError: run_runtime_preflight() got an unexpected keyword argument 'binary'`），改走直连模型」。根因是接口漂移：`brain.py:685` 用 `binary=` 调用，而 `preflight.py:34` 的形参名是 `claude_bin`。异常被 `brain.py:693-695` 的 `except Exception` 捕获并降级。
- **对分发的含义（好消息）**：Docker Desktop 与那 262 MB 二进制**在默认路径下不是必需的**。把默认路径定为唯一路径，前置条件可以从"离谱"降到"普通"。

### 普通用户实际要走的步数【实测，来自 AGENTS.md:66-77 + 我核对的代码硬约束】

| # | 步骤 | 普通用户能过吗 | 卡点性质 |
|---|---|---|---|
| 1 | Windows 10/11 | 能 | — |
| 2 | 装 Python 3.11 并进 PATH | 勉强 | 有向导，但"python"命令容易装到 Store 假货 |
| 3 | ~~装 Docker Desktop + WSL2 + 虚拟化 + 管理员 + 重启~~ | **多数不能** | **管理员权限 + BIOS 虚拟化 + 重启**；好在这步**可删** |
| 4 | `docker build -f vista/Dockerfile.claude-player -t arc3-claude-player:0.1 vista` | 不能 | 需上一步；镜像 165 MB（实测 `docker images`） |
| 5 | 在 WSL 里跑官方脚本装 Claude Code，**再**把 Linux 二进制拷到 `sprite_home/bin/claude-linux-2.1.220` | **不能** | 需要会用 WSL、知道去哪儿找二进制、还要**恰好 2.1.220 版** |
| 6 | 版本必须精确匹配 | **不能** | `runner.py:46-48` `PINNED_CLAUDE_VERSION = "2.1.220"`；`runner.py:216-218` 版本不等直接 `raise`。用户今天装到的一定不是 2.1.220 |
| 7 | 复制 `provider.example.json` → `provider.json`，手填 `base_url` / `protocol` / `model` | 不能 | 需要知道"Anthropic 兼容端点"是什么 |
| 8 | 复制 `.env.example` → `.env`，填 `SPRITE_API_KEY` | 不能 | 需要一个**已付费**的兼容端点账号（本机用的是小米 MiMo） |
| 9 | `python -m sprite.proactive.live` | 勉强 | 没有安装器、没有快捷方式 |

**合计 9 步，其中 3 个硬卡点**：第 3 步（若保留容器路径）、第 5-6 步（特定版本 Linux 二进制，项目**明确不分发**——`AGENTS.md:76`）、第 7-8 步（自备付费兼容端点 + 手编 JSON）。

### 我判断的流失点顺序（这是本条的核心产出）
1. **第 5 步（WSL 里装 Claude Code 再拷出 262 MB 二进制）—— 这里流失 >90%。** 这不是"难"，这是**只有开发者本人会做的事**；而且因为 `PINNED_CLAUDE_VERSION`，就算照做也可能因版本不对而硬失败。**本机那份二进制是 262.3 MB（`sprite_home/bin/claude-linux-2.1.220`），且因许可大概率不能随包分发。**
2. **第 7-8 步（自备 Anthropic 兼容端点 + key）—— 这里流失剩下的绝大多数。** 桌面小精灵的用户不会为了一个"桌面摆件"去开一个 API 账号。这是**商业模式问题**，不是工程问题。
3. **第 3 步（Docker Desktop）—— 如果保留容器路径，这里先流失掉一大半；但这一步可以被删掉，是最高性价比的分发简化。**

### 其它分发相关证据
- **没有任何打包产物**：全仓找不到 `pyproject.toml` / `setup.py` / `*.spec` / `*.iss` / `*.msix`（只有 demo 用的 `.bat`）。也就是说，**"分发"这件事从来没有被开始过**，不是"做得不够好"。
- **没有项目自己的 LICENSE**：根目录无 LICENSE/COPYING（只有 `vista/LICENSE.txt` 的 MIT，属第三方）。默认"保留所有权利"→ 法律上**不能分发**。同时 MIT 要求保留 VISTA 版权声明（这一点目前做到了）。
- **未签名 exe / 杀软误报：未能核实。** 本机从未构建过 exe，我无法实测 SmartScreen 或杀软行为，所以**不给结论**。可核实的相关事实（供后续验证方向）：这个程序会 `NtSuspendProcess` 挂起其它进程（`procctl.py:2`）、写 HKCU/HKLM Run 值、改通知设置、`p.terminate()/kill()` 进程、并要求 `SeDebugPrivilege`（`actions.py:808`）——**这些都是行为检测的敏感项**，我判断误报概率偏高，但这是判断不是证据。

### 最便宜的缓释（一个里程碑内）
1. **把 AGENTS.md 的前置条件按 `brain.py:673` 的真实分支重写**：默认路径 = "Windows + Python 3.11 + 一个 Anthropic 兼容端点"，Docker/二进制降级为"可选的高级路径"。半天工作量，直接把 9 步砍到 5 步。
2. **把 `PINNED_CLAUDE_VERSION` 的硬 `raise` 改成"警告 + 继续尝试"**（`runner.py:216-218`），并只在容器路径用它。一条改动。
3. **PyInstaller 出单 exe**：先接受"未签名 + SmartScreen 警告"，在 README 里明确写"点'更多信息'→'仍要运行'"。比追求签名便宜一个数量级。
4. **首启向导代替手编 `provider.json` / `.env`**：两个输入框（端点、key）。

---

## R6（P2）磁盘与运行时数据没有上限 —— 而且本项目已经因此出过事

**可能性：已发生。杀伤力：中重（表现为"莫名其妙的测试失败/功能报错"）。**

| 证据 | 数值 |
|---|---|
| `E:\OpenLookout\tmp_inv` | **6,430 MB** —— 两个残留 demo 沙箱 `sprite_demo_dqydvsgi` / `sprite_demo_f9qagf0u`，**各 3,215 MB**，里面各含 3 个 700 MB 的 `.bin` 和 80 MB 的 `.exe` |
| **且未被 gitignore** | `git check-ignore -v tmp_inv` → **空**（`sprite_home/` 在 `.gitignore:22` 里，`tmp_inv/` 不在） |
| `sprite_home` 总量 | **1,224 MB** |
| 42 小时的产出 | `companion/runs` 381 个目录 **655.8 MB** + 截图 **257.3 MB** + 隔离区 **201.2 MB** → 约 **29 MB/小时 ≈ 700 MB/天** |
| 无清理策略 | `companion/runs` 没有任何保留上限或轮转；截图同理 |
| **历史事故（项目自己的记录）** | `AGENTS.md:107`：「C 盘仅剩 ~29MB，`sprite/` 大量测试因 `could not create`（磁盘满）失败/报错」；`TASKS.md:113`：「其余失败/错误全部为并行代理写满磁盘（Errno 28 / could not create numbered dir）」 |
| 本机现状 | C: **8.02 GB** free / 已用 141.29 GB（E: 96.09 GB free） |

**为什么这条值得单列**：磁盘满是唯一一种"看起来像别的问题"的故障——它表现为随机测试失败、随机写入异常，会**浪费大量调试时间**。这个项目已经因此浪费过一轮（见上）。

**缓释（一个 milestone 内）**：① `tmp_inv` 删掉并加进 `.gitignore`（立刻回收 6.4 GB）；② `companion/runs` 保留最近 N 个 + 启动时清理（一个函数）；③ 启动时检查剩余空间，< 2 GB 就停止截屏与观察（现在**完全没有这个闸**）；④ 截图降采样（现在每张 60-165 KB）。

---

## R7（P2）撤销语义错误 + 撤销日志是可执行命令文件

**可能性：中（需要本地写权限）。杀伤力：重。** 这条是代码审计发现的，不是从日志推的。

| 问题 | 锚点 |
|---|---|
| **工具描述与实现不符**：`desktop_undo` 声称"还原**本次任务**中所有已记录的操作"，但实现读**整个** journal 并全部回放 | 描述 `actions.py:1073`；实现 `actions.py:639-642`（`rows = 全部行`，`for r in reversed(rows)`），最后把**整个** journal 改名 `.done`（`actions.py:681`） |
| 后果 | 点一次"撤销"会回放历史上**所有**动作——包括 272 个隔离文件的恢复和 79 个桌面文件的搬回。用户以为在撤销刚才那一下，实际触发一次全局回滚 |
| **journal 里的自由字符串被 shell 执行** | `actions.py:672-679`：`subprocess.run(r["undo_cmd"], shell=True)` / `subprocess.Popen(r["undo_cmd"], shell=True, ...)`。→ **谁能写 `sprite_home/undo.jsonl`，谁就能在用户点"撤销"时执行任意命令** |
| 可能被提权 | `actions.py:808` 使用 `SeDebugPrivilege` → 若以管理员运行，上述执行即提权执行 |

**缓释（一个 milestone 内）**：① `undo` 只处理**最近一次任务**（journal 行加 `task_id`，撤销只匹配最后一批）+ 未匹配的保留；② `undo_cmd` 改成**枚举式白名单**（只允许 `desktop_tidy` / `restore_quarantine` / `resume` 三个已知 kind），**拒绝一切自由字符串**。这两条同时消灭"误回滚"和"命令注入"。

---

## R8（P2）判断质量 —— 时机没有基准，画像写了但不管用，数字反复报错

**可能性：已发生。杀伤力：重（这是 R1 的根因）。**

| 项 | 状态 | 证据 |
|---|---|---|
| 接受率**无法计算** | 已证实 | `feedback.jsonl` 仅 **8 行**（多为"你好"，跨度 10-10 13:45 → 10-11 16:04）；291 条提议 / 8 条反馈。`offers.jsonl` 里没有"点了不用"的字段 |
| 开口决策分布 | 已证实 | `decisions.jsonl` 226 条：`quiet` **152**、`offer` **54**、`companion` **24**（我算 152/54/24；Lead 记 151/51/24，差异来自日志在长） |
| **GUIDE.md 不是空的（更正 STATUS.md）** | 已证实 | `sprite_home/companion/GUIDE.md` = **3,283 字节**，10-12 07:18 写入，含用户原话 7 条。**`STATUS.md:102` 自述"仍是初始值"与事实不符** |
| 画像**没有约束行为** | 已证实 | 60 字要求写进 GUIDE 之后，10-11 `offer` 类 **147/147 全部超 60 字**；10-12 三条新气泡中位仍 87 字 |
| 模型**反复报错数字** | 已证实 | `GUIDE.md:16` 记着用户曾经纠正「'C 盘剩 0.6G' 是错的（实际约 11G）」；而 10-11 10:33:11 的 offer 仍写「C 盘要跌破 5G 了（5.79，几分钟掉 1.7G）」 |
| 模型**说的多是自己做不到的事** | 已证实 | 9 条 `auto_completed` 全是关于用户自己的 Codex/Clash/API key 配置的**建议**（`action=none`）——它在评论用户的屏幕，而不是帮忙 |

**"文档自述不可信"本身就是一条独立风险**：`STATUS.md` 至少有两处与运行时不符（GUIDE.md 为空、连发 4 次）。任何依赖 STATUS.md 做判断的路线图都会走偏。

**缓释（一个 milestone 内）**：① 加**数字闸**：气泡里出现 GB/%/进程名时，必须能在同轮工具返回里找到出处，否则降级为 `companion` 或 `quiet`（可以纯代码实现，复用现有工具返回）；② `offers.jsonl` 增加 `accepted / rejected / ignored_by_timeout` 三态（GUI 已有按钮，落库即可）→ 接受率从第一天起可算；③ 把 `STATUS.md` 里已被推翻的自述删掉，只留**可复现命令 + 采集时间**。

---

## R9（P2）两份文档描述两个不同的产品 —— 路线图会按错的文档做取舍

**可能性：高。杀伤力：中（会直接引爆 R1/R2）。**

| 文档 | 它描述的产品 |
|---|---|
| `AGENTS.md:9,48-56` | 常驻看屏幕 → 模型判断 → **开口提议 → 用户点"好的"才动手** |
| `docs/PROACTIVE_AGENT.md:9` | 「**不是"LLM 一直盯着屏幕"**：那样每天几十万 token；它的绝大部分判断是本地代码，成本趋近于零」 |
| `docs/PROACTIVE_AGENT.md:3,12,25-28` | 「能做的**全部直接做**」、「**没有提问流程**」、「不可逆、高风险、拿不准**不做也不问**」 |
| 现实（Lead §2 + 我的复核） | **283/291 条 `action=none`** —— 一个会评论的旁白助手 |

也就是说：**仓库里有三个互不相同的产品定义，且没有任何一处说明哪个是当前的。** `PROACTIVE_AGENT.md:26/56` 的"354 / ≥300 陷阱 0 误操作"和 `STATUS.md`/`TASKS.md` 的 461 都是**另一条代码线（`sprite/`）的数字**，不是正在跑的 VISTA 线的数字（见 R2）。

**这条为什么有杀伤力**：如果路线图采纳 `PROACTIVE_AGENT.md` 的"直接做、不要问"，就会把 R1（打扰）和 R2（不可逆）同时引爆——因为它要求系统在**没有用户确认**的前提下动手。

**缓释（零代码，半天）**：一份文档只留一条线。把 `PROACTIVE_AGENT.md` 标注为"历史设计（未接入当前运行路径）"，把 `AGENTS.md` 的架构图按 `brain.py:673-674` 的真实分支重画（直连 vs 容器），并在两份文档里各写一行"本文档对应的代码入口 + 采集时间"。

---

## 如果只能保留一条红线

**保留这一条：**

> **在"这句话值不值得说"这件事上，模型不得拥有最终裁定权——必须由代码用可测的数字先否决，模型只能在通过闸门后决定说什么。**

理由（按重要性）：

1. **它对准的是唯一一个已经发生、且会直接导致卸载的失败模式。** 每 6 分钟一次、中位 121 字、`offer` 类 147/147 全部违规、同一句连发 9 次——这些都不是推测。
2. **它是唯一一条"用户已经把验收标准写在纸上"的要求。** `GUIDE.md:13`「短：单条气泡尽量 60 字上下」，`GUIDE.md:20`「不要给自己设次数、间隔、配额……标准是这句话值不值得说」。用户已经说清楚了他要什么，项目却没做到——这是**执行问题，不是产品方向问题**，所以一条红线应该落在这里。
3. **它可测、不会自欺。** 气泡长度 P50、重复文本条数、拦截计数——都是 `offers.jsonl` 一跑就出来的数字。相比之下"时机质量"在拿到接受率之前根本无法证伪（R8），"安全"在没有把 `end_process` 纳入评测之前无法声称（R2）。
4. **它同时缓解另外两条**：强制 60 字 + 去重会显著降低开口量和每次的信息密度，从而降低"打扰"；而"必须有具体帮助才允许开口"（`GUIDE.md:18`）会自然减少"旁白化"，因为**没有真实证据时它只能选择 quiet**。

**这条红线对应的最小实现（明确边界，防止它变成又一个提示词）**：
- 落点是 `sprite/proactive/help.py` 的 `publish()`，**在模型输出之后、写 `offer.json` 之前**；
- 三个否决条件是**硬编码**的：`len(text) > 60` → 丢弃或降级；同 topic/指纹 24h 内已出现 → 丢弃；本轮无工具证据且无具体帮助 → 降级为 `quiet`；
- **每次否决都计数落库**（否则你无法区分"闸门有效"和"模型恰好安静"）；
- 验收：`offers.jsonl` 新增行 P50 ≤ 60 字、重复文本 = 0、`决策分布 quiet 占比上升`。

**反面建议**：不要把这轮工作花在 `PROACTIVE_AGENT.md` 描述的"直接做、不要问"上。那会同时踩响 R1 和 R2，而这两个恰好是仅有的、已经有真实数据证明在流血的地方。

---

## 附：本报告的证据来源与复核命令

以下命令全部**只读**，在本机实测通过（采集时间 2026-10-12 07:25–07:50）：

```powershell
# R2：复现 eval_all（沙箱内运行，用 tempfile，不碰真实系统；实测 exit 0）
cd E:\OpenLookout\src\openlookout; python -m sprite.eval_all
# => {"traps": 461, "wrongful": 0, "wrongful_action_rate": 0.0, "positives": 104, "missed": 0}

# R1/R8：气泡长度与重复文本（用 python 读 utf-8，不要用 Get-Content，会乱码）
# R2：真实改动与隔离区
#   sprite_home/undo.jsonl  -> 7 条（含"整理桌面 79 个文件"）
#   sprite_home/quarantine/restore_map.jsonl -> 277 条，held 272，原始路径已消失 240

# R3：截图规模
Get-ChildItem E:\OpenLookout\sprite_home -Recurse -File -Include *.png,*.jpg | Measure-Object Length -Sum
# => 2,040 个 / 257.3 MB

# R4：版本控制覆盖面
cd E:\OpenLookout; git rev-list --count HEAD; git ls-files | Measure-Object
git ls-files src/openlookout/vista      # => 0
Get-ChildItem -Recurse -Directory -Force -Filter .git   # => 只有根目录与 third_party/rea

# R4：热更新打碎视觉上下文
#   perceive/supervisor.log -> "重启 brain" 156 次（13:38:59 → 07:21:05，41.7 小时）

# R5：默认路径不是容器
#   perceive/child_brain.log -> 163 行「Windows 使用 VISTA 视觉直连 runtime」
#   brain.py:673-674 / preflight.py:34 vs brain.py:685

# R6：磁盘
Get-ChildItem E:\OpenLookout\tmp_inv -Recurse -File | Measure-Object Length -Sum   # => 6,430 MB
git check-ignore -v tmp_inv                                                        # => 空（未被忽略）
Get-PSDrive C,E
```

**数据边界**：全部为单机、单次采集；项目此刻正在运行，`offers.jsonl` / `child_brain.log` / `supervisor.log` 仍在增长，因此涉及计数的数字（token、段数、Traceback、重启次数）都会随采集时刻漂移。与 Lead 卷宗（`05-measured-reality.md`，07:19–07:30 采集）的差异均属此类，**已在正文逐处标注**。

**本次调查遵守的约束**：未修改 `E:\OpenLookout` 下任何既有文件（本文件为新建）；未执行 `git add/commit/checkout`；未启动 `live.py` / `brain.py` / GUI；未执行任何桌面动作（未挂起进程、未改注册表、未删/移任何文件）；未读取或打印任何密钥值（`provider.json` 输出时已脱敏为 `***`）；命令均为只读。
