# 02b 外部对标、定位楔子与分发/合规策略

> 本卷是 `docs/strategy/README.md` 已收敛决策的**外部压力测试**，不是继承它。
> 任务要求：用外部证据检验「保留 A（实时环境型）、归档 B（异步洞察型）」这个取舍。
> 采集时间：**2026-10-12 08:10–09:05（Asia/Shanghai）**。
> 检索方式说明：本机 `web_search`/`web_fetch` 工具因沙箱 DNS 策略被拒（`non-public IP address`），实际检索经 PowerShell `Invoke-WebRequest` 直连完成；搜索后端为 `search.brave.com`（后期限流，故第 3–4 节改用官方文档直取）。
> 标注约定：**【事实】**＝有来源可核；**【推断】**＝我基于事实的判断，可被证伪。

---

## 0. 结论摘要

1. **A 的定位是一块已经被大厂占满、且被大厂自己证明会翻车的地。** 2024-05→2026 的 Recall 风波是消费级「常驻截屏」这条路线最大规模的一次公共实测，结论**不是**"技术不行"，而是"**说不清为什么要有它 → 用户读成监控 → 卸载**"。**【事实】**
2. **B 的定位不在同一张竞品地图上。** Rewind/Limitless 的答案资产被 Meta **收购并停售/停服**（2025-12）；Cluely 的商业模式被其创始人**公开承认虚报 ARR 约 35%**。这两个事实说明：**"记忆/洞察"这个方向的需求是真的（有人肯付 $99 硬件 + 订阅），但"把原始数据都交给我"的权力姿态不成立。** B 的"原始数据不出本机 + 已验证成品 + 每日 ≤3 张"恰好是这条路径上的空档。**【事实 + 推断】**
3. **但最重要的外部发现对 A 和 B 都不利：学术界已经把"主动"拆成了"能不能在用户说出口之前解决隐藏意图"，并有基准测了它——现有最好模型在这个指标上仍然很差。** `π-Bench` 的核心指标 Proc（隐藏意图被主动解决的比例）被单列，正是因为"完成度"和"主动性"是**两件事、会背离**（arXiv:2605.14678）。**【事实】** 这条同时是 A 的死刑判决书和 B 的说明书。
4. **我的结论与卷宗相反：先做 B，把 A 的安全层留下、把 A 的"常驻截屏"砍掉。** 理由不是"B 更酷"，而是：**唯一无法用工程补的那种失败模式——镜头上没打码的常驻截屏——A 全占了；而 B 已经把"如何证明有用"做成了产线产物。** 详见 §5。
5. **本建议的推翻条件写在 §6**，其中最容易先发生的两条是：B 的卡片在 14 天内触达却零行动，或 Microsoft 把 Copilot Memory 升级成"已验证成品交付器"。

---

## 1. 事实核验：卷宗里会漂移的数字，现在是多少

（不是外部情报，但本卷要拿它算单位成本，必须先重测。全部只读。）

| 量 | 卷宗记录（2026-10-12 07:19–08:00） | 我实测（2026-10-12 08:17） | 判定 |
|---|---|---|---|
| `child_brain.log` 模型段数 | 389 / 390 段 | **474 段** | 持续增长中，**+22%** |
| 累计输入 token | 1,821,155 | **2,524,408** | **+38.6%** |
| 累计输出 token | 278,637 | **369,416** | **+32.6%** |
| 单段输入 token（中位/最大） | 3,979 / 16,304 | 未重算（同量级） | — |
| 日志跨度 | 40 小时 | 创建 10-10 17:55 → 末写 10-12 08:17，约 **38.4 小时** | 一致 |
| `offers.jsonl` 条数 | 291 | **292** | 已停涨（末写 08:06） |

**成本重算（用本卷 §4.1 的官方单价）：**

| 档位 | 输入单价 | 输出单价 | 474 段累计成本 |
|---|---|---|---|
| 低档（gpt-6-luna / Haiku 5.5） | $0.10 / M | $0.50 / M | **$0.437** |
| 中档（gpt-6.1-sol / Sonnet 5.5） | $2.00 / M | $10.00 / M | **$8.74** |
| 高档（gpt-6-astra / Fable 5.1） | $10.00 / M | $50.00 / M | **$43.7** |

**每活跃小时成本**：474 段 ÷ 38.4 h ≈ **12.3 段/小时** → 低档 **$0.011/小时**、中档 **$0.227/小时**、高档 **$1.14/小时**。**【事实（单价与 token 数）+ 推断（小时折算按日志墙钟跨度，含空闲时段，属下限）】**

> **这确认了卷宗"钱不是瓶颈"的判断，而且比我预期的更极端**：即使把 A 跑到高档模型，也只有约 $1.1/活跃小时。**所以"token 成本"在读这份取舍时应当被降权**——它是一个可以被买单的 number，不是一个定位理由。真正的否决项是 §4.2 的合规与 §3 的接受率。

---

## 2. 外部对标（每条：能力边界 / 隐私姿态 / 商业模式 / 真实差评）

### 2.1 Microsoft Recall（Copilot+ PC 常驻截屏）

