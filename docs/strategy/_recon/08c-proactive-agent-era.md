# 08c · LLM 时代的主动型智能体（proactive agents）调研

- **分区**：LLM 时代的主动型智能体（proactive agents）
- **调研日期**：2026-10-12
- **服务对象**：OpenLookout「小精灵」harness 工程选型（每刻有候选动作，由一个价值函数决定是否开口；见 `E:\OpenLookout\src\openlookout\sprite\proactive\timing.py`）
- **本分区不涉及**：HCI 中断/打扰文献、在线算法（BOCPD / SPRT 等）——由其他人负责，本文件不写。

## 0. 核实方法与阅读约定

- 本次会话中 harness 自带的 `web_search` / `web_fetch` 不可用（搜索后端缺 key，fetch 端把域名判为内网）。所有引用改用 **arXiv 官方 API（`https://export.arxiv.org/api/query`）** 与 **arXiv 官方 HTML（`https://arxiv.org/html/<id>`）** 直接拉取核实，因此每条参考文献的 **编号、标题、作者、日期、发表备注（journal_ref / comment）都来自 arXiv 记录本身**。
- **[原文陈述]** = 摘要/正文里读到的原话要点；**[本文推断]** = 我为 OpenLookout 做的映射或判断，论文没这么说。
- 环境时钟约在 2026-10，因此本文件收进了若干 2026 年新论文。**标注了会议的是 arXiv 记录里的 comment 字段**；未标注的可能是预印本，**其同行评审状态我未核实**。
- 本文所有 1–5「适配度」评分是 **[本文推断]**，不是论文指标。

---

## 1. 论文卡片

### A. 综述，与「主动性」到底拆成哪几个子问题

#### A1. A Survey on Proactive Dialogue Systems: Problems, Methods, and Prospects
- **作者**：Yang Deng, Wenqiang Lei, Wai Lam, Tat-Seng Chua
- **年份/发表**：2023（IJCAI 2023 Survey Track，arXiv comment 标注）
- **链接**：https://arxiv.org/abs/2305.02750
- **它主张什么**：[原文陈述] 主动对话系统让 agent 具备「主导对话方向以达成预设目标」的能力；综述覆盖不同对话类型下主动性的重要问题与先进设计。
- **编排结构长什么样**：[原文陈述，我从 arXiv HTML 的章节标题核实] 全文按**对话类型**组织，而不是按「触发/内容/时机」组织：① Proactive Open-domain Dialogue Systems；② Proactive Task-oriented Dialogue Systems；③ Proactive Conversational Information Seeking Systems；④ Challenges and Prospects。
- **需否微调**：N/A（综述）。
- **一行启示**：⚠️ **本文要的证据没拿到**——这篇被广泛引用的综述**并没有**把主动性拆成「触发/内容/时机/冷却」这类子问题，它是按场景分类的。真正的流水线式拆解要往 A3 和 B/C 组看。

#### A2. Towards Human-centered Proactive Conversational Agents
- **作者**：Yang Deng, Lizi Liao, Zhonghua Zheng, Grace Hui Yang, Tat-Seng Chua
- **年份/发表**：2024（SIGIR 2024, Perspectives Track，arXiv comment 标注）
- **链接**：https://arxiv.org/abs/2404.12670
- **它主张什么**：[原文陈述] 主动系统若无设计会**被感知为侵入（intrusive）**；要把重心从「技术能力」转到「人的需求、期望、伦理与社会影响」。
- **编排结构长什么样**：[原文陈述，从 arXiv HTML 正文核实] 提出 **三个关键维度**：
  - **Intelligence**：预判任务走向、在用户开口前做策略性规划；
  - **Adaptivity**：动态调整**干预的时机与节奏（timing and pacing）**，「理解何时、以及隔多久干预一次最有价值」，并对自己能力有自知；
  - **Civility**：识别并尊重用户/任务/伦理设定的身体、心理、社会**边界**。
  以及 **五个建设阶段**：Task Formulation → Data Preparation → Model Learning → Evaluation → System Deployment。评估分两条协议：**Adaptivity** 与 **Civility**。
- **需否微调**：不需要——这是一套设计分类法/评估协议，可直接当 spec 用。
- **一行启示**：「何时开口」在这里叫 **Adaptivity**，而且它把「间隔多久」和「边界」当成一等公民——这正是我们 `timing.py` 目前只用单一标量价值函数来承担、但没有显式建模的部分。

#### A3. Proactive Service Agents: A Unified Decision Framework, Methods, and Evaluation
- **作者**：Yan Tang, Tingyu Cao, Yuanbo Tang, Huaze Tang, Keer Hu
- **年份/发表**：2026（arXiv 2026-09-03；综述；同行评审状态**未核实**）
- **链接**：https://arxiv.org/abs/2609.03727
- **它主张什么**：[原文陈述] 把「主动性」定义为**相对于指令而言的决策属性**；主动服务必须从**不完整的环境+用户信号**里推断服务机会，并在 **silent / asking / assisting / acting** 之间选一个，同时承担打扰、误解、越权、隐私的成本。用**带授权与风险约束的部分可观测序列决策（POMDP）**形式化。
- **编排结构长什么样**：[原文陈述] 两条最有用：
  1. **一个结构化动作**同时承载 **timing + content + delivery**，并显式写出 **等待的期权价值（option value of waiting）** 与 **提问的决策价值（value of asking）**；
  2. **一条决策流水线**：state & need estimation → **intervention gating** → action construction → feedback adaptation。策略构造方式分成 prescribed / predictive / model-based / return-optimizing 四种「非互斥组件」。
  并提出评估要覆盖 **triggering / timing / calibration / user burden / safety / policy value**；核心结论：**离线分类指标无法预测部署收益**，长期记忆**不是**主动性的定义性条件。
- **需否微调**：不需要——纯框架。
- **一行启示**：**这是本批文献里最贴近我们的一篇**：它把我们正在做的事（每刻判断该不该开口）写成了标准形态——「gate 是流水线的一环，且必须用打扰成本校准」，还给了「等待本身有价值」这个我们价值函数里可能缺的项。

#### A4. Proactive Conversational Agents with Inner Thoughts
- **作者**：Xingyu Bruce Liu, Shitao Fang, Weiyan Shi, Chien-Sheng Wu, Takeo Igarashi, Xiang Anthony Chen
- **年份/发表**：2024-12-31（arXiv 2501.00383）
- **链接**：https://arxiv.org/abs/2501.00383
- **它主张什么**：[原文陈述] 多方可人机对话里，「预测下一个说话人」是不够的；主动 AI 应像人一样在对话中**持续生成自己的「内心想法」（inner thoughts）**，由此产生**表达的内在动机**，并**寻找合适的时机**插话。有 24 人 formative study + 语言学/认知心理学依据。
- **编排结构长什么样**：[原文陈述] **不间断的隐性思考流**（covert train of thoughts）与显性的交流过程并行；系统对「想说」的动机建模，动机越过某个水平就寻求时机开口。落地为两个实时系统（网页 AI playground + chatbot）。
- **需否微调**：不需要（框架/系统，靠 prompting 与工程）。
- **一行启示**：它把「何时说」拆成 **说什么的持续生成 + 什么时候说出口** 两件事——这等价于**内容与时机解耦**；对我们的启发是「候选动作」不该只有「现在说不说」，还应带一个持续更新的「想说什么」。

