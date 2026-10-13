# 协作看板（认领 / 进行中 / 已完成）

- 2026-10-12 GPT-6.1 Sol outcome_trial：核验前序生命周期实现已落盘，复用 Agenda/ContinuationTracker，不重复实现；失败测试复现“同目标新动作结果后的同参数核验被旧 token 吞掉”，仅将 last_result.id 纳入续办身份修复。新增隔离合成 blind-purchase 操作轨迹，无指定差错或核对指令，含上期正确成果、正常阅读、无影响内存指标与重复切换；回放仅能读取本次 workspace/operations 和 deliverables，固定合成历史快照、全新 VISTA 笔记，记录来源与模型 usage，失败即停止。45 项针对测试、desktop/proactive 全套 313 passed（39.78s）。真实模型 problem 自行发现沿用上期数量造成差额 75，创建成果并独立读回；clean 核对正确金额后 quiet、无重复成果。证据目录分别为 sprite_home/openworld_replay/20261012-184336-synthetic-05927a61 和 20261012-184521-synthetic-74008f99；耗时 87.1s/54.6s，17 次成功请求、输入 32800/output 5221 token，金额成本未知，problem 一次 TLS EOF 按既有通道原样重试成功。**格式验收未通过**：release-核对与修正.csv 含自然语言说明与两块 CSV，非可直接导入的纯 CSV；算术与真实读回通过，不代表可导入成果或完整任务完成，开发 agent 未人工修饰产物。仅上传合成操作/资料、空白图与新笔记至既有模型服务；未读真实用户历史/剪贴板/作业，未扩大采集或出站、未清理或重启用户程序。现机运行状态未核验；未证明真实用户任务获益。详细验收见 docs/experiments/2026-10-12-blind-outcome-trial.md。

- 2026-10-12 GPT-6.1 Sol：认领第一阶段工作生命周期切片，范围 desktop/{agenda,session,brain,test_partner_lifecycle}.py 与计划；复用 VISTA/Agenda，分离静默与工作推进，验证无屏幕变化续办、独立核验与重启不重放。仅本地隔离工具验收，不把回归称为战略智能；runtime_review_sol 独立只读复核。

- 2026-10-12 Codex继续：Qodo登录成功，版本1.4.0，工具目录可访问；本地无origin且账户检索OpenLookout/OpenLook均无匹配，远程review未启动。继续通过Superpowers复现INITIAL/STEP执行状态与段间执行状态重复的问题，改为直连请求统一提供一份最新状态，保留观察/对话/工具配对；新增execution_context_copies实测热更新后8段均为1。独立只读复审无实质问题，desktop/proactive296通过。真实调查仍因页面变化阻止basic_shell，未绕过其环境动作检查，不把请求去重当实际用户任务完成。

- 2026-10-12 Codex：用 Superpowers 设计、复现、修复和独立复审改进主动连续性。续办携带实际工具参数并据参数去重；历史内容比较包括已采集的后续页，不重复替换有效快照，失效游标在来源未变时也恢复；新历史能重新探查，旧快照读取不消耗新上下文。修正无价值正常核对仍汇报的提示冲突。严格分页真实模型回放产出并独立核验金额差额75与单位1000倍核对表；无错误对照安静、不造重复文件。结果在 sprite_home/openworld_replay/20261012-133816-purchase-paged-problem、20261012-134135-purchase-paged-clean、20261012-134220-measurement-paged-problem。热更新后brain与窗口运行、实际继续取证；未证明真实下一份作业已找到。Qodo CLI已安装，账户未连接，未运行其审查。最新全套294通过/1失败（现有内存实测瞬时波动），随后desktop/{test_historyfacts,test_natural_conversation,test_openworld_replay,test_systemfacts}局部复核78通过；没有把工程回归当产品效果。