**【事实】时间线与能力边界**
- 2024-05-20 公布，原定随 Copilot+ PC 于 2024-06-18 上市；2024-06 起在安全与隐私专家**持续、猛烈的批评**下改为**默认关闭（opt-in）**，随后多次延期（来源：The Record, `https://therecord.media/microsoft-reverses-course-recall-opt-in`；Malwarebytes, `https://www.malwarebytes.com/blog/news/2024/06/microsoft-recall-delayed-after-privacy-and-security-concerns`）。
- 安全研究员 Kevin Beaumont 的实测标题即结论：blog 公开测试其"安全与隐私影响"，并指出该功能在闭门小组中开发、**未经过恰当的隐私与安全评审、未进 Windows Insider 测试**（DoublePulsar, `https://doublepulsar.com/microsoft-recall-on-copilot-pc-testing-the-security-and-privacy-implications-ddb296093b6c`）。
- 宾夕法尼亚大学信息安全办公室 2025-04-14 亦发布针对当时可用版本的警告（经 GeekWire 报道，`https://www.geekwire.com/2024/one-year-after-its-rocky-launch-microsofts-windows-recall-still-raises-security-red-flags/`）。
- 2025-04-25 才正式面向主流用户推出（PCMag, `https://www.pcmag.com/news/windows-11-microsoft-finally-launches-its-controversial-recall-feature`）。**从公布到上市用了 11 个月**，其中大部分时间在补安全。

**【事实】隐私姿态**：从"默认开"退到"opt-in + 可暂停 + Windows Hello 加密 + 本地向量库"。这是一次**由舆论倒逼的架构修改**，不是原始设计。

**【事实】真实差评点（不是媒体转述，是用户自己的话）**
- **能耗**：r/Windows11 "Recall to me is great but battery hungry"（`https://www.reddit.com/r/windows11/comments/1kq2fh8/recall_to_me_is_great_but_battery_hungry/`）——用户实测开启后卸载，续航从约 10 小时恢复；回帖"我也注意到了，续航感觉像普通笔记本"。同主题 r/Surface 讨论中多位用户因"电池消耗大"选择不开。
- **搜索到的东西不对/无用**：多条讨论集中在"它抓了，但找不回来"（如"如果我不知道该搜什么词，它就帮不到我"）。
- **敏感信息被记录**：r/privacy 广为传播的帖子指出 Recall 记录了信用卡号、社会安全号等敏感内容（`https://www.reddit.com/r/privacy/`，2024-05-22 前后，306 赞 / 1604 评论）。
- **官方口径的诚实例外**：也有用户表示真的解决了问题——"帮我找回了一个 3D 打印的设置项和一个看到但没打开过的 URL，这两个搜索以前不可能完成"（r/Surface, `https://www.reddit.com/r/surface/`，2025-04-29）。**这个正面案例极其重要，见 §3 的评分依据。**

**结论（事实层）**：Recall 证明了 **(a) "回到过去某个屏幕"这个需求真实存在**；**(b) "默认常驻截屏"的社会许可不存在**；**(c) 即便补了加密和 opt-in，能耗与检索精度仍是主要差评**。

### 2.2 Microsoft Copilot Vision（显式、会话内共享屏幕）

**【事实】** 2026 年形态为 **opt-in、显式触发、会话边界清晰**的屏幕共享：用户主动让 Copilot 看当前屏幕以解释报错/找按钮/总结图表（Windows Forum, `https://windowsforum.com/`，2026-05-04；`https://windowsforum.com/`，2026-01-13 Windows 11 桌面共享）。
- 微软自身的收敛动作可佐证这条线**在收而非在放**：2026-03 出现 "Microsoft Rolls Back Copilot Surfaces in Windows 11, Focusing on Privacy and Control"（Windows Forum, 2026-03-16）。
- 用户差评（r/privacy, r/Windows11 原帖）：对任务栏新增"共享屏幕"按钮的典型反应是 **"Why would anyone want to do that??"**（r/Windows11，2025-09-19，48 赞 / 52 评论）；"Copilot on Windows 11 is gaining the ability to see and interact with your apps" → **"No thanks"**（r/Windows11，2025-04-04，77 赞 / 274 评论）；r/privacy 有用户称"可以关，但我仍然不信任它，个人电脑我会用 Linux"（2025-10-24，95 赞）。

**结论（事实层）**：**微软自己把"常驻看屏幕"降级成了"用户先开口、再看一次"。** 这是本卷对 A 最直接的一次外部证伪——**头部厂商在同一条路上选择的是 §2.2 的形态，不是 §2.1 的形态。** 而 A 当前做的（常驻、逐帧、无遮挡）比微软已经放弃的版本更激进。

### 2.3 Cluely（"实时环境型"的纯血样本）

**【事实】** 定位："实时教练"，在面试、销售电话、考试乃至约会中给出实时建议；宣传语是 "cheat on everything"（Wikipedia, `https://en.wikipedia.org/wiki/Cluely`；tl;dv 评测, `https://tldv.io/`）。
- **定价**：Free（5 次/天，输出截断）/ Pro **$19.99/月** / Pro + Undetectability **$149.99/月**——最高档的功能是"**在屏幕共享时把自己藏起来**"（Postbeam, `https://postbeam.ai/`）。
- **融资**：2025-04 的 $5.3M 种子（Abstract Ventures / Susa Ventures），2025-06 的 **$15M A 轮（a16z 领投）**，投后约 $1.2 亿（同上）。
- **【事实】真实差评点（且是致命的那一类）**：
  1. **创始人公开承认虚报收入。** Roy Lee 2025-07 公开宣称 $7M ARR，**2026-03-05 在与 TechCrunch 冲突后撤回，承认数字被抬高了约 35%，实际约 $5.2M ARR**（ThePlanetTools, `https://theplanettools.ai/`；Postbeam 同上）。
  2. **合规证书造假。** 有来源称其合规认证由一家**因被指伪造审计证据而被 Y Combinator 除名**的平台出具（tl;dv, `https://tldv.io/`）。
  3. **幻觉**：评测反复提到 AI 编造信息，在专业场景构成重大责任（eesel.ai, `https://eesel.ai/`）。
  4. **伦理反噬**：学术诚信风险"严重且后果不可逆"；创始人本人因作弊被大学开除（eesel.ai / Wikipedia 同上）。
  5. 定位漂移：Reddit 用户评价"从学生的作弊工具，变成企业的笔记应用，但两边都不擅长，是一次身份危机的产物"（r/csMajors，2025-10-31，81 赞 / 286 评论）。

