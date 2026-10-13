# 协作看板（认领 / 进行中 / 已完成）

- 2026-10-12 GPT-6.1 Sol privacy_trial：已完成非生产隐私设计与合成验收，范围 docs/superpowers/specs/2026-10-12-context-egress-design.md、docs/experiments/privacy_trial/；三例本地算术/关联验证通过，证明凭据标注移除保持数据、粗暴人名替换丢失关系，不代表AI发现率或生产保护；无真实请求/资料读取/活动链路接线。

- 2026-10-12 GPT-6.1 Sol outcome_trial：已完成工程核验与最小真实模型合成对照，格式验收未通过、真实用户收益待证。范围 desktop/{agenda,brain,test_partner_lifecycle,replay_openworld,test_openworld_replay}.py、docs/superpowers/plans/2026-10-12-blind-outcome-trial.md 和 docs/experiments/2026-10-12-blind-outcome-trial.md。前序工作/说话分离实现保留；失败测试复现并修复新动作结果的同参数核验 token 缺陷。45 focused / 313 full passed；无差错指令的 problem 自行发现 75 差额并生成/读回，人类可读算术内容核验通过；clean 安静无重复成果。problem 的 .csv 实含说明与两块 CSV，不能直接导入，未由开发 agent 人工修文件冒充自主完成。两回放 87.1s/54.6s、17 次成功请求、32800 输入/5221 输出 token，金额成本未知。读取/写入均在本次合成隔离目录，固定合成历史/空白图/全新笔记；未读真实用户资料或扩大出站，未检查/重启现机进程。产物与逐项来源、usage、权限拒绝及 undo 证据保留在 STATUS 所列回放目录；不再付费重放。

- 2026-10-12 GPT-6.1 Sol：进行中：工作/说话分离与基于真实后继的续办，独占 desktop/{agenda,session,brain,test_partner_lifecycle}.py；计划见 docs/superpowers/plans/2026-10-12-proactive-partner.md，已有授权无需再询问执行方式。

- 2026-10-12 Codex：修正“扩展到 200 个”仍是人为上限的问题。危急 C 盘时回收改为穷尽安全候选，不再把模型的 `max_items` 或固定数字当作完成条件；空间恢复或候选耗尽才收尾，仍逐文件复核、可撤回。动作代码已热更新并验证 brain 正常启动。

- 2026-10-11 Codex：操作记录接线完成。真实跨来源小页进入 VISTA INITIAL/STEP，监督进程复用 record_win 持续采集，同时读取此前漏接的 data/events.jsonl；长日志用完整行与绝对字节游标分段，支持来源/时间段/事件顺序查询。真实运行 20261012-072013 已自主调用 desktop_history 且成功返回，随后 inspect 成功；记录输入与取证链已核对，未认定特定作业已发现。回归通过，没有注入任务答案。

- 2026-10-12 Codex：实机 C 盘已降至 0 字节；模型只传 max_items=30，回收约 9MB，未解除阻塞。直接调用同一可撤回 risk/quarantine 引擎释放约 1.29GB，当前可用空间已恢复。进一步修复为危急状态持续扫描至安全候选耗尽，不再把 200 或其他数字当作完成条件；仍逐文件复核且可用 desktop_undo，不纳入用户文件。

- 2026-10-11 Codex：上下文接线修复完成，WORKING 完整且段间刷新、历史按资源归并；现场更新和收尾提示不再挤掉本轮工具证据，旧轮次仍缩减，重复失败动作进入收尾重判。RemoteDisconnected 原样重试一次。针对性回归通过，监督日志确认已热更新；真实下一份作业仍未识别，后台维护成功尚无实证，不注入具体任务答案。

- 2026-10-11 Codex：历史查询/本地资料读取与跨重启 WORKING 接线完成，自主运行已查询历史；真实下一份作业尚未识别，验收未通过。新增按工具证据续办与统一对话/帮助/维护协议，系统压力可独立唤醒判断。范围：desktop/historyfacts.py、actions/session/profiles/brain 与相关测试。后续重点是任务判断质量与模型通道稳定性，不注入具体作业答案。

> 豆包、WorkBuddy、Grok Bot 都只改这一份。认领：在「谁」列写自己名字，把状态改成进行中；完成：改成已完成并在进度区补一行验收。