- 2026-10-12 Codex：已接通自主取证到交付文件的闭环，复用 Tabbit 观察现有页面，新增自身目录 md/txt/csv 交付物与独立读回、撤回。真实模型未获隐藏错误指令时，从操作历史发现采购差额75和体积单位1000倍错误，分别生成并核验核对表；正确金额对照安静且不重复产出。修复计划正文重复、读取长度误归因、完成增量和假 ready。常驻 brain、GUI、记录器已重启并自主查询真实历史；真实下一份作业尚未实证，浏览器实验/原文件修改/完整复杂办公流程仍缺能力，不把这两项盲测宣称为全面达标。

- 2026-10-12 Codex：修正把通用队列当智能核心的方案。开放探索沿 VISTA 原生工具循环、history/WORKING 进行：观察线索、比较解释、取证、依结果重定目标、尝试并核验；agenda 仅保存执行状态。只读探索无需先登记目标或服从局部评分，按实际工具 effect 判断能力；去掉新颖度自身的调查奖励。变更须登记预期与独立核验，完成引用本目标结果并说明预期是否满足；异常不再卡 running，也不宣称电脑没被改动。修复结果引用尾注导致实际取证覆盖无法解析。验收：`python -m pytest vista/benchmarks/desktop sprite/proactive -q --basetemp E:/OpenLookout/tmp/pytest-openworld-verified`，224 passed。监督进程整体重启为 12032，brain 1572、GUI 30356、记录器 7360 正常；未由 Codex 清理真实磁盘。运行已出现自主历史和资料查询，但高价值问题发现、正确改目标和有效解决仍需真实场景验收，尚不能声称开放世界能力达标。设计见 desktop/DECISION_ALGORITHM.md 的开放探索章节。

- 2026-10-12 Codex：按反馈移除危急清理的固定扩展上限：`desktop_reclaim` 在 C 盘危急时会持续扫描并处理所有通过 safe 风险核验的候选，直到空间恢复或候选耗尽；`max_items` 仅用于非危急的显式小批量，危急时忽略。每项仍写撤回日志、压缩校验后隔离，可用 `desktop_undo` 还原。动作代码已热更新，brain 正常启动。

- 2026-10-12 Codex：C 盘实测 0 字节；brain 曾 6 次调用 desktop_reclaim，其中 max_items=30 仅安全隔离约 9MB。已用同一工具安全扩大至 200 个，释放约 1.29GB，全部在 quarantine、可用 desktop_undo 还原；当前 C 盘约 1.29GB 可用。新增危急磁盘自动放大批次逻辑，风险分类、撤回日志和逐文件状态复核不变。模型仍需继续通过真实报告理解“空间已恢复”，但不再因小批量停在 0。

- 2026-10-11 Codex：真实操作记录已成为 VISTA 环境输入。补接原记录器的 data/events.jsonl，监督进程增加 record_win 子进程写 sprite_home/perceive/operations.jsonl；实际 INITIAL 已包含 activity/browser/downloads/recent 的真实小页与覆盖，Office 无记录如实保留。长日志支持 2MB 完整行读取、绝对游标向前追查、来源筛选、since/until 和 events 的时间顺序；不会传剪贴板正文。运行 20261012-072013 自主调用 desktop_history 与 inspect，两者实际成功返回。07:21:05 热更新后仍为单监督进程、单 brain/GUI 与新记录器；保留另一个既有记录器，不结束它。具体下一份作业正确识别仍待实证。

- 2026-10-11 Codex：关机后重新启动监督进程 25764、brain 25996、GUI pythonw 26004；后续热更新正常。自主调查审计发现上一完整会话 55 次 basic_search、0 次 desktop_history，说明围绕既有开发线搜索并未覆盖真实操作来源。修复请求元数据被算成新证据，以及模型无法直接核对自身调查覆盖的缺口；覆盖由实际回包生成，保留空结果、截断、过滤与未读页。真实下一份作业尚未识别，不能把启动与接线回归当作目标通过。