**结论（事实层）**：**"实时环境型"能最快拿到钱，但它的增长策略必然与"可信"发生冲突。** Cluely 的 $149.99 档卖的是"不被看见"，A 的产品若被读成同一类东西，代价是用户信任的永久折价。

### 2.4 Limitless / Rewind（"记忆与洞察"的答案资产）

**【事实】**
- Rewind AI 更名 Limitless AI，推出 **$99 的 Pendant**（持续录制并转写对话与周围环境）+ 订阅（捆绑价 $299–$399，`https://limitless.ai/`）。
- **2025-12，Meta 收购 Limitless**，**立即停售 Pendant**、**关停 Rewind Mac app**，并**阻断欧盟访问**（WinBuzzer, `https://winbuzzer.com/`，2025-12-08；9to5Mac, `https://9to5mac.com/2025/12/05/rewind-limitless-meta-acquisition/`）。团队并入 Meta Reality Labs 做 AI 可穿戴（含 Ray-Ban Meta 智能眼镜）。
- **【事实】差评点**：
  1. **停服后的账单**：有用户报告**在关停后仍被收取两年期订阅费用，且无退款**（r/MacOSApps，经 LUCI 汇总，`https://luci.memories.ai/`）。
  2. **"全录"姿态本身被反感**：r/macapps 高赞评论针对类似产品——"**如果全都是本地的，为什么订阅费这么离谱？**"（对标产品 $95.88/年，2025-08-12）。
  3. 社区出现明确的替代诉求帖："Tired of Rewind.ai's 'record everything' approach? I'm building ... an *intentional* second brain"（r/macapps, 2025-08-12）。
  4. Google Play 上 "Limitless AI Voice Recorder" 评分 **2.9 / 73 票**（`https://play.google.com/store/apps/details?id=...`，经搜索结果页）。
  5. 对创始人诚信的行业性不信任（r/Wellthatsucks 高赞："一个做 ADHD 工具公司的 CEO 被抓到说谎……别把创始人当朋友"，2025-12-07，88 赞 / 1384 评论）。

**结论（事实层）——这条对 B 最关键**：**"从个人痕迹挖洞察"的需求是真的**（有人买 $99 硬件 + 订阅，有人肯做替代品），**但三条做法被判了死刑**：默认全录（权力姿态）、数据上云、停服即弃（无本地可控性）。**B 的"原始数据不出本机 + 可完全本地跑 + 交付成品"正好逐条绕开。** 同时这是一个**警告**：这个方向的公司治理风险极高，Meta/Google 随时可以把它变成一个功能并吞掉。

### 2.5 Google Project Astra / Gemini Live & Apple

**【事实】**
- Astra 的研究能力（屏幕/视频理解）通过 **Gemini Live 的屏幕共享与视频**落地：2025-03 起在 Android 上分批推出，官方确认**支持 Android 10 及以上的任何设备**（Android Police, `https://www.androidpolice.com/geminis-project-astra-live-camera-mode-wont-just-be-a-pixel-exclusive/`，2025-04-02；BleepingComputer, `https://www.bleepingcomputer.com/news/artificial-intelligence/google-geminis-astra-screen-sharing-rolls-out-on-android-for-some-users/`，2025-03-24）。
- 2025-04-17 起**对全部 Android 用户免费**开放相机与屏幕共享（YouTube 官方口径，经 Brave 检索）。
- **能力边界**：智能眼镜"预计最早 2026 年上市"（Android Central, `https://www.androidcentral.com/apps-software/ai/what-is-project-astra`，2025-06-02）——即**桌面/眼镜形态尚未成为产品**。
- **用户差评点**：r/Bard 实测反馈集中在——共享屏幕/相机入口**仅在 Gemini Advanced 订阅下可见，免费账号没有**；整屏共享时"单个应用"选项**不可选**；结束会话后回看，**转录掉了 1–2 个词**；部分用户无法在非 beta 账号拿到功能（r/Bard，2025-03-22，56 赞 / 95 评论）。

**【事实】Apple**：未检索到 2025–2026 有与"常驻截屏 + 主动开口"对等形态的公开产品落地；本卷**不作断言**（避免把传闻当事实）。

**结论（事实层）**：Google 走的是**"会话内的显式共享"**，与微软 §2.2 同向。**大厂在"看屏幕"这件事上的一致选择是：用户先动，AI 再看。**

### 2.6 Ambient / Proactive Agent 的研究与开源（A 的技术底座）

