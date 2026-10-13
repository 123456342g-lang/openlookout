# OpenLookout 小精灵 · 架构与协作指南

## 愿景（项目负责人原话）

该项目的愿景是实现持续观察，看准时机主动帮忙，能听取用户反馈，形成用户画像的智能体小精灵，它应该会清楚用户要什么，用户反馈只能作为权衡，例如用户说要一匹快马，但是这个智能体懂得给它一辆汽车，类似这样的问题，很类似一个产品经理，在已有基础上持续迭代项目

## 一句话

小精灵常驻在 Windows 桌面右下角，**持续看用户的屏幕**，在**看准的时机**主动开口：安静陪伴、一句关心，或提出能具体帮上的事；用户点头才动手，所有动作**可撤回**；它会形成**用户画像**，把用户反馈当作权衡依据，而不是命令。

## 架构总览

```
 屏幕  ──►  DesktopSession  ──►  VISTA TaskRuntime  ──►  Claude Code（容器内）──►  mimo 模型
 (每次变化)   (一帧一个观察)      视觉记忆·工具·笔记·交接      (只是模型的传输通道)       (provider.json)
                                        │
                                        ├─ companion 工具：本轮的决定（quiet / companion / offer）
                                        │        └─► perceive/offer.json ─► 小精灵窗口气泡 ─► 用户点 好的/不用
                                        ├─ history / inspect / read_pixels：回看过去的画面
                                        ├─ GUIDE.md：用户画像（长期，跨重启）；WORKING.md：当前在做的事
                                        └─ desktop_* 工具：用户点“好的”后才动手，先写撤回日志
```

**核心原则：视觉上下文由 VISTA 管，不要自己再造一份。** 历史画面、回看、记忆、上下文交接都是 VISTA 的原生能力；我们只提供“环境”（屏幕）和“动作”（桌面工具）。

## 目录与职责

| 路径 | 作用 |
|---|---|
| `src/openlookout/vista/` | VISTA（MIT，来自 https://github.com/joshhhhhan/VISTA）。核心 `core/` 基本不改；Windows 适配改在 `backends/claude/`（见下） |
| `vista/benchmarks/desktop/brain.py` | **小精灵的大脑**：一个长期运行的 VISTA 会话；屏幕变化时发一轮 `STEP`；管理 GUIDE.md 的保存与恢复、把用户反馈带进下一轮；每轮附上三路事实（【记忆】近期接受/拒绝、【观察】画面计时、【系统】C盘/内存） |
| `vista/benchmarks/desktop/watching.py` | **画面计时事实（通用）**：同一屏停了多久、卡没卡、来回翻、刚完成一个阶段、人走没走。不含任何场景白名单——画面里是什么由 VISTA 视觉上下文判断 |
| `vista/benchmarks/desktop/systemfacts.py` | **视觉外事实（通用）**：C 盘/内存/占资源进程。视觉看不见的问题只有这条线 |
| `vista/benchmarks/desktop/memory.py` | **跨轮记忆摘要**：他接受过/拒绝过的 topic（近 7 天），每轮一句话，防止换说法再提 |
| `vista/benchmarks/desktop/profiles.py` | 角色、场景（陪读书/写代码写报告/修电脑/桌面整理）、用户画像规则、反馈规则、动手边界——**产品行为主要改这里的提示词**；场景是数据（`SCENES` 字典），不是代码分支 |
| `vista/benchmarks/desktop/session.py` | `DesktopSession`：一帧屏幕 = 一个 CURRENT 观察；`companion` 工具的处理 |
| `vista/benchmarks/desktop/actions.py` | `desktop_*` 工具（只读进程查看、挂起、结束、撤销）和 `companion` 工具定义；先写撤回日志再动手；前台/系统/安全进程拒绝 |
| `vista/benchmarks/desktop/cli.py`、`run.py` | 一次性桌面任务入口（用户点“好的”后的执行也可走这里） |
| `src/openlookout/sprite/proactive/live.py` | **监督进程 + 窗口**：拉起并管理 brain 和 GUI；**热更新**（见下） |
| `sprite/proactive/dialog.py` | 点小精灵弹出的对话框（反馈入口） |
| `sprite/proactive/feedback.py` | 用户对小精灵说的话，写入 `perceive/feedback.jsonl` |
| `sprite/proactive/help.py` | `publish()` / `record()`：把一条话写成 `offer.json` 并记录；其余旧判断逻辑已被 brain 取代 |
| `sprite/proactive/provider.py` | 供应商配置读取（地址、协议、模型、key） |
| `sprite/gui.py` | 小精灵像素形象与气泡（既有） |
| `sprite/proactive/{perceive,understand,trigger}.py` | 早期的“采集/理解/资源触发器”版本，**保留作参考**，当前不在监督列表里 |
| `sprite_home/`（已 .gitignore） | 运行时数据：`perceive/`（offer、offers.jsonl、feedback.jsonl、日志）、`companion/GUIDE.md`（用户画像）、`bin/`（Linux 版 Claude 二进制）、`brain.log` |