- 2026-10-11 Codex：修复直连调查上下文断点：真实轮次起点独立于 CURRENT 更新与收尾提示，本轮工具证据保留、旧轮次缩减、只发送最新画面；最新 WORKING/ GUIDE 完整送达且不会写入 assistant 回答。历史默认 resources 归并，保留次数/时间/来源，可切 events 核对过程。失败动作重复且无新证据时收尾重判；远端无响应断开原样重试一次。回归检查通过，22:27:13 监督进程已加载最新 brain。自主查询已有实际调用，但下一份作业仍无正确识别证据；维护被拒调用不能算成功，模型通道单段仍出现较长等待。

- 2026-10-11 Codex：常驻 VISTA 已接入只读 `desktop_history` / `desktop_read_local`，查询复用 Windows backfill，快照分页且保留来源覆盖与未知条件；没有给模型发送特定作业任务、候选名称或日期。真实运行已自主查询历史，但目前偏向当前项目/读书线索，仍未识别用户下一份作业；WORKING 中存在未经核实的系统/进程陈述，不能当作真实动作成果。新增证据驱动续办、跨重启保存原生 WORKING、统一对话/帮助/维护判断；系统事实纳入初始轮并在主循环独立检查压力变化。针对性验证通过；较早全套出现一次实测内存瞬时变化断言失败，其余通过。最新运行已热更新，模型端点仍间歇 TLS EOF / RemoteDisconnected，不能宣称三层实际体验已达标。

> 豆包、WorkBuddy、Grok Bot 都只改这一份。认领：在「谁」列写自己名字，把状态改成进行中；完成：改成已完成并在进度区补一行验收。

| 状态 | 任务 | 文件范围 | 谁 |
|---|---|---|---|
| 已完成 | 消除 quiet 重判空转、传输上下文去重、下一步续办与 token 实测（服务延迟和模型判断仍需观察） | desktop/{brain,session,actions,profiles}、回归测试与设计文档 | Codex |
| 已完成 | 对话衔接：真实回应关联、当前话轮优先、减少自我复盘（模型表达仍需长期回放） | desktop/{brain,profiles,actions,session,replay_conversation,test_natural_conversation}.py，proactive/{conversation,live}.py | Codex |
| 已完成 | 持续目标决策协议、段间现场更新、去除固定天气与伪回复；长期效果待验证 | desktop/{brain,profiles,actions,session}、设计文档与测试，proactive/{live,dialog}.py | Codex |
| 已完成 | T10 系统事实层（视觉看不见的 C盘/内存/重进程 + 趋势） | vista/benchmarks/desktop/systemfacts.py, test_systemfacts.py | WorkBuddy |
| 已完成 | T11 brain 接两条事实线（watching + systemfacts） | vista/benchmarks/desktop/brain.py, test_brain_wiring.py | WorkBuddy |
| 已完成 | T12 帮忙闭环：做完后必须 submit 收尾，否则用户只看到「没能帮上忙」 | vista/benchmarks/desktop/profiles.py, test_help_chain.py, test_help_e2e.py | WorkBuddy |
| 已完成 | T13 时机闸：同一件事没回应前不重复说（修真实事故：同一句提议连发 4 次） | sprite/proactive/help.py, vista/benchmarks/desktop/session.py, sprite/proactive/test_timing.py | WorkBuddy |
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
| 已完成 | T-GrokBot 通用脑：novel 默认定性（非网络优先） | novel.py, investigate.py, network/stalemate 降为传感器, docs | Grok Bot |
| 已完成 | T-GrokBot 网络 HTTP 真通（fake-ip） | sprite/scenarios/network.py | Grok Bot |
| 进行中 | T-GrokBot recorder 浏览失败信号 | observe/, record_win.py, recorder_ext/ | Grok Bot |
| 进行中 | T-GrokBot 僵局观察 | stalemate.py, observe/capture_hook.py | Grok Bot |
| 已完成 | T-GrokBot 文献+微实验（开放世界异常/主动助手） | docs/RESEARCH_*, research/microexp | Grok Bot |
| 已完成 | T-GrokBot exp_progress 微实验（progress/stuck/error → FakeNovel P/R/F1） | research/exp_progress/, research/microexp ROOT→sync | Grok Bot |
| 已完成 | T14 学习信号修正：companion 气泡超时不再冒充负例 + 开口门槛方向反了 | sprite/proactive/{live,timing}.py, test_outcome_labels.py | Agent Teams signal-fixer |
| 已完成 | T15 开口质量离线度量报告（拒绝把沉默冒充拒绝） | sprite/proactive/outcome_report.py, test_outcome_report.py, docs/OUTCOME_METRICS.md | Agent Teams metric-builder |
| 已完成 | T16 只读审计自动执行 36 次「失败」+ 独立复核学习信号（三份文档） | docs/{AUTO_ACTION_OUTCOME_AUDIT,VERIFY_OUTCOME_SIGNAL_2026-10-12}.md | Agent Teams outcome-auditor / verifier |
| 已完成 | T17 自动执行终态词表修正（auto_failed 名实相反） | sprite/proactive/{live,conversation}.py, test_auto_terminal_state.py | Agent Teams outcome-auditor |
| 已完成 | T18 修跨任务回归：测试隔离依赖 collection 顺序 | sprite/proactive/test_outcome_report.py | Agent Teams metric-builder |