| 工作 | 类型 | **能力边界（关键数字）** | 对 A/B 的意义 |
|---|---|---|---|
| **VISTA**（MIT：Qiushi Han, Keya Hu, Linlu Qiu, Cathy Wu, Kaiming He，2026-10-01） | 研究：视觉 harness | **无损视觉记忆**（原样保留过去观测）+ 模型可主动检索并重组视觉输入。在 **ARC-AGI-3** 上把 Claude Opus 5.0 的 Relative Human Action Efficiency 从 **40.68 提到满分 100.00**，25 个公开关卡全通，动作数比人类首次参与者**少 57.4%**（arXiv:2610.02200, `https://arxiv.org/abs/2610.02200`） | ⚠️ **必须纠正**：**VISTA 不是产品，是 ARC-AGI-3 的评测 harness**。A 的"技术栈是 VISTA"这个说法**在外部证据里找不到对应物**——名称撞了三个不同工作（2610.02200 视觉 harness、2510.15831 视频生成 agent、2605.10579 自我中心协助场景平台）。**A 的技术叙事目前无法外部核验。** |
| **ContextAgent**（Bufang Yang 等） | 研究：主动 agent | "**首个**上下文感知的主动 LLM agent"，不吃手工指令，而是用**开放世界的大规模传感上下文** + LLM 推理做工具增强的主动服务；代码与数据集公开（arXiv:2505.14668, `https://arxiv.org/abs/2505.14668`） | **这正是 A 的学术形态，且开源可用。** 意味着 A 的"技术护城河"是不存在的——底座是公共品。 |
| **ProPerSim**（ICLR 2026） | 基准：**模拟家庭环境** | 用户 agent + 助手 agent 模拟，评"及时、个性化、符合偏好的推荐"（arXiv:2509.21730, `https://arxiv.org/abs/2509.21730`） | ⚠️ **与本项目不在同一域**：A 是**桌面工作**环境，ProPerSim 是**家庭**环境。**在桌面场景上"主动时机"没有现成基准。** |
| **π-Bench**（arXiv:2605.14678，v3 2026-05-19） | 基准：**主动个人助理** | 100 个多轮任务 × 5 类领域人物画像；**核心发现三条：(1) 主动协助仍然很难；(2) 任务完成度与主动性之间有明确区分（会背离）；(3) 前序交互对后续任务的主动意图识别有价值。** 两个指标：**Proc**（隐藏意图被主动解决/被定向提问澄清的比例）与 **Comp**（轨迹是否满足可验证清单）。**排行榜默认按 Proc 排序**（`https://simplified-reasoning.github.io/Pi-Bench/`，`https://arxiv.org/abs/2605.14678`） | 🔴 **这是本卷最重要的一条外部发现**：它把"主动"定义成了一个**可测且与完成度背离**的量。**A 的失败模式（101 条/天但接受率算不出来）正是 Proc 低而 Comp 无法评估。** |
| **GUITester / PROBE** | — | ⚠️ **未能取得可核来源**：检索被限流（HTTP 429），本卷**不作陈述**，标记为**未核项**。 | 需要在后续卷宗中补测 |

**【事实】π-Bench 的一句话警告**（原文）："Systems built for real users should preserve user agency, protect private data, and involve domain experts when decisions carry real-world consequences."

**结论（事实层）**：**(a) "主动"有公共基准，且现有模型表现差；(b) A 的技术底座是开源公共品，不构成差异化；(c) 桌面场景的"主动时机"没有基准，ProPerSim 不适用——这既是 A 的风险（不知道怎么测），也是 B 的机会（B 自己造了可验证层）。**

---

## 3. 楔子对比：A vs B 同表打分

**评分说明**：0–5 分，**分越高越好**。所有分数都是**【推断】**，依据列必须指向 §1/§2/§5 的**【事实】**。

| 维度 | A 实时环境型（常驻看屏幕→主动开口→可撤回动手） | 分 | B 异步洞察型（本机痕迹→未察觉需求→已验证成品） | 分 |
|---|---|---|---|---|
| **差异化** | 与 Recall / Copilot Vision / Gemini Live 正面重叠。唯一独有点是**可撤回的本地动手**（`undo.jsonl` 7 条、隔离区 277 条）——但这正撞上微软"Rolls Back Copilot Surfaces"的退却方向；技术底座（ContextAgent）本身开源。 | **2** | "已验证成品 + 原始数据不出本机 + 每日 ≤3 张"三者组合，在检索到的产品里**没有对应物**（Rewind/Limitless 已停，Cluely 是另一个域）。 | **4** |
| **可信度/可验证性** | 🔴 **无基线**：292 提议 vs `feedback.jsonl` 8 行 → **接受率至今无法计算**；π-Bench 已证明"完成度"与"主动性"会背离，而 A 只测完成度、测不到主动性。 | **1** | 卡片**自带三元组**（行为证据/可量化指标/已验证成品路径 + 验证记录），`runs/local/` 有真实产物：gate 从 **10 个候选中拒掉 8 个**、7 个 `verified`、产物落盘（`v1_cards.json` 18.8 KB、`v1_inbox.html` 6.9 KB、含 `artifacts/`）。**"证明有用"是流程的一部分，不是事后补的。** | **4** |
| **隐私/合规风险** | 🔴 **公开即引爆**：2040 张截图 / 257.3 MB 本地囤积，**逐帧全屏 base64 上传、零遮挡逻辑**；等于把"第二方个人信息"交给外部模型通道。对照 Store 政策 10.5.2/10.5.3（向第三方发布个人信息**必须**在界面内取得 opt-in 同意，并须提供撤回机制）——**当前实现按字面不达标**。 | **1** | 设计上**原始数据不出本机**，`--no-llm` 可完全本地跑；脱敏（`deid.py`）后才可选上云。风险面主要是**读历史记录本身的授权**，而非"持续向第三方直播屏幕"。 | **4** |
| **单位成本** | 474 段 / 38.4 h → 低档 **$0.011/h**、中档 **$0.227/h**、高档 **$1.14/h**。**钱不是问题。** | **4** | 每日批处理 + 10 个候选过闸 → 每天 ≤3 张卡；同量级下更低（推断：**低一个数量级**）。 | **5** |
| **可分发性** | Docker 前置（虽 `README.md` 4.2 认定容器通道已坏、应去掉）+ 常驻截屏需解释授权 + PyInstaller 打包存在 AV/SmartScreen 误报面。 | **2** | 纯 Python + 可选 `openpyxl`/LibreOffice/Chrome；无 Docker、无常驻权限。打包与签名路径干净（§4.1 已验证成本 $9.99/月）。 | **4** |
| **冷启动** | **需要"养"**：要让模型"看准时机"必须先积累足够多的屏幕历史，且期间持续产生打扰。 | **2** | **Day-1 可用**：`backfill_win --days 90` 直接从**用户已有的**浏览记录/最近使用/Office 文件/git 回填，**10 分钟内看到第一张卡**（V1.md 验收 1）。 | **5** |
| **竞品密度** | 🔴 **极密**：Recall、Copilot Vision、Gemini Live/Astra、Apple Intelligence、Cluely——**五个都比你大**。 | **1** | 稀疏：Rewind（已死）、Limitless Pendant（已停售）、Otter/Granola（只做摘要，不做成品）、Copilot Memory（只做检索）。 | **3** |
| **合计** | | **13 / 35** | | **29 / 35** |