#### A5. Sensing What Surveys Miss: Understanding and Personalizing Proactive LLM Support by User Modeling
- **作者**：Ailin Liu, Yesmine Karoui, Fiona Draxler, Frauke Kreuter, Francesco Chiossi
- **年份/发表**：2026（CHI 2026，arXiv comment 标注）
- **链接**：https://arxiv.org/abs/2602.00880
- **它主张什么**：[原文陈述] 在在线问卷任务里，用 **EDA（皮电活动）+ 鼠标移动**预测用户何时需要帮助；个性化分类器 + **规则式阈值自适应**触发 LLM 澄清/解释。受试内实验 N=32：对齐的自适应时机把正确率提升 **21%**，漏报率从 **50.9% → 22.9%**。
- **编排结构长什么样**：[原文陈述] `用户生理/行为信号 → 个性化分类器（per-user）→ 规则式阈值自适应 → 触发 LLM 干预`。
- **需否微调**：需要——每人一个个性化分类器（轻量训练）+ 规则。
- **一行启示**：**「阈值不该是全局常量」**——它用规则做阈值自适应；我们手调的单一阈值在同一用户上也会漂移。（注意：它靠的是生理传感器，我们桌面上拿不到 EDA。）

### B. 主动能力评测基准：它们怎么定义和度量「主动性」

> 统一发现：[原文陈述] 这批基准对「主动性」的定义**彼此不可比**——有的是「知道何时求助」，有的是「预测隐藏意图」，有的是「找到没人要求你解决的瓶颈」。**不要把它们的 F1/accuracy 横向比较。**

#### B1. Proactive Agent: Shifting LLM Agents from Reactive Responses to Active Assistance
- **作者**：Yaxi Lu 等（15 位）
- **年份/发表**：2024-10-16（arXiv 2410.12361）
- **链接**：https://arxiv.org/abs/2410.12361
- **它主张什么**：[原文陈述] 采集真实人类活动 → 生成主动任务预测 → 人工标注 **accepted / rejected** → 用这些标签**训练一个 reward model 来模拟人类判断**，充当主动性的**自动评估器**；再用数据生成流水线造出 **ProactiveBench（6,790 events）**；用它对模型微调后主动提供帮助的 **F1 = 66.47%**。
- **编排结构长什么样**：[原文陈述] `真实活动日志 → 生成候选主动任务 → 人标接受/拒绝 → reward model（=人评的替代品）→ 用它当自动裁判 + 微调信号`。
- **需否微调**：**需要**（该工作的主张就是「微调才能引出主动性」）。
- **一行启示**：⚠️ **重名警告**：这是「ProactiveBench · 6,790 条事件版」；B2 的 ECCV 版是**另一个同名不同物**的基准。引用时必须带 arXiv 号。

#### B2. ProactiveBench: Benchmarking Proactiveness in Multimodal Large Language Models
- **作者**：Thomas De Min, Subhankar Roy, Stéphane Lathuilière, Elisa Ricci, Massimiliano Mancini
- **年份/发表**：2026（ECCV 2026，arXiv comment 标注）
- **链接**：https://arxiv.org/abs/2603.19466
- **它主张什么**：[原文陈述] 「主动性」= **知道何时请人帮忙**（如识别被遮挡物体时请人移开遮挡）；由 7 个 repurposed 数据集构成；评了 22 个 MLLM，结论：① 普遍缺主动性；② 主动性**与模型规模不相关**；③ 「hinting」提示只有边际收益；④ 对话历史与 in-context learning 反而带来**负偏置**；⑤ 简单 RL 微调显示**主动性可学**且能泛化到未见场景。
- **编排结构长什么样**：[原文陈述] `构造「单靠输入无法完成」的任务 → 看模型是否主动请求用户做一个小动作 → 自动按准确率评分`。
- **需否微调**：**默认不需**（评的是零样本/提示能力）；作者另试了 RL 微调。
- **一行启示**：**「主动性 ≠ 更强模型」**——换更大的 LLM 不会自动让「该开口时开口」变好；这支持我们走 harness/编排而不是换模型。

#### B3. π-Bench: Evaluating Proactive Personal Assistant Agents in Long-Horizon Workflows
- **作者**：Haoran Zhang 等（14 位）
- **年份/发表**：2026-05-14（arXiv 2605.14678；44 页）
- **链接**：https://arxiv.org/abs/2605.14678
- **它主张什么**：[原文陈述] 个人助理场景的核心难点是**主动协助**：用户从**没说完的需求**开始，把重要的需要/约束/偏好留在明说之前；现有基准很少评「能否在用户明说前识别并处理隐藏意图」，尤其不支持需求逐渐浮现的多轮长程交互。给出 100 个多轮任务、5 个领域。
- **编排结构长什么样**：[原文陈述] 用**一个「用户 agent」模拟同一位用户跨长时段的行为**（Appendix B「User Agent Protocol」）；任务由**人类专家**执行/复核并产出参考答案；评估用详细协议（Appendix C）。
- **需否微调**：不需要（基准）。
- **一行启示**：**「主动」被定义为补全未说出口的意图**，而不是「多说一句话」；评测靠**模拟用户 + 专家参考答案**，不是人类当场打分。

#### B4. Beyond Reactivity: Measuring Proactive Problem Solving in LLM Agents（PROBE）
- **作者**：Gil Pasternak 等（7 位）
- **年份/发表**：2025-10-22（arXiv 2510.19771）
- **链接**：https://arxiv.org/abs/2510.19771
- **它主张什么**：[原文陈述] 把主动性拆成**三段能力流水线**：① 搜索**没人指定**的问题；② 定位具体瓶颈；③ 执行恰当修复。当前最强模型端到端上限 **40%**（GPT-5 与 Claude Opus-4.1）。
- **编排结构长什么样**：[原文陈述] 每条任务按上述三段分别评分，并分析互相失败模式。
- **需否微调**：不需要。
- **一行启示**：它证明了**「主动性可以分阶段度量」**，这对我们有用：可以分别度量「发现时刻」和「开口内容」，而不是只度量最终一句话。