## 认领规则
- 2026-10-12 Codex：完成 C 盘危急时后台维护被前台画面更新反复拦截的修复；范围 desktop/brain.py、test_natural_conversation.py。desktop_reclaim 依据工具内实时磁盘读数和逐文件风险复核，不依赖前台像素或窗口；新用户反馈仍拒绝旧决定，其他动作仍检查画面。模拟回归验证画面变化时能执行、新反馈时拒绝、过期进程操作仍拒绝。热更新后运行中的小精灵真实调用 reclaim：4959 个可再生文件进入隔离区，工具报告 C 盘 0.22GB→3.69GB、释放 3.47GB；独立读取约 3.68GB 可用。没有从 Codex 直接调用清理；注意本次重试接收了 Codex 转述的澄清反馈，不能当作无提示自主发现能力的验证。
- 2026-10-11 Codex：精准作业截图工具接入当前 VISTA 会话。按作业条目定位，匹配 CURRENT source_id，使用实际尺寸映射原分辨率 PNG；场景或区域变化退回重定位。裁图通过 VISTA 返回模型，逐项核对相关/完整/清晰/聚焦并记录 accepted/rejected，内容哈希变化使旧核验失效；不能同请求预先核验尚未返回的截图。保存前写撤回日志，用户修改过的文件撤回时保留。工程回归通过，监督进程已自动加载；未在真实课程上验证截图选择准确率，浏览器实验执行和报告生成仍待接入。
- 2026-10-11 Codex：认领主动闲聊闭环，范围 desktop/{brain,chat_planner,chat_facts,weather,actions,profiles,session}.py、proactive/{help,live}.py 与对应测试；从固定谈资改为 VISTA 自选问题、联网取证、生成对话。网络出口城市不再当用户所在地。
1. 先改上表状态再动文件；同一文件范围同时只能一个 agent。
2. 完成后在下方「进度」追加一行：日期、谁、验收命令与结果。
3. 不要改别人正在进行中的范围；要协作先留言。

---

打开完整任务说明见 [TASKS.md](TASKS.md)。