**对 A 的诚实辩护（必须写，否则这张表是自我说服）：**
1. **A 是唯一有真实运行时证据的线。** 38.4 小时的实时回合、292 条提议、真实的用户原话纠正（"看起来好长看不懂"）、7 条撤销记录。B 的产物**全部集中在 2026-10-09 一天**（`runs/` 目录 11 个子目录，时间戳 10-09 14:15 → 10-10 06:46），是**一次性冒烟，不是持续运行**。
2. **A 是唯一有像样安全层的线。** `sprite/risk.py` 的分类器 + 隔离区 + `eval_all` 的 461 陷阱 / 0 误操作——B 没有对抗评测。
3. **B 的"已验证"是同一条流水线自己验的。** 没有用户确认闭环（`feedback_rules.json` 只是降权表，1,138 字节），存在**自我确认**风险：门控自己判"我找到了一个惊喜"，而不是用户判。

**因此本表给出的不是"B 完胜"，而是"两条线的强项互补"**：A 有的（动作库 + 安全层）是 B 缺的；B 有的（可信度结构 + 可分发 + 冷启动）是 A 缺的。这就直接推出了 §5 的建议形态。

---

## 4. 分发与商业

### 4.1 Windows-first 打包与签名（**已实测成本**）

**【事实】** Azure Trusted Signing（Azure Artifact Signing）官方零售价（经 Azure Retail Prices API 直取，`https://prices.azure.com/api/retail/prices`，产品 `Trusted Signing`）：

| 档 | 月基价 | 内含签名数/月 | 超出单价 |
|---|---|---|---|
| **Basic** | **$9.99** | 5,000 | **$0.005 / 次** |
| **Premium** | **$99.99** | 100,000 | $0.005 / 次 |

产品文档：`https://learn.microsoft.com/en-us/azure/trusted-signing/overview`；定价页：`https://azure.microsoft.com/en-us/pricing/details/trusted-signing/`。

**【事实】Trusted Signing 的一个关键优势**：它是**托管式**证书服务，省掉了传统 EV/OV 代码签名证书的**硬件令牌与私钥保管**流程，且 Basic 档 $9.99/月（5,000 次签名）**对一个小项目完全够用**。

**【推断】对 A / B 的不同含义**：
- 对 B：$9.99/月 + PyInstaller/Nuitka 打包 = **一个可在两周内完成的工程任务**。
- 对 A：同样便宜的签名**不能解决 Docker 前置**。去 Docker 是 `README.md` §4.2 已经认定的工作，**且要先做**——因为选 Docker 就等于选"要求用户先装 Docker Desktop"，而 Docker Desktop 的商业授权按规模收费，把它做成分发前置会同时引入法律与转化两层摩擦。
- **SmartScreen 声誉是分开的、会累积的**：即使买了签名，新证书仍有一段"未知发布者"提示期。**这解释了为什么"免 Python 打包"必须早做而不是 M4 才做**：声誉需要时间养，而它不是代码任务。

### 4.2 隐私与合规要点（**这是 A 的真正否决项**）

**【事实】Microsoft Store 政策 10.5 Personal Information**（`https://learn.microsoft.com/en-us/windows/apps/publish/store-policies`）：
- **10.5.1** 访问/收集/传输个人信息的应用**必须**维护隐私政策，并在 Partner Center 提交 `privacy policy URL`；政策须说明**访问了什么、如何被使用/存储/保护、向哪些类别的第三方披露、用户有哪些控制权**，且**必须随功能更新保持最新**。明确点名"**Desktop Bridge 与 Win32 产品**"属"固有可访问个人信息"的类型，**必须始终有隐私政策**。
- **10.5.2** 通过产品向**外部服务或第三方**发布用户个人信息，**必须先取得 opt-in 同意**；"opt-in"定义为：在**产品 UI 内**取得明确授权，且你已说明如何被访问/使用/共享、披露给哪些类别的第三方，**并提供用户日后可撤回（opt-out）的界面机制**。
- **10.5.3** 若发布的是**非本产品用户**的个人信息，须取得**书面明示同意**，且必须允许其随时撤回。

**【事实】GDPR 侧**：DPIA（数据保护影响评估）在 **Art. 35(1)** 下于"很可能对自然人权利与自由造成高风险"时要求，**尤其在使用新技术时**；Art. 35(3) 强制三种情形，其中包含**大规模系统性监控**；**当满足 EDPB 九项高风险准则中的两项或以上时，DPIA 通常必须做**（Microsoft Learn `https://learn.microsoft.com/en-us/compliance/regulatory/gdpr-data-protection-impact-assessments`；recordinglaw.com `https://recordinglaw.com/` 汇总）。

**【推断】把上面两条对着 A 的当前实现：**
| A 的现状 | Store 政策 | GDPR |
|---|---|---|
| 常驻截屏 + 逐帧全屏上传到外部模型通道 | **10.5.2 直接相关**：屏幕像素里含第三方个人信息（邮件、聊天、医疗账单、客户名单）→ 需要 UI 内 opt-in + 撤回机制 | 可能触发 Art. 35(1)（新技术 + 高风险）；若面向 EU 用户，**DPIA 很可能必须做** |
| 无遮挡逻辑 | 满足不了"已说明共享了什么" | 数据最小化原则冲突 |
| 2040 张截图本地囤积 257 MB | 隐私政策须说明存储与保护方式 | 存储限制原则需要留存策略 |
| 用户无法证明"它没上传我的密码管理器窗口" | 撤回机制存在但**不可验证** | 透明度要求 |

