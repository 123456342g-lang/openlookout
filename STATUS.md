# 协作看板（认领 / 进行中 / 已完成）

> 豆包、WorkBuddy、Grok Bot 都只改这一份。认领：在「谁」列写自己名字，把状态改成进行中；完成：改成已完成并在进度区补一行验收。

| 状态 | 任务 | 文件范围 | 谁 |
|---|---|---|---|
| 进行中 | T1 真实 Windows 采集与进程控制 | sprite/winprobe.py, procctl.py, sysstate.py | opencode |
| 已完成 | T2 内存告急演示 | sprite/demo_live/, scenarios/resource.py, pressure.py | MainAgent |
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
| 进行中 | T-GrokBot 通用大脑/网络取证插件 | investigate 插件，禁止场景流水线 | Grok Bot + 待豆包/WorkBuddy |

## 认领规则
1. 先改上表状态再动文件；同一文件范围同时只能一个 agent。
2. 完成后在下方「进度」追加一行：日期、谁、验收命令与结果。
3. 不要改别人正在进行中的范围；要协作先留言。

---

打开完整任务说明见 [TASKS.md](TASKS.md)。