- 2026-10-13 WorkBuddy：按用户要求把 VISTA 后端固定为**宿主机 claude code**（host-native-unsandboxed，不经 Docker），模型走本机供应商 opus 别名档 = deepseek-v4.1-flash。修掉一个真病根：`runner.py` 主循环把「边界收尾后 MCP 连接被 TerminateProcess 打成 RST（WinError 10054）」误判成 `MCP host failed`——Windows 宿主机模式下每个 decision_complete 边界都必然触发，片段返回 1 → lifecycle 走 fresh runtime recovery → 5 次后 runtime 判 backend_failure → brain 退出 → 监督进程重启，一轮正常决策要烧 2~6 个模型段。改为「已在本轮边界上主动收尾后，host.failure 只是 teardown 噪声，不算失败」（边界已记录并确认，后续 MCP 错误改不回去）。验收：`D:\python3.11\python.exe -m pytest vista/benchmarks/desktop sprite/proactive -q` → **319 passed in 22.37s**；实机 brain 重启后连续多轮 `turn done boundary=decision_complete` 单段完成、无 recovery 段、supervisor 10 分钟无重启。链路实证：segment_000.stdout.jsonl 里 assistant 消息 `"model":"deepseek-v4.1-flash"`；companion 工具正常记录决定；提问「你现在在做什么呢？」→ 自然回答「我在收实验6的尾：任务书 6 页全读了一遍……现在只剩你把修正副本里那个 14 改成 13。」随后正确转 quiet。冒烟测试确认宿主机 claude 经 127.0.0.1:15721（CC Switch 代理）可用。**未验证**：窗口气泡的实际视觉效果（需要有屏幕的人确认）；点「好的」后的桌面任务执行链路本轮未端到端跑（沿用既有测试证据）； brain.py 今天 06:48/06:57 两次被并行编辑成语法错误/NameError 中间态，监督进程热重启期间出现短暂 crash loop——文件自身恢复后自愈，但并行编辑与常驻 brain 的冲突是真实协作风险，已在此登记。


- 2026-10-11 Codex：修复主动循环停住与 token 浪费：companion 每轮补齐结构化 `next_step`（ready 自动续办一次并去重，waiting/done 不造空转），GUI 对话框显示下一步；同一轮最多 12 个模型段；旧截图在直连请求中改为 VISTA history 引用，仅保留最新画面；当前笔记只在首段附上并截取 3000 字；无工具调用时明确要求下一段直接 companion，不重复读笔记；记录每段输入/输出 token、缓存命中、请求大小、截图数和工具名。实际日志约 6–9k 输入 token/段、通常约 4k 缓存命中，已有请求出现 83 秒的公共搜索调用，调查工具仍是主要延迟来源。模型当前能产生 next_step，但 waiting 时不会主动造任务。最新桌面与 proactive 回归 **150 passed**，小精灵监督进程、brain、GUI 均在运行。
- 2026-10-11 Codex：继续修正历史增长：直连消息窗口保留当前与上一条普通用户话轮，保证工具请求/结果配对，早期画面交给 VISTA history；新增窗口回归。实跑重启后首段输入降至约 2.8k（缓存约 6.1k 的请求仍会因供应商计量口径变化），上一轮曾涨到 11.8k，已定位为从首条用户消息开始的裁剪错误。最新回归 **151 passed**，监督进程、brain、GUI 仍在运行。

- 2026-10-11 Codex：针对“聊天不顺畅”增加真实话轮关联：GUI 消息保存稳定 id，companion 使用 reply_to 关联回答，待回应问题显式优先进入 VISTA 上下文；未关联的主动开场不会消除待回复消息。用户换窗口不会中断直接回答。对话提示词要求先回答眼前意思、被质疑时重新检查依据、避免自我复盘和无关建议；新增 replay_conversation 用配置模型回放分歧/追问，独立保存，不写用户聊天或调用桌面变更。回放连续回答两轮并正确关联，但最新回复仍偏长且有防御旧观点/追加建议的倾向，不能声称自然度已解决。桌面与 proactive 回归 149 passed；回放服务响应约 10–23 秒，延迟仍存在。已热更新，GUI 与 brain 均运行。