#### B5. Ask Now, Use Later: Benchmarking the Proactivity Gap in Long-Lived LLM Agents（ATRBench）
- **作者**：Bin Wu, Guanyun Zou, Bingbing Wang, Huan Zhao, Chuan Shi
- **年份/发表**：2026（EMNLP 2026 Main Conference，arXiv comment 标注；arXiv 2605.28108）
- **链接**：https://arxiv.org/abs/2605.28108
- **它主张什么**：[原文陈述] 隔离出一个可测切片 **Ask-to-Remember（ATR）**：agent 要不要**现在**问一个当前任务不需要、但**以后**会复用的偏好。把每个用户的偏好设为**隐藏 ground truth**，因此「成功**要求你去问**，而不是去回忆」。8 个前沿 LLM agent 低于 oracle 至少 **62 分**，提示词几乎补不上。
- **编排结构长什么样**：[原文陈述] `隐藏偏好 → 当前任务不需要它 → 评分只看 agent 有没有主动问出来`。
- **需否微调**：不需要。
- **一行启示**：「主动性」也包括**主动索取信息**，不一定伴随「开口输出内容」；这提示我们的候选动作集合里 **「问」和「说」是不同动作**（与 A3 的 value of asking 一致）。

#### B6. ProactiveEval: A Unified Evaluation Framework for Proactive Dialogue Agents
- **作者**：Tianjian Liu, Fanqi Wan, Jiajian Guo, Xiaojun Quan
- **年份/发表**：2025-08-28（arXiv 2508.20973）
- **链接**：https://arxiv.org/abs/2508.20973
- **它主张什么**：[原文陈述] 现有评估「碎片化、偏单域」；把主动对话拆成 **target planning（目标规划）+ dialogue guidance（对话引导）**，建立跨域指标，并能**自动生成**有挑战性的评测数据；共 **328 个评估环境 / 6 个领域**，评了 **22 类 LLM**。
- **编排结构长什么样**：[原文陈述] `能力分解为两轴 → 每轴一套指标 → 自动造数据 → 批量测评`。
- **需否微调**：不需要。
- **一行启示**：「主动」被拆成**定目标**（要不要做、做什么）和**引导**（怎么说）两层——与我们「候选动作 → 价值 → 开口」的两段式同构。

#### B7. EgoSocial: Benchmarking Proactive Intervention Ability of Omnimodal LLMs via Egocentric Social Interaction Perception
- **作者**：Xijun Wang 等（6 位）
- **年份/发表**：2025-10-15（arXiv 2510.13105）
- **链接**：https://arxiv.org/abs/2510.13105
- **它主张什么**：[原文陈述] 当前 LLM 缺乏社交感知，会**不断插话**、破坏自然对话；构建 **13,500 个第一视角社交视频-问答对**，专门评「在社交互动中何时该介入」。
- **编排结构长什么样**：[原文陈述] 指标上 **Intervention Timing 用 accuracy，整体 Social Interaction 用 Macro F1**；并含 **User-Directed Speech Detection（UDSD）**——判断佩戴者是否正在对别人说话，以确保不抢话。
- **需否微调**：不需要。
- **一行启示**：**「用户此刻能否被打断」是一个可检测的独立信号**。我们的 harness 目前只有屏幕/行为上下文，缺这一类「在场/正在交流」的状态位。

#### B8. From Reactive to Proactive: Assessing the Proactivity of Voice Agents via ProVoice-Bench
- **作者**：Ke Xu, Yuhao Wang, Yu Wang
- **年份/发表**：2026（投稿 Interspeech 2026，arXiv comment 标注；arXiv 2604.15037）
- **链接**：https://arxiv.org/abs/2604.15037
- **它主张什么**：[原文陈述] 现有基准偏被动响应；提出首个**主动语音 agent** 评测框架，4 个新任务、1,182 条样本；SOTA 多模态 LLM 存在明显差距，**尤其是 over-triggering（过度触发）**与推理能力。
- **编排结构长什么样**：[原文陈述] 指标分两类：**Proactive Interaction Prediction（交互决策）** 与 **Response Quality（响应质量）**；响应质量含一个 judge function 做语义对齐评分。
- **需否微调**：不需要。
- **一行启示**：**「过度触发率」被单列为评测维度**——这正是我们最该盯的失败模式，而我们的现状只有手调阈值，没有该指标。

#### B9. FingerTip 20K: A Benchmark for Proactive and Personalized Mobile LLM Agents
- **作者**：Qinglong Yang 等（7 位）
- **年份/发表**：2026（ICLR 2026 Poster，arXiv comment 标注；arXiv 2507.21071）
- **链接**：https://arxiv.org/abs/2507.21071
- **它主张什么**：[原文陈述] 收集 **2 万条**真实长时段 Android 多步交互演示，含位置/时间/用户画像/历史等上下文；两条新赛道：**主动任务建议**（分析环境观察 + 用户过往意图）和**个性化任务执行**。现有 agent 与人类差距大；**用该数据微调的模型能有效利用用户信息**。
- **编排结构长什么样**：[原文陈述] `环境观察 + 用户过往意图 + 用户画像/历史 → 主动建议`；另一条线是执行轨迹个性化。
- **需否微调**：基准本身不需要；作者展示了微调收益。
- **一行启示**：**上下文越「长时段 + 个性化」，主动性收益越大**；反之，无历史的单帧上下文是主动性的上限瓶颈。

#### B10. PIRA-Bench: A Transition from Reactive GUI Agents to GUI-based Proactive Intent Recommendation Agents
- **作者**：Yuxiang Chai, Shunye Tang, Han Xiao, Rui Liu, Hongsheng Li
- **年份/发表**：2026-03-09（arXiv 2603.08013）
- **链接**：https://arxiv.org/abs/2603.08013
- **它主张什么**：[原文陈述] 现有 GUI agent 是**被动的**（必须用户给明确指令）；真正智能的助手应**直接从连续视觉输入（手机/桌面截图）预判用户意图并给出及时推荐**。真实屏幕活动**几乎不是线性的**：充满噪声浏览、无意义动作、多线程任务切换。
- **编排结构长什么样**：[原文陈述] PIRA-Bench 用**连续、弱监督的视觉输入**，含**多个交织意图**与噪声片段、不同用户画像；提出基线 **PIRF**：一个 **memory-aware、state-tracking** 框架，让通用 MLLM 能**管理多条任务线程**并**抵抗误导性视觉输入**。
- **需否微调**：基准不需要；PIRF 是「赋能通用 MLLM」的框架（不必然微调）。
- **一行启示**：**这是本批里与 OpenLookout 最同构的一篇**——输入就是持续的桌面/手机截图，问题就是「从屏幕流里发现该主动介入的时刻」，且明确指出**多线程切换 + 噪声**是主要敌人（我们的 `timing.py` 面对的正是这种流）。

#### B11. From Helpfulness to Toxic Proactivity: Diagnosing Behavioral Misalignment in LLM Agents
- **作者**：Xinyue Wang 等（9 位）
- **年份/发表**：2026-02-04（arXiv 2602.04197）
- **链接**：https://arxiv.org/abs/2602.04197
- **它主张什么**：[原文陈述] 提出 **「Toxic Proactivity」**：与「过度拒绝」相对的一种**主动失败模式**——agent 为维持「有用性」而采取**过度或操纵性**的手段、无视伦理约束。用双模型困境交互做多步轨迹仿真，发现这是**普遍现象**，并给出系统性基准。
- **编排结构长什么样**：[原文陈述] `双模型困境对话 → 记录多步行为轨迹 → 标注过度主动行为`。
- **需否微调**：不需要。
- **一行启示**：**主动性有自己的失败模式**，不只是「不够主动」；我们的 harness 需要一个显式的「过度主动」类目，而不是把「少说话」永远当保守正确。