**【事实】中国的个人信息保护法（PIPL）**：⚠️ **官方正文页未能取得**——`flk.npc.gov.cn` 返回 200 但正文由 JS 渲染（仅 534 字节骨架），`www.gov.cn/xinwen/2021-08/20/content_5632486.htm` 返回 404，`www.npc.gov.cn`/`www.cac.gov.cn` 在本机网络下 TLS/解析失败。**故本节只给检索结论、不给逐条条文引用**，标记为**待核**。可核对入口：`https://flk.npc.gov.cn/`（国家法律法规数据库）。
- 【推断，依据检索到的通行解读】PIPL 体系对屏幕录制的核心约束与 GDPR 同构：**告知—同意**、**最小必要**、**单独同意**（敏感个人信息）、**本地化与跨境传输**评估。**A 的"逐帧上传"在中国法域下比在 GDPR 下更危险**，因为跨境传输还需满足额外条件。

**【事实】应用商店/法律的其他要点**：
- 屏幕录制在美国属**各州法**覆盖；加州 **Cal. Penal Code 632** 主要管音频，**不直接管屏幕视觉捕获**；伊利诺伊 **BIPA** 要求采集生物识别标识前取得**书面同意**。**工作场景下**雇主须在采集时或之前披露所收集个人信息的类别（E-Monitor, `https://employee-monitoring.net/compliance/is-screen-recording-employees-legal/`，2026-03-31）。**【推断】这意味着：如果 OpenLookout 未来被用于公司设备，隐私义务会从"个人授权"升级为"雇主披露"。**
- **Microsoft Store 产品政策 10.1**（Distinct Function & Value; Accurate Representation）要求元数据如实反映功能与**重要限制**；**11.16 Live Generative AI Content** 单独成条。**【推断】A/B 提交商店时都必须把"会看屏幕/会读你的浏览历史"写在明面上，靠模糊描述过审是政策明确禁止的。**

### 4.3 开源 vs 付费

**【事实】市场给出的价格锚**：Limitless Pendant $99 硬件 + 订阅（捆绑 $299–$399）；Cluely Pro $19.99/月、Pro+Undetectability $149.99/月；Limitless 免费档给 1,200 分钟/月转写。**【推断】"个人 AI 记忆"这个品类的消费者价格锚在 $10–$20/月**，而 Cluely 的 $149.99 档证明**存在愿意为"不被看见"付溢价的细分**——但那个细分与"可信助手"的品牌是互斥的。

**【推断】具体建议**：
- **B 的核心应该是开源的。** 理由有三：(1) "原始数据不出本机"这个主张**必须可核验**，唯一可信的证明方式是源码可审计；(2) 竞品密度低但对手是大厂，"可审计的本地优先"是唯一大厂**结构上无法复制**的卖点（它们的商业模式要求数据回传）；(3) 分发冷启动成本因此降到近零。
- **收费点放在"结果"而不是"能力"**：卡片生成、逃脱趣门控的候选挖掘、产物构建可以免费；**每日超过 3 张、跨机同步、企业策略模板**收费。这与 π-Bench 的 Proc 指标同构——**你卖的是"命中率"，不是"能看到多少"。**
- **A 的反面教训**：Cluely 的定价金字塔建立在"隐藏"上，一旦被平台（会议软件/学校）针对性封堵，$149.99 档立刻归零。**不要做任何建立在"不被发现"上的功能。**

---

## 5. 结论：先做哪一条、另一条怎么处置

### 5.1 建议（与卷宗相反）

> **先做 B。但不是原文的 B——把 A 的动作库与安全层作为"手"接进 B 的"已验证成品"里，砍掉 A 的常驻截屏。**
>
> 用一句话说：**做 B 的"验证过的交付"，用 A 的"可撤回的执行"。**

### 5.2 为什么是这样，理由按分量排序

1. **A 的失败模式里有一种是工程修不回来的。** 打扰（`feedback`）可以靠闸门修；延迟可以靠通道修；**但"常驻截屏 + 逐帧上传 + 无遮挡"是权限设计问题**——它一旦以当前形态发出去，用户的判断就定型了，Recall 用 11 个月的延期与一次 opt-in 回退买到的就是这条教训（§2.1）。**这是"先做哪条"的唯一决定性理由：A 若以现状首发，赌上的是整个产品的社会许可。**
2. **A 的技术叙事在外部无法核验。** VISTA 是 ARC-AGI-3 的视觉 harness，**不是产品**；而 A 真正的能力底座 ContextAgent 是**开源公共品**（§2.6）。**一个无法外部核验、且底座是公共品的技术栈，不能支撑"保留 A"这个决策。**
3. **A 的"有没有用"至今没有基线，而 π-Bench 已经把这件事变成了一个有名字的指标。** 292 条提议对 8 条反馈——**不是数据不足，是没有采集"主动性"的埋点**。π-Bench 的 Proc 指标（隐藏意图被主动解决的比例）是现成的度量方式（§2.6）。**在补上这个埋点之前，任何"M2 闸门做完了"的验收都是自评。**
4. **B 的"证明有用"是内建在交付物里的。** 卡片必须同时有行为证据 + 可量化指标 + 已验证成品路径，否则不出卡；`runs/local/gate.json` 实测从 10 个候选里拒掉 8 个。**"拒掉"是这条线最健康的一个信号**——它说明门控真的在挡东西，而不是恰好没东西可发。A 目前的"拦截计数"还是 0（卷宗 M0.3 的门就是要求它 > 0）。
5. **B 能吃到 A 拿不到的"Day-1 价值"。** 用户装完 10 分钟就能看到第一张基于**他自己已有历史**的卡；A 需要养。**冷启动差距直接决定首日留存的量级。**