## 一轮是怎么走的

1. `brain.py` 每 2 秒取屏；缩略图差异 ≥ 3% 且距上轮 ≥ 20 秒、或有新用户反馈、或每 10 分钟心跳，就开一轮。
2. 屏幕作为新的 `CURRENT` 观察交给 VISTA；用户反馈（说的话、对提议的“好的/不用”）以文字附上，**只作权衡**。
3. 模型（经 Claude Code → mimo）看画面，必要时 `history` 回看，更新 WORKING.md/GUIDE.md，最后**必须**调用 `companion`：
   - `quiet`：安静（绝大多数轮次应该是这个）
   - `companion`：一句朋友式的话，不带按钮
   - `offer`：具体提议，窗口显示“好的 / 不用”
4. 用户点“好的” → 交给桌面任务执行（`desktop_*` 工具）；每个改动先写撤回日志；气泡带“撤销”。

## 热更新

- 监督进程 `live.py` 每 2 秒检查 `sprite/proactive/*.py`、`vista/benchmarks/desktop/*.py`、`sprite/gui.py` 的修改时间；有改动就重启全部子进程（brain 和窗口），并写 `perceive/supervisor.log`。
- **注意**：只重启子进程。改了 `live.py` 里的 `CHILDREN`（子进程表）本身，必须**整体重启监督进程**，否则新增的子进程不会被拉起。
- 子进程退出会自动拉起。

## 怎么跑

前置：Windows、Docker Desktop 已运行、Python 3.11。

```
cd src\openlookout
python -m sprite.proactive.live            # 启动监督进程（brain + 窗口），热更新
python -m vista.benchmarks.desktop.brain   # 只跑大脑（调试）
```

首次需要：
1. 构建镜像：`docker build -f vista/Dockerfile.claude-player -t arc3-claude-player:0.1 vista`
2. Linux 版 Claude Code 2.1.220 放到 `sprite_home/bin/claude-linux-2.1.220`（官方安装脚本在 WSL 里装，再复制；项目不分发它）。
3. 复制 `sprite/proactive/provider.example.json` 为 `provider.json`，填接口地址、协议、模型名（不含 key，可以进 git）；复制根目录 `.env.example` 为 `.env`，填 `SPRITE_API_KEY=你的key`（`.env` 已 .gitignore）。key 只通过环境变量或 `.env` 读取，统一走 `sprite/proactive/provider.py` 的 `load_provider()`，不要在别处自己读。

## 对 VISTA 做过的 Windows 适配（直接改了源码）

都在 `vista/backends/claude/`：
- `runner.py`：`claude_version()` 在 Windows 通过 player 容器探测版本；容器 uid/gid 在 Windows 用 `1000`；Windows 上工具通道改走 `127.0.0.1` TCP，容器经 `host.docker.internal` 连回（Linux 仍用 Unix 套接字）。
- `mcp_host.py`、`mcp_bridge.py`：配合上面的 TCP 传输。
- `provider.py`：新增 `MIMO_PROVIDER`（Anthropic 兼容端点）；`launch.py` 增加 `--provider mimo`。

## 硬规则（所有 agent 必须遵守）

1. **不删除用户文件，不绕过任何安全检查/权限/钩子，不结束用户正在用的程序。** 动手的事必须先写撤回方式。
2. **用户反馈只作权衡，不是命令**（见愿景）。拒绝过的提议不换说法再提。
3. **宁可安静。** 误打扰比漏提醒代价高；拿不准就 `quiet`。
4. **不要自研 VISTA 已有的能力**（视觉记忆、回看、笔记、上下文交接、回合循环）。优先用开源原实现，迫不得已才自写。
5. **隐私**：屏幕截图只在本机和配置的模型服务之间流动；`sprite_home/`、`.env` 不进 git；不要把真实 key 写进仓库、配置文件或对话。
6. 写文件时注意：用编辑工具写含 `\n` 的 Python 字符串，**不要用 shell 内联脚本拼**（反复造成转义错误）。

## 状态（诚实版）

**已验证**：VISTA 持续会话多轮循环；`history` 回看前一轮画面；companion 工具产出陪伴语和提议；热更新；窗口进程可拉起；
通用事实三线（画面计时 `watching` / 视觉外 `systemfacts` / 反馈记忆 `memory`）共 40 个测试通过，本机实测两条线在安静环境下都返回空串（宁可安静）。