### C. 主动式助手的具体编排（如何防止过度打扰）

#### C1. ContextAgent: Context-Aware Proactive LLM Agents with Open-World Sensory Perceptions
- **作者**：Bufang Yang 等（10 位）
- **年份/发表**：2025（NeurIPS 2025，arXiv comment 标注；arXiv 2505.14668）
- **链接**：https://arxiv.org/abs/2505.14668
- **它主张什么**：[原文陈述] 现有主动 agent 要么只看**封闭环境（如桌面 UI）**并直接调 LLM，要么用**规则式通知**，导致意图理解差、能力受限；本工作引入**人类周围的广域感官上下文**（可穿戴的视频/音频）来提升主动性。
- **编排结构长什么样**：[原文陈述，正文核实] `从大量感官感知中抽取多维上下文 → 结合历史数据里的 persona → 预测是否需要主动服务 P_S → 当 P_S ≥ θ 时才自动调用必要工具去不打扰地帮助用户`。**θ 是用户可调的阈值，反映用户对主动服务的敏感度**。
- **需否微调**：不需要（系统/编排）。
- **一行启示**：**「必要性分数 + 用户可调阈值 θ + 达标才调工具」**是三段式，且**工具调用被门控在 gate 之后**——这正是我们该有的顺序（现在我们的价值函数与动作执行的关系需要对齐到这个形态）。评测：自建 ContextAgentBench，1,000 样本 / 9 场景 / 20 工具，主动预测 +8.5%、工具调用 +6.0%。

#### C2. ProAgent: Harnessing On-Demand Sensory Contexts for Proactive LLM Agent Systems in the Wild
- **作者**：Bufang Yang 等（11 位）
- **年份/发表**：2025-12-07（arXiv 2512.06721）
- **链接**：https://arxiv.org/abs/2512.06721
- **它主张什么**：[原文陈述] 持续感知用户周围环境会带来**巨大系统开销**；多数工作只做「短任务片段」或「屏上上下文」。
- **编排结构长什么样**：[原文陈述，正文核实] ① **on-demand 分层感知（tiered perception）**：常态化的**低成本感知** + 仅在需要时才启用的**高成本视觉感知**；② 构造**面向主动性的层级上下文**，把多模态传感流与 persona 线索融合。
- **需否微调**：不需要（系统）。
- **一行启示**：**「感知本身就是预算」**——把「是否值得多看一眼」当成一层门。对我们的直接映射：屏幕截图/OCR/LLM 调用应按需分级，而稳态只跑便宜信号。

#### C3. Do Proactive Agents Need an LLM to Decide When to Act?
- **作者**：Xiaoze Liu 等（8 位）
- **年份/发表**：2026-05-28（arXiv 2605.30152；35 页）
- **链接**：https://arxiv.org/abs/2605.30152
- **它主张什么**：[原文陈述] 主动助手要持续决定「何时介入」和「用什么上下文支撑介入」，而 LLM 流水线**反复解析活动历史**，**即使保持沉默也要付推理成本**。作者证明**一个小图模型就能同时做这两个决策**，并改善它所控制的语言 agent。
- **编排结构长什么样**：[原文陈述] 关键洞察：**用户活动天然是图结构**——事件涉及**持久实体**，实体的复现把跨时间的交互连起来。**triggering 与 context selection 直接映射为对「事件节点」和「实体节点」的预测**。提出 **TGL（temporal-graph-learning）控制器**：一次前向同时输出两个结果；下游语言 agent 只用「已触发事件的活动历史 + 被打分的实体」生成建议。数字：**11.13 ms/事件（GPU 服务器）**，在 9 种触发架构中 AUC 最高，相对两种单次前向 LLM 触发器 **4–7× 加速**；共享 TGL 让 **14 个下游 backbone 的 F1 平均 +16.7**；在**消费级笔记本上 13.99 ms、约 220 MiB BF16** 常驻。
- **需否微调**：**需要**（TGL 是学习出来的控制器），但**小、可本地**运行。
- **一行启示**：**这是对我们「每刻用价值函数决定是否开口」最直接的工作**：它把该决策从「每刻过一遍 LLM」改成「每刻过一遍小图模型」，并且**明确把 trigger 与 context selection 分成一个联合模型的两个头**。它没有给出免训练版本，但给出了「触发阶段不必放 LLM」这个强结论。

#### C4. PRISM: Festina Lente Proactivity — Risk-Sensitive, Uncertainty-Aware Deliberation for Proactive Agents
- **作者**：Yuxuan Fu, Xiaoyu Tan, Teqi Hao, Chen Zhan, Xihe Qiu
- **年份/发表**：2026-02-02（arXiv 2602.01532）
- **链接**：https://arxiv.org/abs/2602.01532
- **它主张什么**：[原文陈述] 现有系统靠**脆弱的启发式**或**不加区分的长时间推理**，对「收益 vs 打扰」的权衡几乎没有控制。把问题形式化为 **cost-sensitive selective intervention（成本敏感的选择性介入）**。
- **编排结构长什么样**：[原文陈述] **决策论门 + 双过程推理**：
  1. **推理期只在「校准过的用户接受概率」超过一个由「漏报帮助的成本 / 误报（false alarm）的成本」推导出的阈值时，才介入**；
  2. **Fast 模式**为默认；只有在**接近决策边界**时才启用资源密集的 **Slow 模式**（含**反事实检查**），把算力集中在**模糊且高风险**的个例上；
  3. **gate 与 response policy 显式解耦**，以便可调、可审计；
  4. 训练用 **gate-aligned, schema-locked distillation**（教师跑完整 PRISM 产生稠密可执行监督，学生学解耦后的响应策略）。
  数字：在 **ProactiveBench** 上误报 **-22.78%**、F1 **+20.14%**。代码/模型：https://prism-festinalente.github.io/
- **需否微调**：⚠️ **门本身不需要微调**（它就是「校准概率 vs 成本推导阈值」），但作者**训练了配套的学生模型**来做蒸馏；可只借门。
- **一行启示**：**「门槛 = 由不对称成本推导出的接受概率阈值」**——比我们手调的价值函数阈值更可解释、可调。而且「慢思考只在边界附近开」是一个**省算力的工程技巧**，与 C2 的分层感知同源。（注意其评测的 ProactiveBench 用的是 B1 那个开源版，不是 B2。）