### 5.3 具体怎么处置两条线

| | 动作 | 理由 | 可证伪的门 |
|---|---|---|---|
| **B** | **升为主线**，补两件事：(a) 把 `sprite/risk.py` 分类器 + 隔离区 + `eval_all` 接进 B 的产物交付路径；(b) 把"用户对卡片的行动"落库（接受/忽略/已解决三态），让 B 也有一条可算的接受率 | B 缺"手"和"对抗评测"；它当前的 `feedback_rules.json`（1,138 字节）只是降权表，没有闭环 | 连续 14 天，每天 ≥1 张卡，且**卡片触发行动的比率可计算** |
| **A 的保留部分** | 保留 `sprite/risk.py` 分类器 + 隔离区 + `eval_all`（461 陷阱 / 0 误操作）作为**全项目唯一的动作安全层**；保留 `undo.jsonl` 撤销机制 | 这是全项目唯一被对抗验证过的资产，也是 B 最缺的 | 任意"动手"路径都在同一闸门之后，且 `eval_all` 陷阱集覆盖它 |
| **A 的砍掉部分** | **停止"常驻截屏"作为默认档**。若必须保留感知，改为 **Copilot Vision 形态**：用户显式触发的会话内共享，会话边界清晰，不进持久库 | 微软自己已经这么退了（§2.2）；这是唯一能同时保住"看"和"社会许可"的形态 | 本地截图库在 7 天内不再增长（当前 2040 张 / 257.3 MB） |
| **A 的技术叙事** | 停止把"技术栈是 VISTA"当卖点；如果确实用了 ContextAgent，就**直接引用 ContextAgent 的论文与开源仓库** | 无法核验的技术叙事在任何尽调下都会被揭穿（§2.6） | 对外材料里每个技术名词都能指向一个可访问的来源 |
| **归档线** | `lookout/` 从"归档"改为"**升为 B 的实现主体**"；`src/openlookout/README.md` 与 `V1.md` 作为 B 的规格文档保留 | V1.md 已经写好了验收（Day-1 出卡、卡片三件套、每日 ≤3、原始数据不出本机），规格是现成的 | 仓库只有一条入口命令 |

### 5.4 如果只能改一件事

> **把 A 的默认档从"常驻截屏"改成"用户先开口"。**

理由与卷宗 §六 取同构：这是唯一一个**外部已有大规模反例（Recall）、头部厂商已自行回退（Copilot Vision）、且不可用工程事后弥补**的决策点。其余所有问题（闸门、埋点、动作库、打包）都是可以在保留产品的前提下逐步解决的工程债；**这一条不是债，是许可。**

---

## 6. 这个建议在什么条件下会被推翻

**写清推翻条件，避免自我说服。** 以下任意一条成立，就应当重新考虑"先做 B"：

| # | 推翻条件 | 为什么它会推翻 | 怎么观测 |
|---|---|---|---|
| **F1** | **B 的卡片在 14 天内触达却零行动**（用户看了，但没有任何卡片被采纳/执行） | 那就证明"用户自己说不出、也没察觉的需求"这个楔子是**知识分子的自嗨**——需求不存在，验证做得再漂亮也没有价值 | 卡片三态埋点：`accepted` 比率连续 14 天为 0，且不是"没看到"造成的 |
| **F2** | **惊喜门控"零拒绝"** —— 连续多天所有候选都通过 | 门控形同虚设，B 的"已验证"就退化成了自动生成，可信度优势归零（对照：现在 10 选 2 是健康值） | `gate.json` 的 `rejected_ids` 连续为空的运行批次 |
| **F3** | **A 补上遮挡逻辑 + 本地逐帧缓存后，隐私面被证明可控**，且改动量 < 2 周 | 那么 §5.2 理由 1 的"修不回来"就不成立，A 的唯一死刑被缓刑 | 出现一个可跑的实现：截图不出本机、敏感窗口被识别并遮挡，且有对抗用例 |
| **F4** | **A 的 461 陷阱 / 0 误操作动作库被证明是 B 无法获得的护城河**（例如外部没有任何等价开源实现，且用户明确要"能动手"） | 那么保留 A 的理由从"它的定位"变成"它的资产"，而资产是可以被移植的——但移植成本可能高于保留 | ContextAgent 类开源实现的"动作安全层"覆盖度调查（本轮未做，见 §2.6 未核项） |
| **F5** | **Microsoft / Google 把"本地痕迹 → 已验证成品"做成系统功能** | 与 §2.4 的 Meta 吞并模式同构：这是 B 最现实的死法。B 的护城河只有"可审计的本地优先"，一旦大厂用"本地 NPU 处理"复刻，优势消失 | Copilot Memory / Windows 版 Gemini 的功能发布说明；特别是它们是否开始**产出可验证产物**而不只是检索 |
| **F6** | **A 的常驻截屏在真实用户那里被接受**（不是没意见，而是有明确、持续的使用） | 如果社会许可其实存在，那 §2.1 的教训就不适用于 A——可能因为 A 是本地的、只服务单一个人、且可撤回 | 连续 7 天：截图库在增长、用户没有关闭它、且有 ≥1 次用户主动触发的"看我的屏幕" |
| **F7** | **π-Bench 的 Proc 在 A 的真实数据上并不低** | 我用"π-Bench 证明主动很难"来支持 A 的失败判断，但**我没有在 A 的数据上跑过 Proc**——这是推断，不是测量 | 用 A 的 `offers.jsonl` 做一次离线 Proc 标注（隐藏意图 vs 明说意图），看比例 |

