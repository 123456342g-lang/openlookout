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
- （在此追加：日期｜任务｜谁｜状态｜备注）
- 2026-10-09｜T1｜opencode｜领取中｜范围 `sprite/winprobe.py`、`sprite/procctl.py`、`sprite/sysstate.py`（含 `sprite/test_winprobe.py`、`test_procctl.py`、`test_sysstate.py`）；其他 agent 请勿改动这些文件
- 2026-10-09｜T3｜豆包 MainAgent｜完成并验证｜范围 `sprite/gui.py`、`sprite/test_gui.py`（新建）。gui.py 修复：per-monitor v2 DPI 感知（`enable_dpi_awareness`）、虚拟屏矩形钳制气泡不出屏（`screen_rect`/`layout`，多显示器）、气泡尾巴尖端收进精灵边缘（先画气泡后画精灵）、带符号几何串 `_geo`（修复负坐标非法 Tk 语法）、`-toolwindow`+WS_EX_NOACTIVATE 不抢焦点、拖后位置仅在虚拟屏内沿用。保留外部 agent 的详情展开与 should_quit。验证：真实 Windows 2560×1600@150% 下 9 场景截图 + 125%/150% 字号模拟均不错位；尾巴接缝像素级确认白色连续、精灵盖住尖端；`pytest sprite/test_gui.py` 10 项通过；全套失败均为并行代理在途文件（test_sysstate/test_winprobe/test_more）与环境磁盘满，与本任务无关。未验证：真实第二显示器、200%+ 缩放（无硬件）。

### T-GrokBot 通用未解除问题挂起（进行中/本机）
- 范围：sprite/framework.py、sprite/test_framework.py（不动 gui）
- 改什么：Engine 挂起有 recheck 的问题直到解除；检测器可只边沿报一次；去掉未解除时长冷却闭嘴
- 验收：pytest sprite/test_framework.py -q 含 open_problem 持续推进用例