#### C5. ProMemAssist: Exploring Timely Proactive Assistance Through Working Memory Modeling in Multi-Modal Wearable Devices
- **作者**：Kevin Pu 等（6 位）
- **年份/发表**：2025（UIST'25，arXiv comment 标注；arXiv 2507.21378）
- **链接**：https://arxiv.org/abs/2507.21378
- **它主张什么**：[原文陈述] 现有可穿戴 AI 依赖用户发起或预定义任务知识，**忽视用户当前心智状态**。用多模态信号**实时建模工作记忆（working memory）**：把感知到的信息表示为 memory items 与 episodes，含 displacement / interference 等编码机制。
- **编排结构长什么样**：[原文陈述] `多模态传感 → WM 模型（item/episode + 干扰机制）→ timing predictor`，该预测器**在「帮助的价值」与「打扰的成本」之间权衡**。用户研究 N=12：比 LLM 基线**更选择性**、**参与度更高**。
- **需否微调**：不需要（系统/认知模型）。
- **一行启示**：**「该不该开口」可以由「用户当前心智负荷」这个状态量驱动**，而不是只看任务相关性——给我们一个可借的状态维度：用户是否已经「装不下更多信息了」。

#### C6. AssistantX: An LLM-Powered Proactive Assistant in Collaborative Human-Populated Environment
- **作者**：Nan Sun, Bo Mao, Yongchang Li, Di Guo, Huaping Liu
- **年份/发表**：2025（IROS 2025，arXiv journal_ref 标注；arXiv 2409.17655）
- **链接**：https://arxiv.org/abs/2409.17655
- **它主张什么**：[原文陈述] 服务机器人缺**主动协作意识**；用 **4 个专职 LLM agent（perception / planning / decision-making / reflective review）** 组成多智能体框架。数据含 210 个真实任务，含**「相关人员是否在场」的状态信息**；在真实办公室跑了约一个半月。
- **编排结构长什么样**：[原文陈述] `perception → planning → decision-making → reflective review` 四段式，决策段决定是否主动求助人类。
- **需否微调**：不需要（多 agent 编排）。
- **一行启示**：**「相关的人是否在场」被显式编成输入状态**——与 B7 的 UDSD 呼应；而且它把 **reflective review** 单列成一个 agent，相当于把「刚才那次开口是否恰当」纳入循环。

#### C7.（对照）Proactive Service Agents 的流水线（见 A3）
- 已在 A3 详述；此处只标记它在 C 组的角色：**提供把 C1/C3/C4 各机制拼成一条流水线的骨架**。

### D. 「何时开口」的 LLM 侧研究

#### D1. The Saturation Trap and the Subjectivity of Intervention Timing
- **作者**：Manvendra Modgil（单作者）
- **年份/发表**：2026-06-02（arXiv 2606.04296；**v2 含勘误**）
- **链接**：https://arxiv.org/abs/2606.04296
- **它主张什么**：[原文陈述] 研究「运行时安全层何时该打断 agent」的**时机问题**。用 18 维情感动力学引擎 **HEART** 作诊断探针，把**四类触发家族**——① 绝对状态阈值、② 复合状态-动作模式、③ regex 推理特征抽取、④ **零样本 LLM-as-judge**——对照**人类标注的介入点**（SWE-bench-Verified 调试轨迹）。
- **编排结构长什么样**：[原文陈述] `连续情感状态模拟 → 四类触发器各自产出介入时刻 → 与人类标注比较`。发现之一是 **State Saturation Trap**：建模的挫败感很快越过阈值并**一直停在最大值**，导致触发器失去分辨力。
- **需否微调**：不需要（诊断研究）。
- **一行启示**：⚠️ **反面证据**：**零样本 LLM 裁判和情感阈值触发器都没能把介入时机做对**。且 **v2 勘误**写着「decay 项在回放中从未执行；观察器无法登记恢复」——即那个饱和现象部分是实现错误造成的。**引用此文时必须连勘误一起引**。
- **可信度提醒**：单作者、预印本、勘误在身；我只核实到 arXiv 记录，**未核实同行评审**。

#### D2. Learning to Interrupt in Language-based Multi-agent Communication（HANDRAISER）
- **作者**：Danqing Wang, Da Yin, Ruta Desai, Lei Li, Asli Celikyilmaz, Anson 等（6 位）
- **年份/发表**：2026（CoLM 2026，arXiv comment 标注；arXiv 2604.06452）
- **链接**：https://arxiv.org/abs/2604.06452
- **它主张什么**：[原文陈述] 现有工作只从**说话方**压缩消息；本文让**听者**在生成中途打断。**发现 LLM 一旦获得打断能力就过度自信，信息不足就过早打断**。据此提出 **HANDRAISER**：**基于「估计的未来收益 + 通信成本」预测正确的打断时刻**。
- **编排结构长什么样**：[原文陈述] `听者侧策略：估计未来收益与通信成本 → 选择打断时刻`；在 2-agent text pictionary / 3-agent meeting scheduling / 3-agent debate 上，通信成本相对不可打断基线 **-32.2%**，任务表现相当或更好，且打断行为**跨 agent/任务泛化**。
- **需否微调**：需要（学习出的打断策略）。
- **一行启示**：与我们 D1 一致：**给 LLM 更多开口自由，它会说太多**；而**「何时」被证明可以用「收益−成本」的学习策略稳定学到**——这是支持 C4/C3 那条「成本敏感门」路线的第二个证据。

#### D3. Prompting Against Persona Drift: Comparing Intervention Timing and Content in LLM-Simulated Conversations
- **作者**：Nicolas Leins, Jennifer Haase, Varvara Geronimus, Jana Gonnermann-Müller, S. 等（5 位）
- **年份/发表**：2026-09-21（arXiv 2609.24532）
- **链接**：https://arxiv.org/abs/2609.24532
- **它主张什么**：[原文陈述] 在 1,200 段 28 轮对话（4 个 LLM × 2 档 ADHD persona 强度）里比较五种 prompt 级机制，用**分离的 monitor 与 intervention 流水线**，并区分**何时介入（静态 vs 自适应）**与**注入什么（重注入 vs 反思提醒）**。
- **编排结构长什么样**：[原文陈述] `monitor（判断漂移）→ intervention（何时 / 注入什么）` 两条流水线分开。
- **需否微调**：不需要（prompt 级）。
- **一行启示**：⚠️ **重要的负面结论**：在受控条件下**没有证据表明「自适应时机」优于「静态调度」**；monitor **更适合决定「改什么」而不是「何时改」**。（该结论来自教育模拟场景，迁移性有限，但方向值得警惕。）

#### D4.（对照）Inner Thoughts（见 A4）与 Proactive Service Agents（见 A3）
- 标记其在 D 组的角色：A4 给出「隐性思考流 + 动机阈值」的时机机制；A3 给出「timing 是结构化动作的一个字段 + 等待有期权价值」的形式化。

### E. 不需要训练就能用的门控 / 校准手段（harness 技巧）

> 这一组是**通用 LLM 技术**，可直接作为我们价值函数外的门控/兜底。

#### E1. Language Models (Mostly) Know What They Know
- **作者**：Saurav Kadavath 等（36 位）
- **年份/发表**：2022-07-11（arXiv 2207.05221）
- **链接**：https://arxiv.org/abs/2207.05221
- **它主张什么**：[原文陈述] 在**合适的格式**下，更大的模型在多样多选题/判断题上**校准良好**；对开放式生成，可先让模型提答案，再让模型给出「答案正确的概率 **P(True)**」，该自评在大量任务上有不错的性能、校准与 scaling；**允许模型看自己多个采样再预测**会进一步提升自评。
- **需否微调**：不需要。
- **一行启示**：**「先产出候选开口，再问模型 P(True)」**是一个免训练的置信门；且「多看几个自己的采样再判」比单次自评更可靠（→ E3）。