**F7 是这份建议里最脆的一环，我明确标注**：我把"π-Bench 上的普遍困难"外推成了"A 必然失败"，这是**推断越界**——与卷宗 §九 记录的同类错误（把"没记动作"当成"没做动作"）是同一个毛病。**修正方式很便宜**：A 的账本已经在了，做一次离线标注就能检验。

---

## 7. 本轮未核项（诚实记录）

1. **PIPL 逐条条文**：三个官方入口在本机网络下均未能取得正文（404 / TLS 失败 / JS 渲染）。§4.2 的中国部分只有检索结论，**无逐条引用**。
2. **GUITester / PROBE**：检索被限流，未取得任何可核来源，本卷**未作任何陈述**。
3. **Apple**：未检索到 2025–2026 与 A 对等的公开产品，**不作断言**（不把传闻当事实）。
4. **A 的 Proc 实测**：见 F7，未做。
5. **Cluely 的定价与 ARR 数字**：来自二手汇总站（Postbeam / ThePlanetTools / tl;dv），**未取得一手来源**（TechCrunch 原文在受限网络下不可达）。数字标注为"待核"。
6. **Rewind/Limitless 的欧盟访问阻断原因**：WinBuzzer 称"blocking EU access"，**未取得官方说明**。
7. **A 的 `LICENSE` / 开源状态**：本卷未核验仓库当前的开源许可，§4.3 的开源建议是**产品判断**，不是对现状的描述。

---

## 8. 来源清单（URL + 访问时间均为 2026-10-12）

**官方/一手**
| 来源 | URL | 用途 |
|---|---|---|
| Azure Retail Prices API（`Trusted Signing`） | `https://prices.azure.com/api/retail/prices` | $9.99 / $99.99 / $0.005 签名单价 |
| Azure Trusted Signing 概览 | `https://learn.microsoft.com/en-us/azure/trusted-signing/overview` | Basic/Premium SKU |
| Microsoft Store 产品政策 10.5 | `https://learn.microsoft.com/en-us/windows/apps/publish/store-policies` | 个人信息 opt-in / 撤回 / Win32 必须隐私政策 |
| Microsoft GDPR DPIA 指引 | `https://learn.microsoft.com/en-us/compliance/regulatory/gdpr-data-protection-impact-assessments` | Art.35(1)(3)、EDPB 九项准则 |
| OpenAI 定价页 | `https://platform.openai.com/docs/pricing` | gpt-6-luna / 6.1-sol / 6-astra 单价表 |
| Anthropic 定价文档 | `https://docs.claude.com/en/docs/about-claude/pricing` | Haiku/Sonnet/Opus/Fable 5.x 单价表 |
| Google DeepMind Astra | `https://deepmind.google/models/project-astra/` | 能力与落地形态 |

**学术**
| 来源 | URL | 用途 |
|---|---|---|
| VISTA（MIT，2026-10-01） | `https://arxiv.org/abs/2610.02200` | ARC-AGI-3 视觉 harness，40.68 → 100.00 |
| ContextAgent（2025-05-20 / v2 10-27） | `https://arxiv.org/abs/2505.14668` | 开源主动 agent 底座 |
| ProPerSim（ICLR 2026） | `https://arxiv.org/abs/2509.21730` | 家庭域主动个性化基准（非桌面域） |
| π-Bench（v3 2026-05-19） | `https://arxiv.org/abs/2605.14678`、`https://simplified-reasoning.github.io/Pi-Bench/` | Proc / Comp 双指标；主动 vs 完成度背离 |

**媒体/社区（用于差评与时间线）**
| 来源 | URL | 用途 |
|---|---|---|
| The Record | `https://therecord.media/microsoft-reverses-course-recall-opt-in` | Recall 改 opt-in |
| Malwarebytes | `https://www.malwarebytes.com/blog/news/2024/06/microsoft-recall-delayed-after-privacy-and-security-concerns` | Recall 延期 |
| DoublePulsar（K. Beaumont） | `https://doublepulsar.com/microsoft-recall-on-copilot-pc-testing-the-security-and-privacy-implications-ddb296093b6c` | 一手安全测试 |
| GeekWire | `https://www.geekwire.com/2024/one-year-after-its-rocky-launch-microsofts-windows-recall-still-raises-security-red-flags/` | Penn 警告、一年后仍有红旗 |
| PCMag | `https://www.pcmag.com/news/windows-11-microsoft-finally-launches-its-controversial-recall-feature` | 2025-04-25 上市 |
| Windows Forum | `https://windowsforum.com/` | Copilot Vision opt-in 形态、微软回退 |
| WinBuzzer / 9to5Mac | `https://winbuzzer.com/`、`https://9to5mac.com/2025/12/05/rewind-limitless-meta-acquisition/` | Meta 收购 Limitless、停售 Pendant、关停 Rewind |
| Postbeam | `https://postbeam.ai/` | Cluely 定价与 ARR 撤回（二手，待核） |
| ThePlanetTools | `https://theplanettools.ai/` | Cluely 创始人承认虚报 ARR |
| E-Monitor | `https://employee-monitoring.net/compliance/is-screen-recording-employees-legal/` | BIPA / Cal.632 / 雇主披露 |
| Reddit | `r/Windows11`、`r/Surface`、`r/privacy`、`r/csMajors`、`r/macapps`、`r/Bard` | 用户真实差评原话 |

*本卷所有"运行时数字"采集时刻为 2026-10-12 08:17（Asia/Shanghai），项目当时**未被修改**——本卷未运行 docker、未触碰 `sprite_home/`，只做了只读。*