**未验证 / 待做**：
- 点“好的”后的**执行链路**（桌面任务 → 结论回显 → 撤销）没有端到端跑过。
  （2026-10-13 已打通一半：同意门与选项 UI 有真实点击的端到端测试，`accepted`/`rejected`
  真的落进 `outcomes.jsonl`；但测试里 `run_offer` 是打桩的，**真跑一次桌面任务**仍未验证。）
- **同意门管不到 brain 自己那条路**：brain 的常驻观察循环直接持有 `desktop_trim` /
  `desktop_reclaim` / `desktop_tidy` 等改动工具，不经过 offer，所以「必须点头才动手」
  目前只约束 offer 这一条路径（决策记录里可见 36 次 brain 直接改动）。
- **GUIDE.md 用户画像**：机制已接好，但模型尚未形成有内容的画像（仍是初始值），需要观察它是否真的会写。
- 场景提示词（陪读书三档/写代码/修电脑/桌面整理）刚按“通用机制”重写，**还没有真实场景验证**。
- 开口时机的质量没有数据：需要真人使用几天，看 `outcomes.jsonl` 里提议的接受/拒绝比例
  （`accepted`/`rejected` 两个词已经能落账了，见 `sprite/proactive/test_offer_consent_e2e.py`）。
- 费用：每轮带图，持续运行成本不低；需要决定频率上限与模型。
- 窗口气泡与按钮的实际显示，需要有屏幕的人确认。
- 环境：C 盘仅剩 ~29MB，`sprite/` 大量测试因 `could not create`（磁盘满）失败/报错，与本次改动无关，清理后才能跑全套。

## 适合并行认领的任务

- **场景**：在 `profiles.py` 里增加新场景（写作、写代码、看视频、会议、桌面杂乱等），每个场景写清楚“时机对的标志”和“该说什么/不该说什么”。
- **用户画像**：设计 GUIDE.md 的结构与更新规则；验证它跨重启保留。
- **执行与撤销**：打通“好的 → 执行 → 汇报 → 撤销”，并给 `desktop_*` 工具加更多安全的能力。
- **评测**：用录屏/截图回放评估“该说/不该说”的准确率与打扰率（参考 π-Bench、ProPerSim 的思路）。
- **窗口体验**：气泡、对话框、陪伴状态动画（`sprite/gui.py`、`dialog.py`）。
- **成本与频率**：触发条件、缩略图阈值、心跳、模型选择。

## 协作约定（多 agent · GitHub）

仓库：`github.com/123456342g-lang/openlookout`（私有，公开发布时翻转）。分支 `main`。

**铁律四条**（2026-10-13 教训：两个代理同时写 brain.py，互相覆盖，烧掉四十分钟）：

1. **隔离** —— 一个 agent 一个分支（`fix/…` / `feat/…` / `chore/…`），禁止直推 `main`。
   并行改同一仓库时用 `git worktree add ../openlookout-<任务名>` 各拿独立工作区，杜绝文件互踩。
2. **挂牌** —— 动共享文件（`brain.py`、`profiles.py`、`runner.py`、`live.py`、`session.py`）前，
   先在对应 issue 里认领；同一文件同时只允许一个 agent 改。没挂牌就等于没开工。
3. **队列** —— 任务全部挂 issue（带优先级标签）；agent 做完关 issue，附验证证据
   （测试输出、日志行、`file:行号`），不许只写"已完成"。
4. **闸门** —— 所有合并走 PR，由主理人执行；测试不过不合并。
   注意：GitHub 免费**私有**仓不提供 required-review 分支保护（API 403，需 Pro 或公开），
   私有期闸门靠本协议 + 主理人合并；**公开发布当天开启分支保护**（见 issue 清单）。

GitHub 操作约定：
- 提交信息写清"改了什么、为什么"，关键判断附 `file:行号` 证据。
- 提交前必跑：`git grep -nE "tp-|sk-ant|SPRITE_API_KEY="` 不得出现真实密钥（`.env.example` 只能是占位符）。
- `.env`、`provider.json`、`sprite_home/` 永不入库（已 .gitignore）；截图/录屏只在本机与配置的模型服务间流动。
- 认领与进度写在 issue；根目录 `STATUS.md` / `TASKS.md` 是给项目负责人看的状态板，不是 agent 的工作队列。
- 外部动作（公开发布、提 issue 到别的仓库、发帖）先问项目负责人；内部动作（读、扫、写分支、跑测试）自主做。