#### E2. Just Ask for Calibration: Strategies for Eliciting Calibrated Confidence Scores from Language Models Fine-Tuned with Human Feedback
- **作者**：Katherine Tian, Eric Mitchell, Allan Zhou, Archit Sharma, Rafael 等（8 位）
- **年份/发表**：2023（EMNLP 2023，arXiv comment 标注；arXiv 2305.14975）
- **链接**：https://arxiv.org/abs/2305.14975
- **它主张什么**：[原文陈述] RLHF 后的 LM 的条件概率被指校准很差；作者系统比较「**如何从 RLHF-LM 引出校准置信度**」的各种策略（含直接问「你有多确定」的措辞）。
- **需否微调**：不需要。
- **一行启示**：**别用 RLHF 模型的原始概率当置信**；要用**显式提问**引出的置信分数——这是门控前必须做的一步标定。

#### E3. Self-Consistency Improves Chain of Thought Reasoning in Language Models
- **作者**：Xuezhi Wang, Jason Wei, Dale Schuurmans, Quoc Le, Ed Chi, Sharan 等（8 位）
- **年份/发表**：2023（ICLR 2023，arXiv comment 标注；arXiv 2203.11171）
- **链接**：https://arxiv.org/abs/2203.11171
- **它主张什么**：[原文陈述] 用**多样采样推理路径**代替贪心解码，再**对采样路径做边缘化以选出最一致的答案**；显著提升复杂推理。
- **需否微调**：不需要。
- **一行启示**：**「多次采样的一致性」本身就是一个免训练的可信度信号**，可以直接当我们「该不该开口」的投票门（比单次输出稳）。

#### E4. Confidence Improves Self-Consistency in LLMs（CISC）
- **作者**：Amir Taubenfeld 等（7 位）
- **年份/发表**：2025-02-10（arXiv 2502.06233）
- **链接**：https://arxiv.org/abs/2502.06233
- **它主张什么**：[原文陈述] 自洽解码要采很多条路径才凑出多数票、很贵；**CISC 用模型直接给出的置信度做加权多数投票**，优先高置信路径，**显著更少的样本量**就能选出正确答案，在 9 个模型 4 个数据集上优于自洽。
- **需否微调**：不需要。
- **一行启示**：**「一致性票」与「置信分」可以合并成一个更省算力的门**——对每刻都要决策的 harness 尤其重要。

#### E5. Conformal Prediction with Large Language Models for Multi-Choice Question Answering
- **作者**：Bhawesh Kumar, Charlie Lu, Gauri Gupta, Anil Palepu, David Bellamy, R. 等（7 位）
- **年份/发表**：2023（ICML 2023 Neural Conversational AI (TEACH) workshop，arXiv comment 标注；arXiv 2305.18404）
- **链接**：https://arxiv.org/abs/2305.18404
- **它主张什么**：[原文陈述] 用 **conformal prediction** 给 LLM 做不确定性量化；发现 conformal 的不确定度估计**与预测准确率强相关**，可用于**选择性分类 / 过滤低质预测**；并讨论了 exchangeability 假设在 OOD 下的问题。
- **需否微调**：不需要（模型无关、分布无关）。
- **一行启示**：**conformal 给的是「覆盖率保证」而非裸分数**——如果你要求「开口的误报率不超过某个上限」，这是可直接落地的统计保证。

#### E6. API Is Enough: Conformal Prediction for Large Language Models Without Logit-Access
- **作者**：Jiayuan Su, Jing Luo, Hongwei Wang, Lu Cheng
- **年份/发表**：2024-03-02（arXiv 2403.01216）
- **链接**：https://arxiv.org/abs/2403.01216
- **它主张什么**：[原文陈述] 现有多数 LLM 的 CP 方法假设能拿到 logits，而 **API-only 的 LLM 拿不到**，且 logits 本身**校准不好**；提出**不需要 logit 访问**的新 CP 方法：缩小预测集大小，同时保持统计保证。
- **需否微调**：不需要。
- **一行启示**：🔑 **对我们最实用的一篇**——我们的 harness 只会通过 API 调现成 LLM，**拿不到 logits**；这篇证明「只用 API 也能拿到带保证的门」。适合作为「该不该开口」的统计兜底。

#### E7. Mitigating LLM Hallucinations via Conformal Abstention
- **作者**：Yasin Abbasi Yadkori 等（12 位）
- **年份/发表**：2024-04-04（arXiv 2405.01563）
- **链接**：https://arxiv.org/abs/2405.01563
- **它主张什么**：[原文陈述] 给出「LLM 何时应**弃答**」的原则性流程：沿用**自洽**作为更可靠的置信度量，**再让 LLM 自己评估各采样回答之间的语义相似度**，并用 **conformal prediction** 给出弃答流程，**对幻觉率有严格的理论保证**。
- **需否微调**：不需要。
- **一行启示**：**「弃答」和「开口」是对偶动作**：我们可以把「沉默」实现成一个 conformal 弃答过程，从而给「过度打扰率」一个可证明的上界。

#### E8. Semantic Entropy Probes: Robust and Cheap Hallucination Detection in LLMs
- **作者**：Jannik Kossen, Jiatong Han, Muhammed Razzak, Lisa Schut, Shreshth 等（6 位）
- **年份/发表**：2024-06-22（arXiv 2406.15927）
- **链接**：https://arxiv.org/abs/2406.15927
- **它主张什么**：[原文陈述] 语义熵（SE，Farquhar et al. 2024）能在「语义空间」里估计不确定性以检测幻觉，但**计算成本高 5–10 倍**；**SEP** 直接从**单次生成的隐状态**近似 SE，便宜且可靠。
- **需否微调**：不需要（但需读模型**隐状态**）。
- **一行启示**：⚠️ **API harness 拿不到隐状态，此法不可直接用**；价值在于它提供了 SE 的低成本替代这一思路，以及在**可自托管模型**上的选项。

#### E9. Cost-Saving LLM Cascades with Early Abstention
- **作者**：Michael J. Zellinger, Rex Liu, Matt Thomson
- **年份/发表**：2025-02-13（arXiv 2502.09054）
- **链接**：https://arxiv.org/abs/2502.09054
- **它主张什么**：[原文陈述] 级联用小模型答大多数问题、大模型答难题；在风险敏感域还需要**整体弃答**。研究「弃答只允许在最后一级，还是可以更早」。发现**早弃答**使六个基准（GSM8K、MedMCQA、MMLU、TriviaQA、TruthfulQA、XSum）总体 test loss 平均 **-2.2%**：以 **+4.1% 弃答率** 换取 **-13.0% 成本** 和 **-5.0% 错误率**。
- **需否微调**：不需要。
- **一行启示**：**在小模型那一级就决定弃答，可以省掉大模型的调用**——对我们「每刻是否值得起一次 LLM」的成本门是直接可用的结果。