| 状态 | 任务 | 文件范围 | 谁 |
|---|---|---|---|
| 已完成 | 主动循环效率与后续推进（需要真实场景继续评估） | desktop brain/companion 协议与回归 | Codex |
| 已完成 | 对话衔接与真实模型回放（自然度需持续观察） | desktop 对话上下文、companion 协议、replay_conversation，proactive 对话送达 | Codex |
| 已完成 | 持续目标判断协议、调查中更新现场、真实对话回应（战略效果仍待实测） | desktop/{brain,profiles,actions,session}、设计文档与回归测试，proactive/{live,dialog}.py | Codex |
| 进行中 | T1 真实 Windows 采集与进程控制 | sprite/winprobe.py, procctl.py, sysstate.py | opencode |
| 进行中 | T2 内存告急演示 | sprite/demo_live/, scenarios/resource.py, pressure.py | MainAgent |
| 已完成 | T3 小精灵 GUI | sprite/gui.py, pixels.py | MainAgent |
| 未认领 | T4 价值闸与分层 token | sprite/tiers.py, sim_tokens.py, voice.py | — |
| 未认领 | T5 惯例学习（通用） | sprite/conventions.py, reinvention.py, capability.py | — |
| 已完成 | T6 更多通用场景（只注册） | sprite/scenarios/more.py, extras.py | MainAgent |
| 已完成 | T7 观察与洞察 | lookout/, backfill_win/ | MainAgent |
| 已完成 | T8 评测与对抗 | sprite/eval_all.py, eval_risk.py | MainAgent |
| 未认领 | T9 文档与发布 | README.md, docs/ | — |
| 已完成 | T-GrokBot 未解除问题挂起 | sprite/framework.py, test_framework.py | Grok Bot |
| 进行中 | T-GrokBot investigate-then-act | sprite/investigate.py, scenarios/annoyance.py | Grok Bot |
| 进行中 | T-GrokBot GUI 可见汇报 | sprite/gui.py（冒泡 action + 位置） | Grok Bot |
| 已完成 | T-GrokBot 通用脑：novel 默认定性（非网络优先） | novel.py, investigate.py, scenarios/* 传感器化 | Grok Bot |
| 已完成 | T-GrokBot 网络 HTTP 真通（fake-ip 假通修复） | sprite/scenarios/network.py, test_network.py | Grok Bot |
| 进行中 | T-GrokBot recorder 浏览失败信号（nav/url/browser_error） | observe/, record_win.py, recorder_ext/ | Grok Bot |
| 进行中 | T-GrokBot 僵局观察（dwell/flicker + 触发截图接口） | sprite/scenarios/stalemate.py, observe/capture_hook.py | Grok Bot |
| 已完成 | T-GrokBot 新颖理解（prefer_novel 默认） | sprite/novel.py, investigate.py, test_novel.py | Grok Bot |
| 进行中 | T-GrokBot 文献+微实验 open-world | docs/RESEARCH_*, research/microexp | Grok Bot |
| 已完成 | T14 学习信号修正：companion 气泡超时不再冒充负例 + 开口门槛方向反了 | sprite/proactive/{live,timing}.py, test_outcome_labels.py | Agent Teams signal-fixer |
| 已完成 | T15 开口质量离线度量报告（拒绝把沉默冒充拒绝） | sprite/proactive/outcome_report.py, test_outcome_report.py, docs/OUTCOME_METRICS.md | Agent Teams metric-builder |
| 已完成 | T16 只读审计自动执行 36 次「失败」+ 独立复核学习信号（三份文档） | docs/{AUTO_ACTION_OUTCOME_AUDIT,VERIFY_OUTCOME_SIGNAL_2026-10-12}.md | Agent Teams outcome-auditor / verifier |
| 已完成 | T17 自动执行终态词表修正（auto_failed 名实相反） | sprite/proactive/{live,conversation}.py, test_auto_terminal_state.py | Agent Teams outcome-auditor |
| 已完成 | T18 修跨任务回归：测试隔离依赖 collection 顺序 | sprite/proactive/test_outcome_report.py | Agent Teams metric-builder |

## 认领规则
- 2026-10-12 Codex：完成 desktop/{brain,test_natural_conversation}.py 的执行上下文重复修复；Qodo已登录版本1.4.0，但本机无origin、账户检索OpenLookout/OpenLook均为空，review未能启动；不伪造仓库映射或推送源码。动态agenda由每段请求统一附上，直连历史话轮不保存相同末尾执行快照；保留原生WORKING、工具结果和用户对话。先失败复现两份，再跨轮更新验证一份；热更新后实际8段execution_context_copies均为1。独立只读复审无实质问题，desktop/proactive296通过。真实basic_shell因现场变化被拦截仍是下一执行缺口，不绕过检查。
1. 先改上表状态再动文件；同一文件范围同时只能一个 agent。
2. 完成后在下方「进度」追加一行：日期、谁、验收命令与结果。
3. 不要改别人正在进行中的范围；要协作先留言。

---
# OpenLookout 并行开发任务书

目标：做出「主动判断型智能体」——在电脑上持续观察，自己发现大大小小的潜在问题，**自己判断是否安全，安全就做、有风险才问一次、做完一句话告诉你**，全部可撤销，不用定时器，token 成本极低。设计说明见 `docs/PROACTIVE_AGENT.md`，代码在 `sprite/`。

## 全局规则（所有任务都要遵守）
1. **通用机制优先**：新场景只通过 `sprite/framework.py` 的 `registry.register` 注册检测器和动作，不改核心；不要写专门的某某守卫。
2. **宁可漏做，不可错做**：不认识的一律当唯一物，不碰。任何删除都不能真删，先进可还原的隔离区。误操作率第一指标：`python -m sprite.eval_all` 必须保持 **0 误操作**。
3. **触发由状态变化驱动**，不写 cron/定时清理。
4. **隐私**：原始数据不出本机、不进 git；只发脱敏摘要给云端模型；密钥只读环境变量或 `~/.config/ai-butler/`，不打印不提交。
5. **每个任务**：先写测试再合并；`python -m pytest sprite -q` 全过；改动控制在自己的文件范围；在 PR/提交说明里写清验证了什么、没验证什么（尤其是未在真实 Windows 上跑过的部分）。
6. 提交前自检：`git grep -nE "KEY|token|password"` 不能出现真实密钥。

## 任务（可并行，文件范围互不重叠）

### T1 真实 Windows 采集与进程控制（最高优先）
- 范围：`sprite/winprobe.py`、`sprite/procctl.py`、`sprite/sysstate.py`
- 做什么：用 psutil（可选）+ ctypes 取内存压力、每个进程的空闲时长、前台/可见窗口、音频、窗口标题未保存标记；实现真实的**挂起/恢复**（NtSuspendProcess/NtResumeProcess）、降优先级、收缩工作集；挂起必须写日志，崩溃或退出时 watchdog 自动恢复所有被挂起的进程；`resume_all` 一键恢复。
- 验收：在真实 Windows 上，`eat_memory` 把空闲内存压到阈值下，小精灵只挂起合格的闲置后台进程，前台窗口、音乐标签、未保存文档、IDE、终端、系统和安全进程全部不动；撤销后全部恢复。

### T2 内存告急端到端演示
- 范围：`sprite/demo_live/`、`sprite/scenarios/resource.py`、`sprite/pressure.py`
- 做什么：一键脚本启动小精灵、触发真实内存压力、观察气泡反应；先 DRY 模式列出将挂起的进程，确认后才 `--live`。
- 验收：按 `sprite/demo_live/README` 能在真实电脑上重现一次：自动处理安全项、只问一次风险项、撤销还原。

### T3 小精灵形象与气泡（GUI）
- 范围：`sprite/gui.py`、`sprite/pixels.py`
- 做什么：在真实 Windows 上检查并修复：中文字体、透明底、置顶、DPI 缩放、多显示器、拖动、气泡尾巴指向精灵；idle/observing/working/thinking 四状态动画；详情展开；不抢焦点。
- 验收：截图对比，在 100%/125%/150% 缩放下都不错位。

### T4 价值闸与分层 token 成本
- 范围：`sprite/tiers.py`、`sprite/sim_tokens.py`、`sprite/voice.py`
- 做什么：接入真实的本地小模型（tier1，如 llama.cpp 的 1B~3B 量化模型，8GB 显存可跑）；记录真实 token/费用；每日硬预算与降级；规则缓存持久化。
- 验收：多日模拟里每日 token ≤ 1000；超预算自动降级；报表可读。

### T5 惯例学习器（通用，不是开源专用）
- 范围：`sprite/conventions.py`、`sprite/reinvention.py`、`sprite/capability.py`、`sprite/persist.py`
- 做什么：接入真实的反复提醒来源（agent 规则文件、对话记录）；语义合并「别造轮子」「先找现成的」这类同义表达（可选小模型 `semantic=` 钩子）；真实 GitHub 之外增加 PyPI/npm 索引；全局规则（≥3 个项目）先问再落。
- 验收：多种惯例（不止开源）都能学到并写入多种规则文件；陷阱不误触发。

### T6 更多通用场景（只靠注册）
- 范围：`sprite/scenarios/more.py`、`sprite/scenarios/extras.py`（新增文件放 `sprite/scenarios/`）
- 做什么：真实实现自启项精简和通知洪水静音的控制器（目前只有假控制器）；新增：浏览器标签爆炸、电量低于长任务前预警、大型陈旧构建目录、桌面整理、编号作业环境提前准备（venv/依赖/模板）。
- 验收：每个场景有风险分级、撤销、对抗测试；`eval_all` 0 误操作。

### T7 观察与洞察（长期）
- 范围：`lookout/`、`backfill_win/`、`recorder_win/`
- 做什么：把历史回溯、实时事件接成小精灵的情境模型输入；成果/放弃/来回切换/更好路径这些事件的真实采集；洞察算法（`lookout/insight/`）接到小精灵的岔路口判断。
- 验收：真实机器上行为流里能产生这些事件，岔路口提示有证据且不烦人。

### T8 评测与回归
- 范围：`sprite/eval_all.py`、`sprite/eval_risk.py`、新增 `sprite/eval_*.py`
- 做什么：扩大对抗用例（越多越好，尤其是「看起来像缓存的用户数据」「没保存的文档」「正在被使用的目录」）；变异检查（故意改坏规则要被抓到）；独立来源的用例，不只用自己写的。
- 验收：用例数持续增长，误操作恒为 0，变异检查全部被抓。

### T9 文档、打包与发布
- 范围：`README.md`、`docs/`、新增 `packaging/`
- 做什么：中英文 README 讲清这个新类别；一键安装（Windows 免装 Python 的打包，或 pipx）；演示 GIF；贡献指南。
- 验收：陌生人 10 分钟内装好并看到一次真实的自动处理。

## 协作约定
- 每个 agent 只改自己任务的文件范围；要改别人的文件，先在 `TASKS.md` 末尾写一条请求。
- 合并顺序：T1 → T2/T6 → 其余。T1 没过真实 Windows 验证前，T2 只能跑 DRY。
- 进度记录在下面：

## 进度
- 2026-10-12｜Codex｜插件辅助持续探索修复｜工程完成、真实任务效果待验证｜范围 desktop/{brain,historyfacts,profiles,replay_openworld,test_historyfacts,test_natural_conversation,test_openworld_replay}.py。Superpowers 根因复现和独立只读复审修复：真实工具参数续办身份、内容未变游标保持、被淘汰游标恢复、后续页变化漏判、新历史重新探查及旧快照误覆盖。严格分页模型回放：采购差额75正确交付并独立读回（105.8s）；测量单位1000倍差错正确交付并独立读回（77.4s）；修正正常结果也强制汇报的冲突后，对照quiet无重复交付（41.5s）。最新全套294通过/1失败，为现有test_mem_reading_matches_psutil两次实测间内存波动，不修改无关用例；此前全套294通过，最新局部复核见STATUS。Qodo CLI1.0.0已安装、whoami仍not_logged_in，未运行Qodo审查。已热更新，无具体真实作业注入、未由Codex清理电脑。
- 2026-10-12｜Codex｜真实模型自主发现与交付验收｜本轮完成，真实场景继续验收｜范围 desktop/{actions,session,agenda,brain,profiles,replay_openworld,test_deliverables,test_agenda,test_openworld_replay}.py；金额差额与体积换算盲测实际创建并独立读回核对表、目标done，无错误对照安静。修计划正文重复、来源不匹配诊断、读取长度归因、完成增量及假ready；常驻已启动且自主查询真实历史，真实下一份作业仍未实证。未注入真实作业、未由 Codex 清理电脑，能力与限制见 DECISION_ALGORITHM.md。
- 2026-10-12｜Codex｜开放探索与执行进度｜工程完成，能力验收未完成｜撤掉单目标锁定、固定领域候选和强制评分方向；只读取证可自由探索，目标可重定，执行记录只防丢进度。修复异常卡 running、结果归因与调查覆盖遗漏；desktop/proactive 回归 224 passed（临时目录名含 final 会触发现有 risk 保护，改用中性目录后通过）。监督进程已整体重启，brain/GUI/记录器均恢复。真实模型已有自主查询历史和资料的记录，但未知场景中发现并解决高价值问题仍无验收证据；不将工程检查当成智能达标。
- 2026-10-11｜Codex｜作业证据截图｜已接入，真实作业待验证｜截图绑定作业条目、CURRENT source_id 与原图坐标；原分辨率 PNG 通过 VISTA 返回模型核验，记录相关/完整/清晰/聚焦与原因；过期现场退回，内容变化后拒绝核验及撤回删除。浏览器实验和报告产出仍待接入；范围 desktop/{actions,profiles,session,brain}.py 与对应测试
- （在此追加：日期｜任务｜谁｜状态｜备注）
- 2026-10-09｜T1｜opencode｜领取中｜范围 `sprite/winprobe.py`、`sprite/procctl.py`、`sprite/sysstate.py`（含 `sprite/test_winprobe.py`、`test_procctl.py`、`test_sysstate.py`）；其他 agent 请勿改动这些文件
- 2026-10-09｜T3｜豆包 MainAgent｜完成并验证｜范围 `sprite/gui.py`、`sprite/test_gui.py`（新建）。gui.py 修复：per-monitor v2 DPI 感知（`enable_dpi_awareness`）、虚拟屏矩形钳制气泡不出屏（`screen_rect`/`layout`，多显示器）、气泡尾巴尖端收进精灵边缘（先画气泡后画精灵）、带符号几何串 `_geo`（修复负坐标非法 Tk 语法）、`-toolwindow`+WS_EX_NOACTIVATE 不抢焦点、拖后位置仅在虚拟屏内沿用。保留外部 agent 的详情展开与 should_quit。验证：真实 Windows 2560×1600@150% 下 9 场景截图 + 125%/150% 字号模拟均不错位；尾巴接缝像素级确认白色连续、精灵盖住尖端；`pytest sprite/test_gui.py` 10 项通过；全套失败均为并行代理在途文件（test_sysstate/test_winprobe/test_more）与环境磁盘满，与本任务无关。未验证：真实第二显示器、200%+ 缩放（无硬件）。
- 2026-10-09｜T6｜豆包 MainAgent｜完成并验证｜范围 `sprite/scenarios/more.py`、新增 `sprite/scenarios/win_ctrl.py`、`sprite/defaults.py`（装配）、`sprite/test_more_scenarios.py`（新建测试）。新增三场景：browser_tabs（标签>25 只把最老超额标签网址存档到自家档案文件，标签一个不关、整份可撤销）、battery_prewarn（电量≤20% 未充电且正跑长任务时，暂停可安全挂起的闲置后台进程省电，充电/回升自动恢复、recheck 解除）、homework_env_prep（编号作业目录无 venv 时建 .venv+装依赖+复制模板，`.sprite_prep` 标记证明归属，撤销只删自己建的东西）。真实控制器 `win_ctrl.WindowsController`：自启项（HKCU/HKLM Run 值+启动文件夹快捷方式）先备份后删除、可还原；通知静音（`Notifications\Settings\{App}` Enabled=0，原值备份还原）；winreg 可注入（假注册表无头测试）。验收：`pytest sprite/test_more_scenarios.py` 23 项对抗测试全过（含撤销只删自己的、venv 失败回滚、已有 venv 不碰、不覆盖用户模板、未知名称不崩溃）；`python -m sprite.eval_all` 409 陷阱 / 0 误操作 / 0 漏做；`test_more+test_conventions` 16 项不回归；真实 Windows 上 `defaults.build` 枚举出 14 个自启项（组合控制器 startup_disable/suspend 均可用；Run 值无使用时间→场景按未知=不动）。未验证：真实注册表 disable/enable 往返（未在本机真禁用任何项，保守）、Win11 部分 UWP 应用通知键在系统数据库、200%+ 缩放（与 T3 同因无硬件）。
- 2026-10-09｜T8｜豆包 MainAgent｜完成并验证｜范围 `sprite/eval_all.py`、新增 `sprite/eval_engine.py`。对抗用例增长：eval_all 新增 4 个场景块（resource_pressure 旗舰场景此前未评测：temp 内可再生大文件正例 + docx/被占用/旧安装包/未保存编辑器/前台 explorer 陷阱 + 闲置 chrome renderer 挂起正例 + 切回浏览器自动恢复；browser_tabs 40 标签超额存档 15 条绝不关标签；battery_prewarn 低电挂起闲置进程、长任务/未保存/前台不碰；homework_env_prep 假 venv 建/标记/保留/不碰已有），并压实磁盘占用（bd/rp 陷阱文件改小、dup 副本 60→50MB 保住阈值、重型块总占用降到 ~1GB）。变异检查：核心 watch 管线 `eval_mutate.py` 8/8 全 CAUGHT（0 SURVIVED）；新增引擎/风险层 `eval_engine.py` 3 变异体全 CAUGHT——classify-file-always-safe（163 误操作）、classify-proc-always-safe（12 误操作）、engine-gates-off 去三道闸门（6 误操作）；每变异体独立子进程，峰值磁盘=单次 evaluate。验收：`python -m sprite.eval_all` **461 陷阱 / 0 误操作 / 104 正例 / 0 漏做**（较基线 409/80 增长）；`python -m sprite.eval_engine` 3/3 CAUGHT；全套 pytest 133 过 + 其余失败/错误全部为并行代理写满磁盘（Errno 28 / could not create numbered dir），无逻辑失败。未验证：真实机器上运行整套 eval（本机磁盘被并行代理占满，已用轻量尺寸验证语义；新场景真机行为依赖 T1 控制器落地）。
- 2026-10-10｜T7｜豆包 MainAgent｜认领并完成（基线缺口修复+端到端验证）｜范围 `backfill_win/`、`lookout/`（recorder_win 此前已实测）。T7 核心素材（trajectory/pet/judgment/insight-catalog 等 lookout 未跟踪文件）为并行代理在途，本次未动、未提交。本次交付：(1) 修复 backfill 测试 Windows 兼容——`backfill_win/tests/test_backfill.py` 的 pmod 平台断言、路径分隔符规范化（digest/writes 用 normpath）、ROOT 改系统临时目录（避开 C 盘满与 "OpenLookout" 路径误报）；`D:\python3.11\python.exe backfill_win/tests/test_backfill.py` 全过（此前 3 失败：pmod/只读/越界全因 POSIX 假设）。(2) 补 `lookout/world_kits/ai_tools_check/advisories.json`（基线缺口：文件从未进 git 导致 3 测试 FileNotFoundError；现用真实 GitHub Advisory 快照：langflow 42 条真实公告 + ollama 键 CVE-2024-39720 range<0.1.46，测试版本号 0.35.0/0.40.1 修正为真实受影响/干净版本 0.1.45/0.1.47）→ `pytest lookout/world_kits/ai_tools_check` 4 项全过。(3) 端到端验收证据：fixture 上跑 backfill_win（Windows，3.11）产出 259 条事件（含 backfill:git 提交=「成果」类事件）→ `run_backfill --no-llm` 检出 6 发现/5 候选（site_rhythm×2、recurring_files、repeated_download、duplicate_copies、repeated_lookup，0 LLM 调用）→ `lookout.trajectory` 产出 1 个岔路候选（openlookout_build 行为证据 8 事件/4 天/6 路径 score22 + Codex 0.162 worktree 外部趋势交汇，带 url/date/next_test），judgment 判 quiet（confidence 0.25 证据弱不打扰）——满足验收「真实行为流产生事件、岔路口提示有证据且不烦人」。未验证：pet.py 桌面精灵真机常驻 GUI、recorder_win 常驻采集（需长时间真实交互会话）；并行代理在途文件归属未确认，未提交。

### T-GrokBot 通用未解除问题挂起（进行中/本机）
- 范围：sprite/framework.py、sprite/test_framework.py（不动 gui）
- 改什么：Engine 挂起有 recheck 的问题直到解除；检测器可只边沿报一次；去掉未解除时长冷却闭嘴
- 验收：pytest sprite/test_framework.py -q 含 open_problem 持续推进用例



### T-GrokBot 通用 investigate-then-act（本机，进行中）
- 范围：sprite/investigate.py、sprite/scenarios/annoyance.py、sprite/test_investigate.py、sprite/demo_live/dry_run_annoyances.py；demo_live/live.py 仅加了几行注册（try 包住）；不动 framework.py/gui.py/pixels.py
- 机制：发现器→取证器→裁判（理解记录写 home/understandings.jsonl）→响应器（可还原）；新问题类只需 register，核心零改动
- 已接：反复可见黑窗（计划任务包成 conhost --headless，整份 XML 存档、可还原、事后真跑校验）、陈旧/重复/弃置进程（挂起、不杀、可恢复）
- 默认干跑：demo 配置 annoyance_apply=true 且 --live 才会真动手


### T-GrokBot 网络不可达 / VPN（本机，2026-10-10）
- 范围：sprite/scenarios/network.py、sprite/test_network.py、sprite/demo_live/dry_run_network.py；demo_live/live.py 仅注册几行；demo_live.json `network_apply`
- 机制：investigate 插件——发现（HTTPS/TCP/DNS/无路由/代理端口死/客户端曾在跑现退出）→ 取证 → 理解记录 → 可逆动作（flushdns → 重启已有本地代理/VPN 客户端 → rasdial 已有系统 VPN）；绝不删应用/安新 VPN/永久改防火墙
- 默认：network_apply=true 且 --live 才真动手；先 dry_run_network 探针

- 2026-10-10｜T-GrokBot 网络 HTTP 真通｜Grok Bot｜已完成（PC）｜fake-ip TCP 假通不再算可达；proxy_running_broken；pytest test_network 过；live 验证因关机中断
- 2026-10-10｜T-GrokBot recorder browse failures｜Grok Bot｜进行中（box）｜observe 事件契约 + recorder_ext webNavigation/ERR 页 + record_win 入队；**PC 装扩展前不算 ERR 已通**
- 2026-10-10｜T-GrokBot stalemate observe｜Grok Bot｜进行中（box）｜stalemate 插件 dwell/flicker + CaptureHook/VisionAdapter 契约；pytest test_stalemate / test_observe
- 2026-10-10｜T-GrokBot 新颖理解 cloud LLM｜Grok Bot｜已完成（box）｜`sprite/novel.py`：unknown/低置信→tier2；白名单动作；FakeNovelClient；日预算；investigate 升级；stalemate/network `novel=`/`novel_from_env`；`pytest sprite/test_novel.py` 10 过。启用：`OPENLOOKOUT_NOVEL=1` + API key。

### T-GrokBot 新颖理解（云端大模型，box 2026-10-10）
- 范围：`sprite/novel.py`、`sprite/investigate.py`（升级钩子）、`sprite/test_novel.py`；stalemate/network `build(novel=...)`；文档 OBSERVE_PLAN
- 机制：**prefer_novel=True**：open 问题默认云端定性（非「本地失败才升级」）；self/protected 跳过；证据包→schema 校验→understandings.jsonl；预算用尽降级
- 默认无密钥则关；测试 FakeNovelClient；真机 `OPENLOOKOUT_NOVEL=1` + API key
- 2026-10-10｜通用脑+文献微实验｜Grok Bot｜已完成（box）｜prefer_novel 默认；network/stalemate 传感器化；pytest novel+stalemate+browse+network+observe **31 passed**；E1/E2 microexp ok；文档 ARCHITECTURE/OBSERVE_PLAN/RESEARCH；sync 已镜像
- 2026-10-10｜通用脑重构｜Grok Bot｜已完成（box）｜网络/僵局降为传感器；pytest novel+network+stalemate+browse 见进度
- 2026-10-10｜文献+微实验｜Grok Bot｜进行中（box）｜PROBE/ContextAgent/GUITester 摘要 + synthetic UI→FakeNovel 微实验
- 2026-10-11 Codex：对话衔接工程改动与同供应商回放完成，详见 STATUS；模型表达长度、非防御性接话与服务延迟仍待改善，不将话轮关联成功等同于自然聊天达标。
- 2026-10-12｜T14 学习信号修正｜Agent Teams signal-fixer｜已完成（工程）／真实端到端待证｜修两条活代码病根：气泡 180s 超时（`gui.py:187`→`gui.py:190`→`live.py:269-271`）把「用户没打字」记成硬负例 ignored（真实账本 5/5 全 ignored、latency 180–237s）；`timing.py:147` 正例为 0 时返回 benefit=300s 使门槛变松，与注释自称的「保守」方向相反（合成 20 行 ignored：4 档门槛全变松）。改后 timing 词表 `_POSITIVE={accepted,responded}`/`_NEGATIVE={rejected}`/`_NO_EVIDENCE={ignored,unanswered,acknowledged}`，正例 0 取保守端 30s；live.py 新增 `expiry_outcome()`，无选项超时记 unanswered。验收：新增 `test_outcome_labels.py` 12 条，旧代码上 11 failed、新代码 12 passed；独立复核同一合成数据 after benefit=60/4 档不变、20 行 accepted 收紧到 46.49。实机热更新后无崩溃循环。未验证：真实气泡超时写出 unanswered 的端到端证据。
- 2026-10-12｜T15/T16 度量与审计｜Agent Teams metric-builder / outcome-auditor / verifier｜已完成（文档）｜新增 `docs/OUTCOME_METRICS.md`（真实数据 evidence_n=0，直说「不能判断在变好」）、`docs/AUTO_ACTION_OUTCOME_AUDIT.md`、`docs/VERIFY_OUTCOME_SIGNAL_2026-10-12.md`。关键更正：STATUS.md 第 5 行的「224 passed」不可复现，当前真实为 **1 failed / 278 passed**（用例集合已增至 279）；该失败是 `test_outcome_report` 的隔离依赖 collection 顺序，非生产缺陷，已开 T18。另发现 offers.jsonl 的 36 条 `auto_failed` 实为「本轮未提交结论」（error 字面 `returncode:0`、归档 `stopped` + 0 个 final_response），其中 18 条其实真改过机器（57 次可逆 desktop_trim），「40%」分母重复计 id 不成立，已开 T17。
- 2026-10-12｜T17/T18 交付 + Lead 冻结树终验｜Agent Teams outcome-auditor / metric-builder / Lead｜已完成（工程）／真实端到端待证｜T17：`live.py` 不再把 `returncode:0` 一律记成 `auto_failed`，拆为 `auto_errored`（error=returncode:N）/`auto_no_answer`/`auto_completed`；`conversation.py` 历史 `auto_failed` 行改用中性文本「这次处理没有走到最后一步，我先停下了。」（导入前真实会话 36 条命中旧文案、其中 18 条其实真改过机器 57 次可逆 desktop_trim；改后 0 旧 36 中性）；新增 `test_auto_terminal_state.py` 8 条。T18：`test_outcome_report.py` 的 `timing_blocked` fixture 同时毒化 `sys.modules` 并清父包属性 + 防泄漏断言；生产文件 `outcome_report.py` 逐字节未变。Lead 另修 `outcome_report.py:216` `status` 与 `available` 自相矛盾（该字段只写不读）。验收：`cd E:\OpenLookout\src\openlookout` 后 `D:\python3.11\python.exe -m pytest vista/benchmarks/desktop sprite/proactive -q` → **288 passed / exit 0**；真实数据复跑结论仍为「不能判断开口质量在变好」（evidence_n=0）。实机 brain 48452 / GUI pythonw 52000 存活、无崩溃循环。未验证：真实气泡超时写出 `unanswered`、真实 `run_offer` 端到端、真实非零 returncode；`sprite/proactive/` 仍未入 git。