- 2026-10-11 Codex：将分散且重复的行为提示收拢为目标→证据与不确定性→候选决策→预期改善→真实结果。WORKING 使用 VISTA 原生笔记，不另造画像或视觉历史；companion 可记录内部 decision，quiet 和工具结果也写本地 decisions.jsonl。Windows 直连新增最新帧采样线程，模型等待/调查期间继续采样，段间通过 TaskRuntime 更新 CURRENT；过期变更或窗口/消息切换后的发言退回重判。同窗口像素变化不会一律禁止聊天，仍可能存在单段滞后。移除后台每日天气和固定主题轮转；GUI 只排队真实消息，去掉“收到”伪回复；修复无正文开口仍完成回合、工具消息配对截断与旧判断时间被刷新问题。相关桌面与 proactive 回归通过，最新局部修正也通过；19:23 GUI 实际送达围绕阅读的对话，随后 quiet。该句仍偏复述且较长，不能宣称自然度或战略帮助已达标。模型请求仍需数秒至数十秒；完整直连压缩、容器段间更新与办公执行能力仍是明确缺口。设计与限制见 desktop/DECISION_ALGORITHM.md。

- 2026-10-10 Grok Bot：research/exp_progress F1=1.0 (P=1 R=1 TP16 TN8 FP0 FN0)；E1/E2 ok；microexp ROOT→sync/src。验收：`python3 research/exp_progress/run_exp.py`
- 2026-10-10 WorkBuddy：新增系统事实层 systemfacts.py（C盘/内存/重进程+趋势）+ brain 接入 watching+systemfacts 两条事实线。验收：`python -m pytest vista/benchmarks/desktop/test_systemfacts.py vista/benchmarks/desktop/test_brain_wiring.py -q` → **20 passed**（含真值回归：数字与 psutil/shutil 实读一致）。本机实测 C盘剩0.6GB(0.4%)/内存剩0.48GB，事实行真会报。
- 2026-10-10 WorkBuddy：打通「点好的→动手→汇报→撤回」闭环（test_help_chain14 + test_help_e2e 7）+ 时机闸（test_timing 16）。合计 `pytest vista/benchmarks/desktop/ sprite/proactive/ -q` → **77 passed**。
  修掉的两个真病根：① `profiles.py` 从没告诉模型做完后要 `submit` 收尾 → 执行完也是空，用户只看到「没能帮上忙」（已在 _COMMON 和修电脑场景各写一条）；② `session._companion` 直接 `publish` 绕过冷却 → 真实日志里同一句「C盘快满了」连发 4 次、0 接受 0 拒绝（现由 `help.worth_saying()` 统一闸管，两条出提议的路都必须过；空 topic 退化为用话本身指纹比对）。