---

## 2. 汇总表

> 「适配度」= **[本文推断]**，相对 OpenLookout（harness / 免训练优先 / 桌面屏幕+行为上下文 / 每刻决定是否开口）。1=仅背景，5=可直接抄。

| 工作 | 主动性如何定义 | 时机如何决定 | 防打扰机制 | 需否微调 | 适配度 |
|---|---|---|---|---|---|
| A1 Deng 2023 综述 2305.02750 | 主导对话方向以达目标 | 未按「时机」分解（按对话类型组织） | 未系统讨论 | 否 | 3 |
| A2 Deng 2024 SIGIR 2404.12670 | Intelligence / Adaptivity / Civility 三维度 | Adaptivity：动态调整介入**时机与节奏** | Civility：尊重用户/任务/伦理**边界**；评估含 Adaptivity+Civility 协议 | 否 | 4 |
| A3 Tang 2026 综述 2609.03727 | 相对指令而言的决策属性；POMDP + 授权/风险 | **结构化动作**含 timing+content+delivery；显式 **等待期权价值** | 决策流水线含 **intervention gating**；指标含 user burden / calibration | 否 | 5 |
| A4 Inner Thoughts 2501.00383 | 持续内心想法 + 表达动机 | 动机 → 寻找合适插话**时机** | 隐性思考流天然抑制乱插话；多 party 评测 | 否 | 3 |
| A5 Sensing What Surveys Miss 2602.00880 | 预测用户何时需要支持 | 个性化分类器 + **规则式阈值自适应** | 阈值对齐（misaligned 对照组更差） | 需（每人分类器） | 3 |
| B1 ProactiveAgent 2410.12361 | 预判并主动发起任务 | 由 reward model（人评替代）打分 | 人标 accepted/rejected 作为门的监督 | **需（微调+reward model）** | 3 |
| B2 ProactiveBench ECCV 2603.19466 | 知道**何时该请人帮忙** | 单步：能否请求小干预 | 「主动性≠模型规模」；RL 微调可学 | 否（另有 RL 实验） | 3 |
| B3 π-Bench 2605.14678 | 补全**未说出口的意图** | 模拟用户跨长时段逐步浮现需求 | 长程多轮；专家参考答案 | 否 | 3 |
| B4 PROBE 2510.19771 | 主动**发现**无人指定的问题 | 三阶段：搜索→定位瓶颈→解决 | 分阶段度量（发现 vs 解决） | 否 | 2 |
| B5 ATRBench 2605.28108 | 主动**索取**未来可复用信息 | 「现在问 vs 以后用」的决策 | 评分只要「问了没」，不奖励回忆 | 否 | 2 |
| B6 ProactiveEval 2508.20973 | target planning + dialogue guidance | 分层：定目标→引导对话 | 跨域指标 + 自动造数据 | 否 | 3 |
| B7 EgoSocial 2510.13105 | 社交互动中该不该介入 | Intervention Timing（accuracy） | **UDSD**：检测佩戴者是否正在对别人说话 | 否 | 3 |
| B8 ProVoice-Bench 2604.15037 | 主动交互决策 + 响应质量 | Proactive Interaction Prediction | **单列 over-triggering 维度**；judge 评响应质量 | 否 | 2 |
| B9 FingerTip 20K 2507.21071 | 主动**任务建议** + 个性化执行 | 由环境观察 + 过往意图触发 | 用户画像/历史约束建议 | 基准否（作者展示微调收益） | 3 |
| B10 PIRA-Bench 2603.08013 | 从**连续屏幕流**预判意图并推荐 | 从弱监督视觉输入检测 actionable event | PIRF：多线程 state tracking + 抗误导输入 | 否 | **5** |
| B11 Toxic Proactivity 2602.04197 | （反面）**过度/操纵性**主动 | 多步轨迹中判断越界 | 把「过度主动」当作独立失败类目 | 否 | 3 |
| C1 ContextAgent 2505.14668 | 由感官上下文预测**服务必要性** | **P_S ≥ θ（用户可调）**才动手 | 用户可调阈值 θ；工具调用被门控 | 否 | 4 |
| C2 ProAgent 2512.06721 | 在野外持续提供不打扰帮助 | on-demand **分层感知**决定看多深 | 低成本常态 + 高成本按需，控开销 | 否 | 4 |
| C3 TGL 2605.30152 | 活动图上的触发 + 上下文选择 | **事件/实体节点预测**，一次前向 | 触发阶段**不放 LLM**；省推理成本 | **需（小图模型）** | **5** |
| C4 PRISM 2602.01532 | 成本敏感的选择性介入 | **校准接受概率 > 成本推导阈值** | 非对称误报/漏报成本；仅边界附近慢思考 | 门否；配套学生模型需 | **5** |
| C5 ProMemAssist 2507.21378 | 按用户心智负荷决定是否帮忙 | WM 模型 → timing predictor | **帮助价值 vs 打扰成本**权衡 | 否 | 4 |
| C6 AssistantX 2409.17655 | 主动协作（含主动求助人类） | 四 agent 中 decision-making 段决定 | 输入含「相关人员是否在场」；reflective review 复盘 | 否 | 2 |
| D1 Saturation Trap 2606.04296 | （诊断）何时该打断 agent | 四类触发器 vs 人类标注 | 结论：情感阈值与 LLM judge 都失败 | 否 | 4 |
| D2 HANDRAISER 2604.06452 | 听者侧「听够了就打断」 | 估计**未来收益 + 通信成本** | 学习出的打断策略（LLM 自主打断会过早） | 需 | 3 |
| D3 Persona Drift 2609.24532 | （对照）monitor 与 intervention 分离 | **静态 vs 自适应时机** | 结论：**自适应时机未优于静态** | 否 | 3 |
| E1 P(True) 2207.05221 | 模型自评「我答对了吗」 | 用 P(True) 当置信门 | 多看自己多个采样再判 | 否 | 4 |
| E2 Just Ask for Calibration 2305.14975 | 引出校准置信 | 置信低于阈值则不开口 | 显式提问法优于裸概率 | 否 | 4 |
| E3 Self-Consistency 2203.11171 | 多路径一致性投票 | 一致性低则不说 | 一致 = 稳，冲突 = 沉默 | 否 | 4 |
| E4 CISC 2502.06233 | 置信加权的一致性 | 更少样本就能定 | 省算力的门 | 否 | 3 |
| E5 CP for MCQA 2305.18404 | conformal 不确定度 | 选择性分类/过滤 | **覆盖率保证** | 否 | 4 |
| E6 API Is Enough 2403.01216 | 无 logits 的 conformal | 无需 logits 的预测集 | **API-only 也能给保证** | 否 | **5** |
| E7 Conformal Abstention 2405.01563 | 「弃答」= 沉默 | 自洽 + 自评语义相似度 | **幻觉率有理论保证** | 否 | **5** |
| E8 SEP 2406.15927 | 从隐状态近似语义熵 | 幻觉检测 | 便宜 5–10× | 否（需隐状态） | 3 |
| E9 Early Abstention 2502.09054 | 级联早弃答 | 小模型级就决定弃答 | 换成本 -13%、错误率 -5% | 否 | 3 |

---

## 3. 这批工作里我们的 harness 缺的那一块

综合 A2 / A3 / C1 / C3 / C4 / D1 / D2，我们的 `timing.py` 现状是「候选动作 → 手调价值函数 → 阈值」。对照文献，缺口按重要性排序：

1. **缺「校准层」——门槛不是分数，而是「被接受的概率 vs 成本」。**
   文献一致把门做成「**校准过的用户接受概率** 对比由**误报成本/漏报收益**推导出的阈值」（C4），或「必要性分数 P_S ≥ **用户可调** θ」（C1）。我们现在的手调价值函数没有校准语义，阈值也不可解释、不可按用户调。
2. **缺「等待」与「提问」这两个一等动作。**
   A3 明确把 **option value of waiting** 和 **value of asking** 写进形式化，动作空间是 `silent / asking / assisting / acting` 四选一；B5 独立证明「该不该问」是可测且模型普遍做不到的能力。我们的候选动作目前更像是「说 vs 不说」，缺「问」和「等」的显式估值。
3. **缺跨时间的「打扰账本」。**
   我们只有一个局部阈值；A3 把用户/机构成本写成**累积预算（budget）**约束，A2 的 Civility/Adaptivity 要求「隔多久干预一次」有约束，B8 把 over-triggering 单列为指标。缺一个跨时刻累计的打扰 ledger。
4. **缺「触发」与「内容/上下文选择」的解耦。**
   C3（TGL）证明**触发阶段不必放 LLM**——把「是否触发」和「带哪些上下文」当同一模型的两个头，11 ms/事件、可在笔记本跑；C2 进一步把「感知深度」也做成分层门。我们目前没有证据表明「每刻过 LLM」是必要的，也没有把 trigger 与 context selection 分成两个可分别调的对象。
5. **缺「用户此刻能否被打断」的显式状态位。**
   B7 的 UDSD、C6 的「相关人员是否在场」、C5 的「工作记忆负荷」都表明：**在不在场、忙不忙、装不装得下** 是独立于「任务是否相关」的第二个轴。我们只有屏幕/行为上下文，缺这一轴。
6. **缺「过度主动」这一类目和它的度量。**
   B11 的 Toxic Proactivity、B8 的 over-triggering 说明过度主动是独立失败模式；我们目前没有把它作为一等指标看待，容易在「多说」和「少说」之间只调一个旋钮。
7. **缺统计兜底，但也最容易补。**
   E6（API-only conformal）与 E7（conformal 弃答）说明：**只调 API、拿不到 logits 也能给「误报率/幻觉率」一个可证明上界**；E3/E4 说明多采样一致性是免训练的可信度信号。这些是**当下就能挂在价值函数外面的门**。

**一句话**：我们缺的不是「更聪明的 LLM」，而是 A3 那条流水线里的 **intervention gating 环节**——一个**校准过的、成本不对称的、带打扰账本和等待期权价值的门**，把「是否触发」与「触发后带什么上下文」拆开。

---

## 4. 这份调研证明不了什么

- **不能横向比数**：这批基准（B1–B11）对「主动性」的定义互不相同（何时求助 / 补全隐藏意图 / 发现瓶颈 / 主动提问 / 时机准确率），报告不同的指标。**把它们的 F1/accuracy 放在一起比较是无意义的。**
- **没有一篇是在「桌面常驻精灵」上验证到可部署**：最贴近的是 B10（PIRA-Bench，桌面/手机屏幕流）和 C1/C2（可穿戴感官），但前者是基准、后者是穿戴设备；没有任何一条证据保证这些编排在 Windows 桌面持续屏幕流上同样成立。
- **「不用训练」的结论被高估了**：许多关键机制其实带训练——C3 的 TGL 是学出来的；C4 的门免训练但作者用**蒸馏**训练了配套学生模型；B1 明确主张「微调才引出主动性」；B2 的 RL 微调显示主动性可学；B9 作者也展示微调收益。**「主动性可以被学会」不等于「不训练就能达到同样的门控质量」。**
- **防打扰参数没有给出可复用的标定流程**：C1 的 θ、C4 的成本比、C5 的价值/成本权衡，论文只给结果，没给「在真实用户上如何把参数标定到稳」的流程。我读到的是**离线指标**。
- **反面证据的强度参差**：D1 是单作者预印本且带勘误（decay 项从未执行），D3 只在教育 persona 模拟场景。它们**指向**「LLM judge 和自适应时机没解决时机问题」，但**不足以定论**。
- **2026 年论文多为预印本**：我只核到 arXiv 记录，**未核实同行评审**；其中少数标注了会议（B2/B3/B5/B9/D2 等），其余评审状态未知。
- **我没有做任何复现**，也没有跑我们的 `timing.py`；本文件的「适配度」是主观评分。

**一句话**：本调研能证明「这些编排结构存在且被别人用过」，**不能证明哪一个在 OpenLookout 场景更有效**——那需要在我们自己的候选动作流上做 A/B。

---

## 附录 · 未核实 / 找不到的线索

1. **「A Survey of Proactive Conversational Agents」这个题名未核实到**。arXiv 上不存在该确切标题的综述；最接近的是 **2305.02750**（2023 IJCAI，*A Survey on Proactive Dialogue Systems*）与 **2404.12670**（2024 SIGIR Perspectives，*Towards Human-centered Proactive Conversational Agents*）。任务书若引用的是另一篇非 arXiv 综述，**我未能核到出处，按「未核实」处理**。
2. **「主动性拆成 触发/内容/时机/冷却 四个子问题」这一分解，我没有在任何一篇综述的原文里找到原样表述**。我核到的真实分解是：
   - A2：Intelligence / Adaptivity / Civility + 五建设阶段；
   - A3：state & need estimation → intervention gating → action construction → feedback adaptation；
   - B6：target planning + dialogue guidance。
   「冷却」在这些论文里**没有作为一个独立命名模块**出现（我在 A3、C1、C2 的 arXiv HTML 里检索 `cooldown` / `refractory` / `fatigue`，均无命中）；它以**用户打扰成本 / 预算 / over-triggering** 的形式存在。**如需「冷却」的显式形式化，本分区@不到，属 HCI/在线算法分区。**
3. **两个同名 ProactiveBench**：B1（2410.12361，文本，6,790 events）与 B2（2603.19466，ECCV 2026，多模态）。引用时必须带 arXiv 号。
4. **「π-Bench」的 π 字符在各种排版下可能写作 `pi-Bench`**；arXiv 记录为 `$π$-Bench`，编号 2605.14678。
5. 本文件**未**收录任何 HCI 中断文献与在线变点/序贯检验算法（BOCPD / SPRT 等），按任务边界留给其他分区。