- 2026-10-10 WorkBuddy（诚实记录）：中断中误删 `vista/benchmarks/desktop/reading.py`，该文件从未入 git、无法恢复；已由并行 agent 的 `watching.py`（通用化、不认具体场景）取代并接入 brain。brain.py 原有 `import reading` 曾因此处于 ImportError 状态，现已修复。
- 2026-10-11 Codex：接入 Windows 原生 PyWinRT 定位；移除 IP/时区城市猜测与旧天气缓存，新增只读 `basic_location`；用户开启系统定位后实测返回坐标，天气使用真实坐标。验收：`python -m pytest -q src/openlookout/vista/benchmarks/desktop` → **109 passed**。
- 2026-10-11 Codex：主动对话改为同一 VISTA 会话的语义判断；运行时移除旧 ChatPlanner 次数/计时/模板通道、规则评分开口闸；送达对话在模型调用前加入上下文，工作/阅读也可自然接话。接入 DDGS 搜索、trafilatura 读正文；修复 Windows 直连丢弃 VISTA inspect/history 返回图片的问题。15:45 运行中的模型自行检索阅读内容并调用 companion，GUI 已写入送达记录；首条语气仍偏播报且因果判断过强，已修改提示词区分事实与观点，不视为自然对话质量已充分验证。
- 2026-10-11 15:50 Codex：更新提示词后的真实会话继续围绕阅读内容，自行搜索、读取公共来源、分享另一种解释，GUI 已记录这条对话（id `1791705012993060100`）。本轮资料核实较长且 companion 参数有两次被协议拒绝；主动链路已成立，表达质量与研究过程延迟仍需真实使用评估，不能将送达成功等同于各场景都已自然。
- 2026-10-11 Codex：根据用户“表达长、查不关心的资料”的反馈，加入主旨/枝节与兴趣假设判断；对话现场明确最近开口后有无接话，不把未回应当兴趣证据。公共搜索需要说明用途与足够答案，读原文也围绕用途，目的不送公共服务；开场先提炼清楚的小想法，接话后再展开，不以截断代替理解。已热更新。新回放的实际模型验证受间歇性 TLS EOF 中断影响，不能声称最新版本的自然度已实测达标。
- 2026-10-12 Agent Teams（Lead，范围 sprite/proactive/{live,timing}.py 与对应测试）：修掉「主动开口」学习信号的两条活代码病根。① 气泡超时=负例：`sprite/gui.py:187` 的 `after(wait*1000, hide(expired=True))` → `gui.py:190` `on_expire()` → `live.py:269-271` 无条件 `record_outcome(offer,"ignored")`，而 kind==companion 的展示时长是 180s（`live.py:303-305`），于是「用户 180s 没打字」被记成硬负例；真实账本 `sprite_home/perceive/outcomes.jsonl` 5/5 全 ignored、latency 180–237s，其中至少一条是真实帮上忙的（清 Temp，C 盘 1.96G→3.04G）。② 门槛方向反了：`timing.py:106-107` 把 ignored 计入负样本，`timing.py:147` 在正例为 0 时返回 benefit=300s，而 `stop_threshold=cost/benefit` 是 benefit 越大门槛越低——注释自称「保守到几乎不开口」，实际相反；合成 20 行 ignored 时 tabbit/edge/default/notepad 四档门槛 p* 全部变松（0.95→0.59 等）。已改：timing.py 词表为 `_POSITIVE={accepted,responded}` / `_NEGATIVE={rejected}` / 新增 `_NO_EVIDENCE={ignored,unanswered,acknowledged}`（沉默不是证据），正例为 0 时取保守端 `BENEFIT_MIN_S=30s` 并让 why 如实写明；live.py 新增 `expiry_outcome()`，只有真给过选项才算 ignored，无选项的 companion/say 超时记 unanswered。独立复核（verifier，非作者）同一合成数据：before benefit=300/4 档门槛全变松 → after benefit=60（出厂先验）/4 档不变，20 行 accepted 时收紧到 46.49，真信号仍能校准。新增 `test_outcome_labels.py` 12 条在旧代码上 11 failed（抓到旧 why 原文「39/0.112=300s」），新代码全过。实机未弄坏：supervisor.log 仅「重启 brain / 只热更新窗口」，无崩溃循环。**更正本文件第 5 行的记录**：「224 passed」现不可复现（用例集合已增至 279），当前真实数字是 **1 failed / 278 passed**，那条失败属测试隔离依赖 collection 顺序（见下表 T18），非生产缺陷。
- 2026-10-12 Agent Teams（Lead，范围 docs/ 三份新文档）：把「改进不可测」这件事本身做成可复核的。产出 `docs/OUTCOME_METRICS.md`（离线度量：按 kind 分列，强制区分正面/负面/无证据，分母必须写明；对真实数据跑出 evidence_n=0，结论直说「现在这套数据不能支撑开口质量在变好的判断」）、`docs/AUTO_ACTION_OUTCOME_AUDIT.md`（只读审计）、`docs/VERIFY_OUTCOME_SIGNAL_2026-10-12.md`（独立复核，含 7 条对抗性误判）。审计的两条硬结论：offers.jsonl 里 36 条 `auto_failed` 的 error 字面全是 `returncode:0`、运行归档全是 `stopped(session_closed)` + 0 个 final_response ⇒ 它记的是「本轮没提交最终结论」而不是「操作失败」，名实相反（T17 修）；其中 18 条其实真改了机器（合计 57 次可逆 desktop_trim），而「40% 失败率」=36/(54+36) 把同一逻辑开口的两行重写算两遍、分母重复计 id，从构造上就是错的。已登记但未做的开放项：① 带 options 的 offer 在真实数据里从未出现过（offers.jsonl 中 options 非空 = 0 行），accepted/rejected 这条路径从未走过；② undo 只写 offers.jsonl，对只读 outcomes.jsonl 的 timing 完全不可见；③ 9 条 auto_started 没有任何终态行。未验证：真实 companion 气泡 180s 超时后写出 unanswered 的端到端证据（账本最后一行仍是 11:59:33 的旧 ignored 数据）；未跑 vista 全量。
- 2026-10-12 Agent Teams（Lead，全员停手后的冻结树终验）：`cd E:\OpenLookout\src\openlookout` 后 `D:\python3.11\python.exe -m pytest vista/benchmarks/desktop sprite/proactive -q` → **288 passed in 19.55s / exit 0**（上面 T16 记的那条失败已由 T18 修掉；「224 passed」这一旧数字仍不可复现）。T17 交付：`live.py` 不再把 `returncode:0` 一律记成 `auto_failed`，改为 `auto_errored`（error=returncode:N）/ `auto_no_answer` / `auto_completed` 三态；`conversation.py` 对历史 `auto_failed` 行改用中性文本「这次处理没有走到最后一步，我先停下了。」——导入前真实会话里正好有 36 条命中旧文案「我保留了现场，没有继续改动」，其中 18 条其实真改过机器（57 次可逆 desktop_trim），改后 0 条旧文案、36 条中性；新增 `test_auto_terminal_state.py` 8 条。T18 交付：`test_outcome_report.py` 的 `timing_blocked` fixture 改为同时毒化 `sys.modules` 并清父包属性，另加一条防泄漏断言；`outcome_report.py` 生产文件逐字节未变。Lead 另修 `outcome_report.py:216` 的 `status` 字段自相矛盾（`available=true` 时仍写「校准状态未知」）：该字段全仓只写不读，`render_markdown` 用的是字面量，故改动不触及渲染；现 `available=true` 写「校准状态已读取」，timing 自报证据不足时写「校准状态已读取（timing 自报证据不足）」。对真实数据复跑：`calibration={available:true, status:校准状态已读取（timing 自报证据不足）, benefit_s:60.0, p_star:0.45}`、`buckets={companion:{n:5, evidence_n:0, labels:{ignored:5}}}`，结论原文「不能：5 条结果全部是「无证据」（沉默 5 条、模糊 0 条、未知 0 条），没有任何正面或负面证据——无回应不等于拒绝，这套数据不能支撑「开口质量在变好」」。实机未弄坏：brain 48452（13:10:25）与 GUI pythonw 52000（13:15:26）存活，supervisor.log 尾部仅「重启 brain / 只热更新窗口」，无崩溃循环；仓库内无残留 .bak/.orig/.tmp。未验证/未做（不得当作已达成）：真实 companion 气泡 180s 超时写出 `unanswered` 的端到端证据（账本最后一行仍是 11:59:33 的旧 ignored）；没有真实 `run_offer` 端到端（无 live `auto_no_answer` 行）；`--directory` 等价性只由 `cli.py:11,21-22` 与 `perceive.py:17-18` 的代码等价性推断，真实非零 returncode 未观测到；9 条 `auto_started` 仍无终态行；带 options 的 offer 从未出现（accepted/rejected 路径从未走过）；undo 只写 offers.jsonl，对只读 outcomes.jsonl 的 timing 完全不可见；未跑 vista 全量；`test_systemfacts.py::test_mem_reading_matches_psutil` 仍是负载敏感的既有 flaky（单独跑过），与本次改动无关。这批改动全部只在工作区，`src/openlookout/sprite/proactive/` 至今未入 git（HEAD 仍是 `dd697a5`，10-10 07:53）。
