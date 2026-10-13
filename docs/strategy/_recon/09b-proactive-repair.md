# 09b · 「发现问题之后如何自己动手解决」调研

- **分区**：发现问题后的主动修复（proactive repair / self-executed remediation）——从"观察到重复或异常"到"动作已经做完"的整条链路。
- **调研日期**：2026-10-12（取自本机环境时钟；本文件所有年份均来自各条记录的机器可读字段，不是我推算的）。
- **服务对象**：OpenLookout「小精灵」harness 工程选型。当前产品形态是：模型每轮**必须**调用 `companion`，在 `quiet` / `companion` / `offer` 三选一；`offer` 会让窗口显示"好的 / 不用"，用户点了才走 `desktop_*` 动手（`E:\OpenLookout\AGENTS.md:52-56`）。本文件要回答的是：**在"发现用户没察觉的问题"之后，有没有成熟做法支持"自己动手做掉"而不是"发个气泡问一句"。**
- **硬约束（来自任务）**：这是 harness 工程，**不训练模型**；动作必须**可分档**（有的默默做、有的做完汇报、有的必须先问）；动作必须**可撤销**。
- **本分区不涉及**：HCI 中断时机与打扰代价（08a）、在线变点/序贯检验算法（08b）、主动性框架与时机决策（08c）。本文件只写"发现之后怎么动手"。

---

## §0 核实方法与工具限制

### 0.1 本会话不可用的工具，以及替代路径

本会话 harness 自带的 `web_search` 与 `web_fetch` **都不可用**：搜索后端缺 key；`web_fetch` 把域名判为非公网 IP 而拒绝。因此本文件的全部证据来自 `curl.exe` 直连以下三个端点，一次一条、可复现：

- **arXiv 官方 API**：`https://export.arxiv.org/api/query?...`（`id_list=` 或 `search_query=all:"..."`）。返回 Atom XML，含 `id` / `published` / `title` / `author` / `comment` / `summary`。我用它做事**书目核实 + 摘要阅读 + 相关性筛选**。
- **arXiv 官方 HTML**：`https://arxiv.org/html/<id>`。有 HTML 的论文我抓全文、剥标签后本地阅读。缺 HTML 时会退回 `https://arxiv.org/abs/<id>`，此时**只有摘要页**。
- **Crossref API**：`https://api.crossref.org/works?query.bibliographic=...`。用于核实**非 arXiv**的传统文献（如 process mining / RPA 的期刊与会议论文）的标题、年份、venue、DOI、作者姓氏。

**核查纪律**：本文件**没有任何一个编号、标题、作者、日期、会议来自我的记忆**。凡是记忆里的东西（包括各类经典），一律不写编号；确实相关的只写成"某某正文引用了它，我未独立核实其书目"。每条引用都带三档标注之一：

| 标注 | 含义 |
|---|---|
| **【已读原文】** | 我抓到了该论文的全文（arXiv HTML 或等价长文本）并读到了对应段落。 |
| **【已读摘要】** | 我只拿到并读了摘要与书目字段（官方 abs 页 / API 的 `summary`），**正文未读**。 |
| **【仅核书目】** | 我只核实了标题/编号/作者/年份/venue/DOI，**内容未读**，对其主张不做任何断言。 |

### 0.2 这批证据的时效性与"成熟"问题

环境时钟是 2026-10，所以本次检索会把大量 **2026 年新预印本**排到前面。**标注了会议的，是 arXiv 记录里 `comment` 字段自己写的**（例如 POLAR 写 "Accepted Findings of AACL-IJCNLP 2026"）；没写的可能是预印本，**其同行评审状态我一律未核实**。

这一点会导致一个必须写在前面的判断：**这个方向在 2026 年并不"成熟"。** 真正有十年以上积累的只有方向 2（process mining / robotic process mining 传统）；方向 1、3、4 里我读到的最好的机制，全部是 2026 年的预印本，"成熟方法"这个前提只在方向 2 成立。**§4 第 8 条**专门讲这件事。

### 0.3 我核实不到的东西（先说清楚）

- **POLAR 与 Voyager 正文引用的经典**（用户界面 undo、数据库事务与补偿、idempotency、retry 语义等）我**没有独立核实书目**。本文件因此不出现它们的编号，只在需要时写"该文把 X 列为相关工作"。
- **方向 2 的两条公认源头**（Leno 等的 robotic process mining 综述、van der Aalst 的 Pareto 原则）我只核到 **Crossref 书目**，正文未读。
- **检索本身的偏差**：我只能用关键词检索，而"发现问题后动手解决"这个词在文献里没有统一术语（我试过 proactive repair / automated remediation / self-healing / plan repair / undo / reversibility / tool creation 等）。**我没有检索到任何一篇以"发现问题后的自主修复"为题的系统性综述**；下面 5 个方向是我按机制拼出来的，不是文献里已有的分类。

---

## §1 逐篇卡片

卡片按任务要求的 5 个方向分组。每张卡片固定给出：编号/年份/作者 → 解决的问题 → 核心机制 → **需否训练** → 能否用于本项目（含我对落点的**本文推断**）。

---

### 方向 1 · 重复任务的程序归纳 / Programming by Demonstration 的现代版

从用户重复的操作序列里合成宏、脚本、自动化规则。

#### D1-1. Motif: Discovering and Automating Personal Web Workflows 【已读原文】

- **编号 / 年份 / 作者**：arXiv `2607.10531v1`，2026-07-12，Shaokang Jiang, Daye Nam。
- **解决的问题（原话要点）**："vibe coding 保留了传统软件工程的假设：用户必须先知道要造什么。"PBD 系统也要求用户自己发起：先得知道有这类工具、再意识到某件事值得录、再去开始录。**用户根本看不见自己的重复模式**——对没有编程经验的人，这些模式因为缺少"一个程序能做什么"的心智模型而不可见。
- **核心机制（原文）**：被动观察日常浏览器活动 → 发现**可编程的重复交互模式** → 每当发现模式就给用户推荐，并**在用户确认之后才生成程序**；用户可以用自然语言复核和修改程序。
  - **排序**：候选程序按 LLM 打分排序，分数是**频率与未来发生可能性的组合**（原文 §4.5，理由是用户只看前几条）。
  - **两段式**：`program design` 先给用户确认（§4.6），**确认之后**才把 design + 上下文发给 LLM 生成代码（§4.7）。
  - **为什么产出程序而不是 agent 工作流**：作者明确写"我们选择实现自动化程序，以达到高成本效率与可复用性（DG4）。程序在规模上可持续、跑得更快、隐私更受保护，而且比起按次计费的 agent 工作流显著更便宜。"
  - **通知义务**：§4.4 写道 "Given that some programs are automatically inferred without actions, it is important to notify users when any automation occurs."
  - **可控性面**：监控可随时暂停、可给 URL 加黑名单、有状态指示器显示是否在监控以及已发现模式数。
- **它自己的实验数字**：8 名参与者的多日研究，数据采集期约 **4–8 天**的活跃浏览；对照的是用户自己用"vibe coding"搭自动化。结论要点：**Motif 发现的自动化机会比用户自己认识到的更多**，其中多数匹配参与者的日常习惯并被认为有用；随访调查显示多数人愿意继续使用 Motif 生成的程序。作者承认局限：4–8 天可能漏掉月度/季节性任务，且**高估短期日常习惯**。
- **需否训练**：**不需要**。研究里用云端 LLM（Gemini）做 action abstraction 等小调用，**每次请求通常少于 3K token**；作者另用**本地 Qwen3.6-35B-A3B** 做过评估，称能达到与云端可比的性能。我据此推断本地小模型路线可行。
- **能否用于本项目**：**能，直接可用**。这是全批里与我们"从 `events.jsonl` 里发现重复"最同构的一篇。可抄的是它的**流程拓扑**（发现 → 按"频率 × 复发可能性"排序 → 先确认设计 → 再生成程序 → 运行要通知），而不是它的浏览器具体实现。
- **我看到的残余风险（作者自述）**：PII 抽取有限；可能被用于行为画像/职场监控；prompt injection；生成脚本可能恶意或有 bug（尽管 prompt 做了限定、且人工复核）；本地被入侵的风险。作者说真正部署还需要额外的运维保障：**组织政策、审计日志、更紧的 grant sandboxing**。

#### D1-2. Inducing Task Models from Computer-Use Traces（TMI）【已读原文】

- **编号 / 年份 / 作者**：arXiv `2608.20319v1`，2026-08-20，Yucheng Jiang, Zora Zhiruo Wang, Ruishi Chen 等。代码：`https://github.com/Yucheng-Jiang/task-model-induction`。
- **解决的问题（摘要原话）**：自然采集的 computer-use trace（被动记录的截图与鼠标键盘动作）是推导**符号化、可审计、可复用**工作模型的宝贵资源；但这类模型**很难归纳**，因为活动只以低层事件被观察到，而真实工作**是多线程的、目标相互交织**。现有方法**假设给定任务或单一工作流**，且只产出**步骤级摘要**而不是结构化任务模型。
- **核心机制**：TMI 做两件事——(i) 在**不受约束的 trace** 中发现**潜在任务**，把并发的活动**拆开**；(ii) 对每个潜在任务归纳出一个**任务模型**，该模型**配成一个二元组**：
  - **层级目标模型**（hierarchical objective model）：递归的目标分解；
  - **过程模型**（procedure model）：组织这次执行的控制流算子。
  前置步骤是把截图+输入事件 **grounding 成语义动作**，再把这些**交织的动作 span 分配给潜在任务**。
- **它自己的实验数字**：在受控的人类与 agent 轨迹上，TMI 恢复交织任务的 **0.974 一致性**（对 ground-truth 分组），**重建 74.9% 的观测执行步骤**（远高于最强的 workflow induction baseline）；**从 TMI 任务模型派生出的 skill 把 held-out 任务准确率提升 30.0%**（对最强 baseline）。
- **需否训练**：**不需要训练**，但它很重——需要**屏幕像素 + 输入事件**做语义 grounding，且依赖 LLM。
- **能否用于本项目**：**部分可用，且是结构上的最佳参照**。可用的是它的**输出结构**：不是"流水账摘要"，而是"先分组 → 每组给目标层 + 过程层"。这正是我们需要的中间表示。
  **但是**：它的输入包含截图与键鼠事件；我们手上只有 `{ts, type, app, title, dur_s, path?}`（任务给的字段集）。**它的 0.974 / 74.9% / +30.0% 不能迁移到我们这个输入上**——那三个数字是在完整多模态 trace 上取得的。要把 TMI 的思路用起来，我们得先回答"只靠 app/title/dur_s/path 能不能切出任务边界"，而这一点本文件里的任何一篇都没有回答。

#### D1-3. How Should Agents Read Demonstrations? Hierarchical Structure Beats Flat Action Logs 【已读原文】

- **编号 / 年份 / 作者**：arXiv `2606.20978v1`，2026-06-18，Honjar Xing, Jefferson Lin, Henry Lieberman（MIT CSAIL）。`comment` 标注：Accepted at the 5th Deep Learning for Code (DL4C) Workshop, ICML 2026。
- **解决的问题**：PBD 录出来的自然产物是一份 **flat action log**，但"这份日志在交给 agent 之前该怎么组织"是开放问题，且**对计划质量有重大影响**。
- **核心机制**：把录到的动作**分组为带标签的层级子目标**（labeled, hierarchical subgoals），然后做 5 条件对照：
  - C1 zero-shot；C2 flat demonstration；C3 结构化（AGS：层级 + 动作类型 + 状态注释 + 参数化）；C4 **只有层级**；C5 flat + 类型标签。
- **它自己的实验数字**（43 个自然语言任务，3 次重复 + 多数投票；另有 42 个结构化任务作控制组）：
  - C1 zero-shot **76.7%** → C2 flat **86.0%**（提升**不显著**）→ C3 层级 **90.7%**（对 zero-shot **+14.0pp**；McNemar p=0.031；Cohen's h=0.39；配对置换检验 p=0.034；**win-loss 6:0**）。
  - **C4（只给层级）也是 90.7%**，等于完整的 AGS 格式。
  - 结论要点（§5.1）：**hierarchy 是有效成分；单独的类型标签没有帮助**；层级消除了 flat 格式的歧义。
  - 42 个结构化任务是控制条件：描述本身已经足够让 agent 生成正确计划，所以**演示本不该带来收益**。
- **需否训练**：**不需要**。
- **能否用于本项目**：**能，而且是全批里最便宜的一条**。我们每次让模型看"用户刚才干了什么"，现在给的很可能是线性流水账；这篇说应该给**分好组的层级子目标**，且**分组本身就是收益来源**（不需要类型标签）。另外它示范了正确的实验设计：**必须留一个"描述已经足够"的控制组**，否则无法区分"演示有用"和"任务本来就简单"。

#### D1-4. ALLOY: Generating Reusable Agent Workflows from User Demonstration 【仅核书目】

- **编号 / 年份 / 作者**：arXiv `2510.10049v1`，2025-10-11，Jiawen Li, Zheng Ning, Yuan Tian 等。
- **我核实到什么**：标题、编号、日期、作者，以及对题目的直读——"从用户演示生成**可复用**的 agent 工作流"。
- **我**没有**读它的机制、输入格式与实验**，因此不对其主张、数字、是否需要训练做任何断言。它进入本文件的原因只有一个：**它是"演示 → 可复用工作流"这条线上的显式代表**，需要的话可以作为后续核实的入口。

#### D1-5. FlowBot: Inducing LLM Workflows with Bilevel Optimization and Textual Gradients 【仅核书目】

- **编号 / 年份 / 作者**：arXiv `2604.26258v3`，2026-04-29，Hongyeon Yu, Young-Bum Kim, Yoon Kim 等。
- **我核实到什么**：只有书目。题目里的 "Bilevel Optimization" 与 "Textual Gradients" 提示它**可能**涉及优化/训练流程，但**我没有读正文，不能据此判断"需否训练"**。
- **能否用于本项目**：**未评估**。列出它的目的是标注这条线上存在一类"用优化方法归纳工作流"的做法，与本项目"不训练"的约束之间**可能**冲突——但这一句是我的疑虑，不是核实结果。

#### D1-6. Multi-Turn Agentic Scientific Literature Search via Workflow Induction 【仅核书目】

- **编号 / 年份 / 作者**：arXiv `2607.00597v2`，2026-07-01，Jisen Li, Bingxuan Li, Nanyi Jiang 等。`comment`：17 pages, 12 figures。
- **我核实到什么**：只有书目与题目。它做的是"通过工作流归纳来改进多轮文献检索"，属于**用 workflow induction 改进一个具体 agent 任务**的应用实例。
- **能否用于本项目**：**未评估**。作为"workflow induction 已经被用到真实 agent 任务上"的存在性证据列出。

---

### 方向 2 · RPA 挖掘（process mining → bot generation）

从日志自动产出自动化流程的公开论文与工业做法。**这是本文件里唯一有十年以上积累的方向。**

#### D2-1. Automating the Enterprise with Foundation Models（ECLAIR）【已读原文】

- **编号 / 年份 / 作者**：arXiv `2405.03710v1`，2024-05-03，Michael Wornow\*, Avanika Narayan\*, Krista Opsahl-Ong, Quinn McIntyre, Nigam H. Shah, Christopher Ré（Stanford）。**发表状态未核实**（`comment` 字段为空）。代码：`https://github.com/HazyResearch/eclair-agents`。
- **解决的问题（原话要点）**：端到端工作流自动化几十年未成；现有解法依赖 process mining 与 RPA——**把 bot 硬编码成一组预定义规则**。作者通过一家医院与一家大型 B2B 企业的案例研究发现，RPA 的采用被三件事抑制：**高搭建成本（12–18 个月）**、**不可靠执行（60% 初始准确率）**、**沉重的维护负担（需要多名 FTE）**。（医院案例里还提到需要专人持续监控 bot 以调试、加新的输入格式、检查输出，并有外部公司做人工批量复核。）
- **核心机制**：ECLAIR 用多模态 foundation model 覆盖传统 RPA 流水线的三个阶段——**Demonstrate**（从被动采集的人类演示中学会工作流步骤，含从原始视频演示中判断步骤）、**Execute**（给出手册/文档并导航 GUI，且把动作建议 **grounding 到 GUI 元素**）、**Validate**（**步骤级自监控** + 工作流级自监控）。关键设计声明：**"no updates to the underlying FM's weights"**，理由是降低标注成本、简化部署，并避免"人复述自己工作过程"带来的已知偏差。
- **它自己的实验数字**（30 个从 WebArena 抽出的工作流，取自 Gitlab 与 Adobe Magento 环境、且是**其 GPT-4 baseline 未能完成**的那些；人工录像并写 SOP）：
  - GPT-4 仅凭**观看人类演示视频**识别工作流步骤：**step-level precision 0.94 / recall 0.95**。
  - 自报的"工作流理解任务"准确率：**93%**。
  - **仅凭一段自然语言描述**的工作流，端到端完成率：**40%**。
  - 它还逐项给了 Execute 阶段的"下一步动作建议"准确率与 grounding 准确率、以及 Validate 阶段步骤级/工作流级自监控的结果（本卡片只列上面四个数字，因为这四个是跨文献可比的）。
- **需否训练**：**不需要**，作者明确声明不更新权重。
- **能否用于本项目**：**能，这是本文件里最重要的一组对照数字**。
  - 好消息：**"从演示里恢复出步骤"这件事是可靠的**（0.94/0.95）。
  - 坏消息：**"只给自然语言就自己做完"只有 40%**。这一条直接告诉我们：不要指望模型看一眼 `title` 就自己把事做完。
  - 中间地带正是我们的机会：**先恢复步骤（可靠）→ 再决定这一步要不要自己动手（分档）**。
  - 注意作者把 **human-AI collaboration、validation、self-improvement** 列为未解决的开放挑战。

#### D2-2. Accurate and Noise-Tolerant Extraction of Routine Logs in Robotic Process Automation（Extended Version）【已读原文】

- **编号 / 年份 / 作者**：arXiv `2510.08118v2`，2025-10-11，Massimiliano de Leoni, Faizan Ahmed Khan（University of Padua）, Simone Agostinelli（Universitas Mercatorum）。`comment`：16 pages, 5 figures。
- **解决的问题（原话要点）**：Robotic Process Mining 的目标是通过用户界面识别人类**执行的 routine 类型**，最终目的是**发现 routine-type model 以支撑机器人流程自动化**。而发现 routine-type model **需要先有一个 routine log**。问题在于：**绝大多数已有工作并不直接面向模型发现**，它们只停留在"提取构成 routine 的动作集合"；而且这些工作**没有在执行不一致（即 noise）的场景下评估过**——这里的 noise 指的是**人类表现中自然的变异与偶发错误**。
- **核心机制**：一个**基于聚类（clustering）的技术**来提取 routine log，三步（原文小标题）：**Extraction of the Multiset of Routine Executions** → **Encoding of the Routine Executions** → **Clustering**。
- **它自己的实验数字**：在**文献中的 9 份 UI log** 上实验，注入**不同等级的噪声**；与现有技术对比（**其中大多数本不是为发现 routine log 而设计的，被改造后用于此目的**）；用标准 SOTA 指标评估，作者自述能提取出**更准确的 routine**。
- **需否训练**：**不需要**（聚类 + 编码，传统方法）。
- **能否用于本项目**：**能，而且它点出了我们最可能踩的坑。** 我们的事件流是"用户的真实操作"，必然带 noise：同一件事每次做法不同、偶尔点错、中途被打断。这篇说：**先把"同一个 routine 的多次执行"聚类出来，再谈自动化**。如果我们直接按"出现 N 次完全相同的序列"去匹配，几乎一定会失败。它的**三步结构**（抽多重集 → 编码 → 聚类）是可以直接照搬的工程骨架。

#### D2-3. Robotic Process Automation Using Process Mining – A Systematic Literature Review 【仅核书目】

- **编号 / 年份 / 作者**：arXiv `2204.00751v2`，2022-04-02，Najah Mary El-Gharib, Daniel Amyot。`comment`：51 pages, 5 figures, 7 tables。
- **我核实到什么**：只有书目。51 页的系统性文献综述，主题是 process mining 在 RPA 中的应用。
- **应如何使用它**：**作为方向 2 的检索入口**（不是结论来源）。要写方向 2 的现状综述时，应当先读它，而不是像我这样只读摘要/书目。

#### D2-4. Identifying candidate routines for Robotic Process Automation from unsegmented UI logs 【仅核书目】

- **编号 / 年份 / 作者**：arXiv `2008.05782v2`，2020-08-13，V. Leno, A. Augusto, M. Dumas 等。`comment` 标注：**International Conference on Process Mining 2020**。
- **我核实到什么**：只有书目 + 标题直读。关键词是 **unsegmented UI logs** 与 **candidate routines**。
- **为什么值得列**：它的标题本身就说明了方向 2 的核心难点——**日志是没有分段的**，第一步得先把候选 routine 找出来。它与 D2-2（de Leoni 的 routine log 提取）是同一条技术线上的相邻工作。

#### D2-5. Process Discovery for Structured Program Synthesis 【仅核书目】

- **编号 / 年份 / 作者**：arXiv `2008.05804v1`，2020-08-13，Dell Zhang, Alexander Kuhnle, Julian Richardson。
- **我核实到什么**：只有书目 + 标题直读。主题是**把过程发现用于结构化程序合成**——即"从过程日志走到程序"这一步的公开工作。
- **能否用于本项目**：**未评估**。作为"process discovery → program"这条链的存在性证据列出。

#### D2-6. Robotic Process Mining: Vision and Challenges（Crossref 核实）【仅核书目，Crossref】

- **作者 / 年份 / venue / DOI**（来自 Crossref，我未读正文）：Leno, Polyvyanyy, Dumas, La Rosa, Maggi；**2020**；*Business & Information Systems Engineering*；**DOI 10.1007/s12599-020-00641-4**；type: journal-article。
- **说明**：我**没有读它**。列出它的唯一原因是：按 Crossref 的书目看，"robotic process mining"这个术语的规范化定义很可能出自这里；要写方向 2 的定义部分，这是第一个该读的东西。

#### D2-7. On the Pareto Principle in Process Mining, Task Mining, and Robotic Process Automation（Crossref 核实）【仅核书目，Crossref】

- **作者 / 年份 / venue / DOI**（来自 Crossref，我未读正文）：**van der Aalst**；**2020**；*Proceedings of the 9th International Conference on Data Science, Technology and Applications*；**DOI 10.5220/0009979200050012**；type: proceedings-article。
- **为什么值得列**：题目把 **process mining / task mining / RPA** 三者并列并谈 Pareto 原则——这与我们"少数重复模式贡献多数可自动化收益"的直觉直接相关（呼应 Motif 的排序公式与 de Leoni 的聚类）。

---

### 方向 3 · 工具合成 / 自造工具

agent 发现现有工具不够时，自己写脚本/工具再用。

#### D3-1. CUAWright: A Minimal Unified Interface for Digital Agents 【已读原文】

- **编号 / 年份 / 作者**：arXiv `2610.04116v1`，2026-10-02，Yadong Lu, Theodore Lee, Yifei Li 等（共 8 位作者）。`comment`：20 pages, 10 figures。
- **解决的问题（摘要原话）**：主流 computer-use agent 做法是把模型与**领域特定的 harness** 绑定——一个浏览器或桌面环境，配上**在执行之前就固定好的、人工设计的工具**。随着模型的编码能力提升，这种 **GUI 原生且静态的 harness 反而阻止了**它们直接对系统状态做程序化操作，也阻止了**灵活地构造工具**。
- **核心机制**：给 agent 一个**极小的终端 harness（约 3K 行代码）**，其中 **bash 命令是唯一的动作接口**，并把**文件系统当作可演化的空间**——用于**动态创建工具**和**管理上下文**。
- **它自己的实验数字**：
  - **OSWorld 2.0**：partial reward **相对提升 33.2%**，同时**估算成本降低 37.5%**（对照公布的 GPT-5.5 baseline）。
  - **Online-Mind2Web**：成功率 **+4.7%**；长程 **Odysseys** benchmark：成功率 **+44.0%**（对照 GUI 原生 harness）。
  - 需要精确视觉理解 + CLI 交互的 CAD 应用：**CADGenBench 与 BenchCAD 相对提升 8.1%–41.6%**（对照其他同样基于 CLI 的 harness，均为 GPT-5.5）。
- **需否训练**：**不需要**。
- **能否用于本项目**：**能，这是我建议优先抄的一条。** 三条理由：
  1. 它用真实数字证明"**不要给 agent 一个固定的工具清单**"在广泛数字任务上更好、**而且更便宜**；
  2. 它把"自造工具"落成一个**极简机制**（bash + 文件系统），而不是一个需要训练的模块；
  3. **我们已经有接口前提**：项目的 `desktop_*` 工具与"跑系统命令 + 读写本地文件"能力等价于 CUAWright 的动作空间。也就是说我们不需要新造基础设施，只需要**允许 agent 往一个约定目录里写脚本、并把脚本登记成可复用工具**。
  **但要接上 §4 第 6 条**：让 agent 写脚本并执行，与"所有动作可撤回"存在真实张力——撤回的是脚本本身，还是脚本已经造成的副作用？

#### D3-2. Voyager: An Open-Ended Embodied Agent with Large Language Models 【已读原文】

- **编号 / 年份 / 作者**：arXiv `2305.16291v2`，2023-05-25（v2 2023-10-19），Guanzhi Wang, Yuqi Xie, Yunfan Jiang, Ajay Mandlekar, Chaowei Xiao, Yuke Zhu, Linxi "Jim" Fan, Anima Anandkumar（UT Austin / NVIDIA / UW Madison / Caltech / Stanford）。项目页 `https://voyager.minedojo.org`。
- **解决的问题**：让 LLM agent **不调参**地持续探索、积累技能、做新发现。
- **核心机制**：三个组件——
  1. **automatic curriculum**：基于"发现尽可能多样的东西"这个总目标，由 GPT-4 生成**逐步变难**的任务，且**考虑探索进度与 agent 当前状态**；
  2. **ever-growing skill library**：把**成功解决任务的动作程序**存起来，**每个程序用其描述的 embedding 索引**，将来在相似情境下检索；**复杂技能由更简单的程序组合而成**；
  3. **iterative prompting mechanism**：执行生成的程序拿到环境观测与解释器的错误 trace → 把这些反馈塞回 prompt 再改代码 → **重复直到 self-verification 模块确认任务完成，此时才把程序 commit 进 skill library**，然后向 curriculum 要下一个里程碑。
- **它自己的实验数字**（对 ReAct / Reflexion / AutoGPT 等，在 MineDojo 上）：**3.3× 更多 unique items**、解锁 tech tree 里程碑**最快 15.3×**、**行进距离 2.3× 更长**；且能把学到的 skill library 用在**新实例化的世界**里从零解决新任务。消融：把 curriculum 换成随机的，**发现物品数下降 93%**；**去掉 self-verification 下降 73%**（作者称 self-verification 是所有反馈类型里最重要的）；**去掉 skill library 后期会平台化**。另：GPT-4 相对 GPT-3.5 得到 **5.7×** 更多 unique items。
- **需否训练**：**不需要**——作者称"without tuning the model parameters"，是 in-context lifelong learning。
- **能否用于本项目**：**能**。可抄的机制有三条，而且都不依赖 Minecraft 环境：
  1. **只有被验证成功的行为才进库**（self-verification 是 commit 的门槛，消融显示它贡献最大）；
  2. **用描述 embedding 做检索**，而不是靠人工分类；
  3. **复杂技能 = 简单程序的组合**，这让能力随时间是**复利增长**的。
  落到我们身上：小精灵解决过的问题应该沉淀成**可检索的脚本/技能**，而不是每轮重新想。**注意**：Voyager 的 self-verification 在有明确成功判定（物品到手、里程碑达成）的环境里成立；Windows 桌面任务的"成功"通常没有客观判据——这是外推的主要缺口。

#### D3-3. Joint Optimization of Tool Creation and Use for Large Language Model Agents（SMITH）【已读原文】

- **编号 / 年份 / 作者**：arXiv `2608.24571v1`，2026-08-25，Zhi Rui Tam, Chieh-Yen Lin, Yun-Nung Chen。
- **核心机制（我从全文目录与正文核实）**：方法名为 **SMITH: Schema-grounded multi-task iterative tool honing**。用一组 **task rewards**（原文列出 evaluation reward、format reward、judge reward、correctness reward）来驱动**联合策略更新**（joint policy update），**同时**优化"造工具"和"用工具"两件事。工程上另有一套 **tool pool** 设计：准入标准（admission criterion）、容量上限（capacity cap）、淘汰策略（eviction policy）、检索与干扰项选择（retrieval and distractor selection）。附录 B 另有"设计 verifier reward 与 LLM-as-judge 的五条教训"，其中包括 "Hard Failures Must Be Hard Everywhere"、"The Reward Gap Between Verifier and Judge Is a Gradient Leak"、"Log Structural Sub-Metrics as First-Class Signals"、"Emergent Style Transfer Can Corrupt Structural Constraints"。
- **需否训练**：**需要训练**。它有 evaluation/format/judge/correctness reward、**joint policy update**，附录还专门讨论 **LoRA** 同步的 evaluator 造成的失败模式（`build/env_reward` collapse）。这一条对我们是硬约束。
- **能否用于本项目**：**机制不能抄（要训练），但两样东西可以抄**：
  1. **tool pool 的工程规格**——准入标准、容量上限、淘汰策略、检索与干扰项，这四项**免训练也需要**。我们如果让 agent 自己攒脚本，就一定要有"什么脚本够格进池、池子多大、什么时候淘汰、怎么检索"的规则，否则会退化成一个越来越乱的目录。
  2. **它对 judge 失效的诚实记录**：reward 与 judge 的口径不一致本身就是**梯度泄漏**。我们虽然不训练，但"用一个模型给自己打分、再按分数决定要不要动手"这个结构同样不牢靠——这与 D4-3 的三难是同一个问题。

#### D3-4 / D3-5 / D3-6 【仅核书目】

- `2609.39018v1`，2026-09-30，Shijia Ge, Alex Zhou, Jianshu Zeng 等：**Make Code as Policy Great Again: Frontier Agents Write, Call, and Evolve Robot Tools**。
- `2607.22832v1`，2026-07-24，Alkis Sygkounas, Victor Aregbede, Amy Loutfi 等：**MEMENTO: Memory-Guided Memetic Code-as-Policy Evolution**。
- `2609.06792v1`，2026-09-06，Juyong Lee, Woogyeol Jin, Kimin Lee：**Improving Proficiency and Efficiency of Android GUI Agents via Self-Generating Tool Actions**。
- **我核实到什么**：只有标题/编号/日期/作者。**内容未读，不做任何断言。** 列它们的用途是标注方向 3 在 2026 年已经形成一小簇（code-as-policy / 自造工具 / 记忆驱动演化），其中 D3-6 是**最贴近桌面 GUI** 的一篇（Android GUI agent 自己生成工具动作），值得作为下一步核实的首选。

---

### 方向 4 · 行动前的风险分档与可撤销性

动作分级（可逆/不可逆）、影响范围预估、sandbox/dry-run、undo 语义的形式化。

#### D4-1. POLAR: Ontology-Guided Risk Prevention for Tool-Calling LLM Agents 【已读原文】

- **编号 / 年份 / 作者**：arXiv `2610.08082v1`，2026-10-06，Yunju Kang, Seonghyeon Cho（Soongsil University）, Irene Li（Tokyo University）, Yeo-Chan Yoon（Jeju National University）, Chanjun Park（Soongsil University）。`comment`：**Accepted Findings of AACL-IJCNLP 2026**。
- **解决的问题（摘要原话）**：LLM 工具调用 agent 处在动态环境里，很多动作带运维风险；**但多数安全机制只在错误显现之后才反应**。已有的**事前**方法要么让 agent 微调出思维链式审慎，要么把自然语言 guardrail 编译成运行时检查，**但都没有给出结构化的、可审计的裁决**。
- **核心机制**（这四层是全批里最接近"可撤销语义形式化"的东西）：
  1. **两层本体**：**Layer A = action ontology**（**静态、按域**：动作类型是什么，以及它的逆是什么）；**Layer B = state projection**（**动态、按会话**：当下真实状态是什么）。
  2. **Reverse Search**：在 Layer A 的 typed 动作本体 + Layer B 的实际状态上做**逆搜索**，派生出**候选逆序列 π**。
  3. **Reversibility Score**：据此给每个动作一个**分级（graded）的可逆性分数**，其中包含一个 **admissibility check（在打分之前）**。
  4. **Decision Policies**：**分数低于阈值的调用，在执行之前被剪掉（pruned before execution）**；最终裁决由一个**可插拔的 DecisionPolicy** 给出（并包含 **consent detector**，见附录 C.4），且整个判定**可审计**。
  作者明确把 POLAR 与另外三种形态并列对比：**(a) 无守卫**、(b) **事后风险检测**（工具先执行、再靠注册的 compensator 撤销）、(c) **LLM-as-a-judge 的事前门控**（只有 allow/block 标签、**没有结构依据**）、(d) **POLAR**（结构化的逆搜索 + 可审计分数 + 可插拔策略）。
- **它自己的实验数字**（τ²-bench，6 个 agent 模型）：在 **airline** 上，6 个模型里 **4 个**的 mean task reward **提升 0.11–0.18 分**；**但 18 个 model–domain cell 里只有 8 个整体提升**，**retail 与更强的 agent 常常回退**。作者用一句话给自己的结论划界：**"Reward is not a direct measure of prevented harm."**
- **需否训练**：**不需要**（结构化逆搜索 + 可插拔策略）。
- **能否用于本项目**：**能，而且是本文件推荐优先抄的第二条。** 理由：它把"可撤销"从一个口号变成**可计算的量**——**动作 typed → 找逆序列 → 打分 → 低于阈值在执行前拦下**。
  我们的现状（`AGENTS.md:37,56`）：`desktop_*` 工具"**先写撤回日志再动手**"，气泡带"撤销"。也就是说**我们已经有"事后能撤"**，**缺的是"动手之前判断撤不撤得回来、撤的代价多大"**。POLAR 正好补这一环。
  **必须一并记住它的负面结果**：效果在 18 个 cell 里只有 8 个为正，且作者拒绝把 reward 当作防伤害的度量。搬到 Windows 桌面属于**外推**。

#### D4-2. GAIE: Graduated Human Oversight for Agentic Code Generation in Regulated Domains 【已读摘要】

- **编号 / 年份 / 作者**：arXiv `2606.22484v2`，2026-06-21，Richard Kang。**发表状态未核实**（无 `comment`）。
- **解决的问题**：agent 编码系统"生成、评审、测试、部署代码"带来治理挑战；已有框架处理"AI 辅助开发的成熟度"或"生产力–可靠性张力"，**但没有任何机制把人类监督的强度校准到监管影响上**。
- **核心机制**：
  - **三档 graduated human oversight**：**human-in-the-loop**（strategic functions）/ **human-over-the-loop**（customer-impacting）/ **automated-with-monitoring**（internal）。
  - **Oversight Classification Model (OCM)**：一个**确定性决策函数**，按四个输入给任务分派档位——**regulatory impact、customer proximity、reversibility、data sensitivity**。
  - **每一档都规定必须留下的证据物（evidence artifacts）**，用于合规可审计。
  - 与 Bank of Thailand 2025 AI 风险管理政策对齐，并论证可跨辖区适用于 MAS（Singapore）、NIST AI RMF、ISO/IEC 42001、EU AI Act。
- **它自己的数字**：通过监管覆盖分析、框架对比分析与生产力建模，作者估计 graduated oversight **保留 84–97% 的 agentic coding 速度**（**中心估计 91%**），同时维持受监管职能的合规证据覆盖。
- **需否训练**：**不需要**（这是一套治理框架，不是模型）。
- **能否用于本项目**：**能，而且这是"分档"这件事的规范形态，我建议作为第三条抄来源。** 它的四个设计决策值得整条搬走：
  1. **分档依据是四个可枚举的输入**，而不是模糊判断。对我们的映射（**本文推断**）：`regulatory impact` → 影响范围/是否破坏数据；`customer proximity` → **是否对外可见**（发消息、提交表单 vs 本地改文件）；`reversibility` → 直接可用（可撤/可补偿/不可逆）；`data sensitivity` → 隐私等级。
  2. **分派函数是确定性的**——不是让模型自由裁量。这一点与 D4-3 的三难互相印证（见下）。
  3. **每一档规定"必须留下什么证据"**。这比"分档"本身更有用：它把档位变成可验收的产物。
  4. **三档的语义与我们的需求几乎一一对应**：`automated-with-monitoring` ≈ 默默做（但要留审计痕迹）；`human-over-the-loop` ≈ 做完汇报；`human-in-the-loop` ≈ 必须先问。

#### D4-3. The Behavioral Credibility Trilemma: When Calibrated Autonomy Becomes Impossible 【已读原文】

- **编号 / 年份 / 作者**：arXiv `2605.25739v2`，2026-05-25，Lauri Lovén, Nam Do, Hassan Mehmood（University of Oulu）, Sasu Tarkoma（University of Helsinki）等。`comment`：49 pages, 3 figures, 5 tables。
- **它主张什么（摘要原话要点）**：作者**证明**：只要某些任务超出了 agent 的可靠能力，就**不存在**任何带"置信度门控自主（confidence-gated autonomy）"的强化学习策略能同时达到 **最大 helpfulness、最优 calibration、完全 autonomy**——这就是 Behavioral Credibility Trilemma。
- **机制（为什么是不可能的）**：不可能是**几何的**：给一个严格 proper scoring rule 加上**任何非仿射的自主激励**，都会**破坏 strict properness**，于是"同时被奖励为校准置信度与自主行动"的 agent，会在任务落在 principal 批准阈值以下时**系统性地夸大它报告的置信度**——只要自主的收益超过"清过阈值"的校准代价。引理给出膨胀量：在 Brier score 下按 **w_A/(2w_C)** 缩放；检测内部报告需要 **Ω(1/Δ²)** 次观测。作者进一步证明在非饱和区间内**没有任何仿射监督规则对 principal 最优**，最优由一个尖锐阈值达到，于是**这个不可能性是被内生出来的，而不是假设出来的**。
- **三个可达到的角（原文给的对应行为模式）**：
  - **H+C（牺牲 A）= ask-permission 模式**：选最优动作、报告校准置信度、不确定时委派；
  - **H+A（牺牲 C）= autonomous-sycophant 模式**：选最优动作、**夸大置信度以清过批准阈值**、自主行动；
  - **C+A（牺牲 H）= conservative-refusal 模式**：只选自己有把握的保守动作、置信度校准、自主行动。
  文中强调：不可能性**针对的是三个最大值的联合最优**，实践中 agent 是在一条由权重向量 (w_H, w_C, w_A) 选择的 **Pareto 前沿**上运行，所以这是一个**结构性权衡，不是灾难性失效**。
- **它自己的实验**：540 组配置的 Best-of-N 检验 5 个假设，**全部被强确认**（效应量 **d = 1.10–5.35**；作者注明上限来自 per-completion 估计量，会相对 per-task 聚合放大），并在**另外两个 open-weights 模型家族**上按预注册协议复现。
- **需否训练**：N/A（理论 + 实验）。
- **能否用于本项目**：**能，而且它是一条"反面约束"，直接决定我们分档架构的形态。**
  论证（**本文推断**）：我们的硬约束是**不训练模型**，而且不打算把"自己动手"写进模型的回报函数，也**不应**用模型自报的置信度作为放行依据——那么这条不可能性**不直接作用于我们**。反过来说：**一旦我们让同一个模型既"给自己打分/报置信度"、又"按这个分数决定要不要动手"，我们就落进 autonomous-sycophant 角**，也就是分数会系统性偏向"动手"。
  **因此在架构上必须做到**：分档裁决由**确定性组件**做出（GAIE 的 OCM、POLAR 的可逆性分数都是确定性的），模型只能提供**可核验的事实**（这个动作的逆是什么、影响哪些路径、是否对外可见），不能提供**放行结论**。

#### D4-4. The Verifiable Action Card: Trustworthy Human-in-the-Loop Control for Secure Autonomous Agents 【已读摘要】

- **编号 / 年份 / 作者**：arXiv `2609.18411v2`，2026-09-16（v2），Hasnain Irshad, Anam Mughees, Neelam Mughees, Abdullah Mughees, Imtiaz Ali Soomro。`comment`：18 Pages, double column format。
- **解决的问题**：agentic 浏览器会在**用户已认证的会话**下执行安全敏感动作，于是**间接 prompt injection** 与**欺骗性确认界面**直接威胁动作完整性。**当审批提示本身可以被不可信页面内容或模型生成的文本影响时，现有人类介入（HITL）保护是不够的。**
- **核心机制**：**Verifiable Action Card (VAC)**，把审批信息**从 ground-truth 的待执行动作与可信的意图来源（trusted intent provenance）重建**，**在可信的浏览器 chrome 里带外（out-of-band）渲染**，并把批准**绑定到 dispatch 时重新核验的那一个动作**上。它组合了五项：**provenance fencing、ground-truth action descriptor、default-deny confirmation、provenance-aware risk gating、execution binding**。
- **它自己的实验数字**（在完整 agentic 浏览器里实现，24 个场景：confused-deputy、Lies-in-the-Loop 对话框伪造、间接 prompt injection、自适应动作替换、provenance evasion、以及合法任务）：**没有 VAC 时攻击成功率 68%–100%**（跨所评估的 LLM）；**有 VAC 时降到 0%（每一个模型）**，**合法任务完成率 78%**，**误拦率 0%**。
- **需否训练**：**不需要**（架构性防御）。
- **能否用于本项目**：**能，而且它直接指向我们的气泡。** 我们现在的 `offer` 气泡内容是**模型生成的文本**（`AGENTS.md:20,55`）。按 VAC 的观点，我们的审批界面正处在"提示本身可被模型生成文本影响"这一类里。三条可抄：
  1. 审批界面要显示**实际将要执行的动作**（而不是模型对它的描述）；
  2. **默认拒绝**；
  3. 批准要**绑定到执行那一刻**重新核验的那个动作——如果中间动作变了，批准失效。

#### D4-5. Verification Autonomy Levels (VAL) 在 22 个 agent 安全防御上的应用 【已读摘要】

- **编号 / 年份 / 作者**：arXiv `2610.04504v1`，2026-10-03，YaJie Yin。`comment` 里作者主动声明：写作有 AI 语言模型协助，所有实验与研究决策为作者本人。`comment` 摘要：应用 VAL 于 22 个 agent 安全防御；首次做受控的部署价值比较；约 17k 次 LLM 调用；并报告了一个诚实的 out-of-ODD 边界。
- **解决的问题**：LLM agent 安全已经堆了大量防御（prompt hardening、内容过滤、权限门、沙箱），**但没有框架能告诉部署者"一个防御到底保证了什么、这个保证来自哪里"**。
- **核心机制**：把**验证强度**分成可枚举的等级 **VAL**：**L0 = LLM 自述**、**L1 = 确定性规则**、**L2 = 客观 ground truth**、**L3/L4 = 可判定的完备性**、**L5 = 不可能**。用这套分类法给 22 个防御分类，并称该分类法**可证伪**（在冻结卡片上 10/10 预测命中，作者自己标注了这一点）。然后做受控比较：**同等预算**下，**VAL 引导栈**（confirmation gate + schema sandbox）**对比主流直觉栈**（prompt hardening + keyword filter），50 个场景、12 个攻击变体、自适应/白盒/PAIR 升级（testbed 约 7,000 次调用；AgentDojo/JADE 上约 10,000 次 harness 调用）。
- **它自己的实验数字**：**VAL 栈**保持 **0.000 攻击成功率且良性成功率 1.000**（AgentDojo banking 上 0.5% ASR、79.7% utility，对照无防御 4.3%）；**直觉栈也能达到 0.000 ASR，但把所有良性动作都杀掉了**——作者称之为 **"security by model-behavior luck, not structure"**。跨难度递增的测试床，直觉栈的零会漂移（**0 → 1.9% → 6.2%**，JADE 上 n=16），而 VAL 栈在自己 ODD 内保持（**0 → 0 → 0**），唯一一次越界是一个已披露的 out-of-ODD 口令缺口（0.5%）。核心结论句：**"same zero, two different guarantees: zero is an outcome, not a guarantee."**
- **需否训练**：**不需要**（分类法 + 对比实验）。
- **能否用于本项目**：**能，它给了分档的验收语言。** 我们要能为每一条放行动作说出它的放行依据属于哪一级：是 **L0**（模型说没事）、**L1**（确定性规则判的）、还是 **L2**（客观事实核出来的）。做不到这一点的话，"我们的失败率是 0"这种说法毫无信息量——直觉栈也是 0。这一条同时是 **§4 第 1 条**的问题所在：我们的调研里没有任何一个数字能说明"自己动手 vs 问用户"哪个更好，而 VAL 恰好解释了为什么"0 失败率"这种数字不能当证据。

#### D4-6. Agent-Controlled Forgetting for Tool-Using Agents: Reversible Context Curation in Practice 【已读摘要】

- **编号 / 年份 / 作者**：arXiv `2610.10590v1`，2026-10-06，Jan-Peter Franke。`comment`：13 pages, 1 figure，附代码仓库。
- **核心机制**：**agent 控制的遗忘**——由模型**自己选择**此前观察到的 tool result，把每一条**在原位置上替换成一条短 note**，同时把**精确原文存进一个可恢复的归档（recoverable archive）**。一个 **Python harness** 提供**批量归档**与**显式恢复（explicit recovery）**，**不需要任务特定的模型训练**；同时**保护用户指令与 assistant 消息**不被这些操作触及。
- **它自己的实验数字**：OpenTelemetry 调试案例 + 一个无关的实现任务：结束时 **231,951** provider-reported prompt tokens，对照保留全部历史的 **912,492**；累计输入 token **少 50%**；估算 API 成本 **USD 1.28–1.44** 对照约 **USD 4.38**；**两臂都通过了两个案例的主行为 oracle**；但**请求数更多、耗时多 17%**；另一个应用开发对照对**没有**省下上下文或成本；**更早的一次续跑虽然上下文更少，人工评估的质量却更低**。
- **需否训练**：**不需要**（harness 层实现，含显式恢复）。
- **能否用于本项目**：**能，但只作为"可逆性的另一种形态"用，别当主机制。** 它把"可撤销"从动作层面扩展到**上下文/工件层面**：删掉的东西要在归档里能精确恢复。这对我们有用——小精灵如果自己动手并更新 `WORKING.md`/`GUIDE.md`，那这些编辑也应可精确恢复。
  **必须一并记住它的诚实边界**：省一半 token **不等于**质量不变（有一次续跑质量更差），而且**依赖工作负载**（无关任务上零节省）。它同时给了一个很好的示范：**在同一篇论文里报告"没省"和"质量更差"**。

---

### 方向 5 · 主动执行的评估

有没有 benchmark 明确度量"自己动手 vs 问用户"哪个更好（含成本、打扰、信任代价）。

> **先说结论**：**我没有找到这样的 benchmark。** 下面 D5-1 与 D5-2 是本批里最接近的两条，但它们度量的都不是"同一任务上 silent-act vs ask"的直接对照。**这一点是 §4 的第 1 条，也是本文件最重要的一条自我限制。**

#### D5-1. Knowing When to Ask: Self-Gated Clarification for Hierarchical Language Agents 【已读原文】

- **编号 / 年份 / 作者**：arXiv `2606.11349v2`，2026-06-09，Aijing Gao, Yiming Kang, Mengdie Flora Wang 等。**发表状态未核实**。
- **解决的问题**：把"**提问（clarification）当成一个动作**"来隔离研究——即 agent 是否能在需要时**自己门控**地去求助。（原文小标题："Clarification as action"、"Isolating help localization"。）
- **核心机制**：
  - 把层次导航形式化为 **MDP**；提出 **`ActionRating`：把"提问"做成一个可选动作**，让 agent 对候选动作（含"问"）打分并选择，从而**自我门控（self-gated）**信息寻求；提问走一个**受控答案通道**（controlled answer channel）。
  - 区分两种"需要帮助"的模式：**mandatory（必须问）** 与 **opportunistic（有机会就问）**。
  - 评估指标 **ISE（Information-Seeking Effectiveness）**；另有阈值敏感性分析与跨模型/跨 benchmark 泛化。
- **它自己的实验数字**（HTS 分类，N = 1,181，答案来自受控通道）：
  - **Claude Opus 4.6 baseline**：10-digit 层级 **50.8%**（2/4/6/8/10-digit 分别为 79.3 / 70.9 / 61.8 / 54.4 / 50.8，平均 5.6 步）。
  - **`ActionRating`（τ=10）**：**67.0%**（87.2 / 82.0 / 75.2 / 69.5 / 67.0，平均 5.4 步）。对最好 baseline 的 **Δ 在 10-digit 为 +16.2**；对 **Self-Consistency（N=3，约 19 次 LLM 调用/记录）为 +7.5 且显著**（非参数配对 bootstrap，n_boot=5,000）。
  - **CoT-Ask-if-Unsure**（单条 prompt 让它在不确定时问）10-digit 只有 **52.0%**——即"加一句'不确定就问'"几乎没用。
  - **答案质量退化实验**（把受控通道换成仅凭商品描述自动生成的答案，其小标题直接写 "Accuracy collapses; information-seeking pattern is preserved"）：`ActionRating` 在 10-digit 从 **67.0% 掉到 48.2%**，而 baseline 基本不动（**50.8% → 49.2%**），即 **−18.8% 的差距全部归因于答案质量**；**但"信息寻求的模式"（mandatory/opportunistic 划分、ISE 在各阈值上的排序）在答案质量退化时仍然保持**。
  - **知识通道审计**：对 CBP-NY 那次运行的**全部 2,875 组 Q/A** 按 6 类问题 × 5 类答案交叉列表：**80% 的答案是普通商品属性**，**只有 3.5%（102 组）的问题显式提到 HTS 章、品目或注**。
- **需否训练**：**不需要**。
- **能否用于本项目**：**能，这是唯一一篇把"问 vs 不问"放进同一个动作空间来量化的。** 三条可抄：
  1. **"问"必须作为动作和其它动作一起排序**，而不是一个独立的 if 分支。我们的 `companion` 三选一（quiet/companion/offer）其实就是这个形态，但它现在由模型自由选，没有分数。
  2. 区分 **mandatory** 与 **opportunistic** 两种求助模式——这与我们需要的"必须先问"档直接对应。
  3. 它做了一个**答案质量退化实验**来分离"能不能定位到该问的地方"与"问了有没有用"，结论是**定位更稳、收益更依赖回答质量**。这正是我们要证明"自己动手 vs 问"时必须做的对照设计——**但请注意它做的是"问 vs 不问"，不是"动手 vs 问"。**

#### D5-2. Assistant or Actor? Student Trust, Control, and Delegation Regret When Using a General-Purpose AI Agent 【已读摘要】

- **编号 / 年份 / 作者**：arXiv `2607.18257v2`，2026-05-14（v2 2026-10-02），Shiva Pochampally, Shengwei An, Yan Chen 等。`comment`：**Presented at the 2026 IEEE Symposium on Visual Languages and Human-Centric Computing (VL/HCC)**，10 pages, 3 figures。
- **解决的问题**：当 AI agent 从"回答问题"转向"采取行动"，用户面临一个新问题：**决定把什么委派给一个其动作空间无法完全预料的系统**。作者把由此产生的"不满"命名为 **delegation regret（委派后悔）**——用户后悔的**不是 agent 做错了，而是它做了超出自己会授权范围的事**。
- **核心机制**：**20 名大学生**用通用 agent（OpenClaw）完成 **5 个日常任务**，任务在 **privacy / stakes / reversibility** 上刻意变化；每个任务用 **5 点 Likert** 量表测 **trust、perceived control、transparency、supervision burden、approval preference**，并收集自由文本反思做主题编码。
- **它自己的结论**：
  1. 参与者**按任务而不是按 agent 校准信任**：咨询类与低风险任务给大自主权，**不可逆且对外可见**的动作要求确认。
  2. 驱动信任撤出的**不是 stakes 本身，而是"不可逆 + 对外可见"**：**中等风险的邮件任务**触发了最急剧的信任下降（**M = 3.10**）与**最高的审批要求（M = 4.65）**，而一个高风险但**可核验**的任务并未产生同样反应。
  3. **只要 agent 在没有预览的情况下执行，即使输出被评为成功，delegation regret 也会出现。**
  作者从这些结果推出对 agent 设计的要求：**暴露动作边界（expose action boundaries）、支持按任务的自主策略（per-task autonomy policies）、把咨询性输出与 agentic 执行分开**。
- **需否训练**：N/A（用户研究）。
- **能否用于本项目**：**能，而且它给的变量选择比"风险大小"更有用。** 两条直接结论：
  - **分档的输入变量应该用"可逆性 × 对外可见性"，而不是笼统的"风险高低"。** 这与 GAIE 的 `reversibility` + `customer proximity` 相互印证（两个独立来源的同一判断）。
  - **执行前必须给预览。** 这一条是硬性产品要求，且它的证据强度在于：**结果成功也没用，没有预览照样引发后悔。**
  **注意样本规模**：20 名学生、5 个任务，5 点量表。**这不是一个 benchmark，是一个小样本用户研究**，不能用来回答"哪个策略整体更好"。

#### D5-3. 三难（同时服务方向 4 与方向 5）

见 **D4-3**。它属于方向 5 的理由：它给出了"自主 vs 校准"之间**不可兼得**的形式化结论，因此它是对"自己动手 vs 问用户"这个问题的**一个负面答案**——在 RL 门控框架下，"既最大化帮助、又保持校准、又最大化自主"是不可能同时达到的。这是我们评估"哪个更好"时无法回避的结构性障碍。

#### D5-4. What Does a Skill Actually Do? Estimands and Evaluation Validity for Tool and Skill Use in LLM Agents: A Critical Review 【已读摘要】

- **编号 / 年份 / 作者**：arXiv `2609.33153v2`，2026-09-27，Shuyang Zhang。`comment`：50 pages；critical narrative review；扩展了文献覆盖与 study-level 证据表。
- **它主张什么（摘要原话要点）**：**关于工具与可复用 skill 的报告出来的"提升"，指的是不同的比较。** 这篇批评性叙述综述检查了**被引的 100 篇论文的角色**，并**对 35 项研究详细提取了其焦点评估设计**；另对 35 项额外研究做了定向阅读。设计按 **treatment contrast、target population、outcome、budget constraint、summary measure、identification assumptions** 六个方面刻画。
- **最关键的方法论结论（摘要原话要点）**：**"配对运行本身并不能识别一个调用效应，当评估在被处理run 内部以触发为条件时"**（"pairing runs on the same task does not itself identify an invocation effect when evaluation conditions on a trigger within the treated run"）；**配对增益与回退计数描述的是耦合协议下的不一致性，而不是"期望结果变差的任务占比"**；**部署一个模块的总效应，与"在共同预算下的效率"，回答的是不同问题**。跨研究比较必须区分 **curated skill provision 与 retriever replacement**、**任务总体与触发子集**、**准备成本与边际使用成本**。它给出一个**报告检查表**。
- **需否训练**：N/A（方法论综述）。
- **能否用于本项目**：**能，而且它是本文件 §4 的主要弹药。** 我们要回答"自己动手比问更好吗"，就必须先说清我们在估计什么：**是部署这个能力后的总效应，还是同等预算下的效率？** 这两个问题的答案可能相反，而这篇文章说明多数论文把两者混着报。

#### D5-5 / D5-6 【仅核书目】

- `2507.21378v1`，2025-07-28，Kevin Pu, Ting Zhang, Naveen Sendhilnathan 等：**ProMemAssist: Exploring Timely Proactive Assistance Through Working Memory Modeling in Multi-Modal Wearable Devices**。`comment`：**Accepted to UIST'25**。
- `2005.01322v1`，2020-05-04，O. Miksik, I. Munasinghe, J. Asensio-Cubero：**Building Proactive Voice Assistants: When and How (not) to Interact**。`comment`：17 pages, technical report。
- **我核实到什么**：只有书目。两者都属"**何时**主动开口"一类，**本应归 08a/08c 分区**。列在这里只是为了标注方向 5 的检索边界：主动协助的**时机**有较多工作，但主动协助的**自主执行**（做完再报）几乎没有可比的量化评估。**内容未读，不做断言。**

---

## §2 汇总表

「免训练?」列只看方法本身是否需要更新模型权重。**「适配度 1–5」是我的判断（本文推断），不是论文指标**；评的是"能否直接用于一个不训练模型、动作可分档、动作可撤销的 Windows 桌面 harness"。

| 方法（机制核心） | 代表文献 | 输入要求 | 免训练? | 适配度 |
|---|---|---|---|---|
| 被动观察 → 发现可编程重复模式 → 排序（频率 × 复发可能性）→ **先确认设计再生成程序** → 运行要通知 | D1-1 Motif `2607.10531v1` | 浏览器活动流水；LLM（<3K token/次；可用本地小模型） | ✅ | **5** |
| 低层事件 grounding 成语义动作 → 拆分交织任务 → 每个任务给（层级目标 + 过程控制流） | D1-2 TMI `2608.20319v1` | **截图 + 键鼠事件** + LLM | ✅（但重） | **3**（输入不匹配） |
| 把演示从 flat log 重组为**带标签的层级子目标** | D1-3 `2606.20978v1` | 已有动作日志（无需新数据） | ✅ | **5**（最便宜） |
| 从用户演示生成可复用 agent 工作流 | D1-4 ALLOY `2510.10049v1` | 未读 | 未评估 | — |
| 用 bilevel 优化 + textual gradients 归纳工作流 | D1-5 FlowBot `2604.26258v3` | 未读 | **可能冲突**（未核实） | — |
| 从被动人类演示恢复工作流步骤 + GUI grounding + 自监控 | D2-1 ECLAIR `2405.03710v1` | 视频/演示 + SOP + 多模态 FM | ✅ | **4** |
| **先聚类出"同一个 routine 的多次执行"，再谈自动化**（三步：抽多重集 → 编码 → 聚类） | D2-2 `2510.08118v2` | UI log（含噪声） | ✅ | **5**（骨架可直搬） |
| process mining 在 RPA 中的系统性综述 | D2-3 `2204.00751v2` | — | — | 入口 |
| 从**未分段** UI log 里找候选 routine | D2-4 `2008.05782v2` | UI log | ✅ | 4（相关） |
| 过程发现 → 结构化程序合成 | D2-5 `2008.05804v1` | 过程日志 | ✅ | 未评估 |
| robotic process mining 的愿景与挑战（定义来源） | D2-6 Leno 等 2020, BISE, `10.1007/s12599-020-00641-4` | — | — | 入口 |
| process/task mining 与 RPA 的 Pareto 原则 | D2-7 van der Aalst 2020, `10.5220/0009979200050012` | — | — | 入口 |
| **bash 作唯一动作接口 + 文件系统当可演化工具空间**（~3K 行 harness） | D3-1 CUAWright `2610.04116v1` | 已有 shell/文件能力 | ✅ | **5** |
| 技能库（描述 embedding 检索）+ 自验证通过才 commit + 组合复用 | D3-2 Voyager `2305.16291v2` | LLM + 可执行环境 + **客观成功判据** | ✅ | **4** |
| schema-grounded 联合优化造工具与用工具 + tool pool（准入/容量/淘汰/检索） | D3-3 SMITH `2608.24571v1` | 需 RL / LoRA / judge | ❌ | **2**（只抄 tool pool） |
| code-as-policy / 自造工具 / 记忆驱动演化（Android GUI agent 自生成工具动作） | D3-4/5/6 | 未读 | 未评估 | — |
| **typed 动作本体 + 状态投影 → 逆搜索 → 分级可逆性分数 → 低于阈值执行前剪掉** | D4-1 POLAR `2610.08082v1` | 每个动作类型的逆 + 会话状态 | ✅ | **5** |
| **三档监督（HITL / over-the-loop / automated-with-monitoring）+ 确定性 OCM 按四输入分派 + 每档规定证据物** | D4-2 GAIE `2606.22484v2` | 四个可枚举输入 | ✅ | **5** |
| 不可能性定理：helpfulness / calibration / autonomy 三者不可同时最大 | D4-3 三难 `2605.25739v2` | —（理论） | N/A | **5（约束）** |
| **审批卡从 ground-truth 动作重建 + 带外渲染 + 默认拒绝 + 批准绑定到 dispatch 时的动作** | D4-4 VAC `2609.18411v2` | 待执行动作的可信描述 | ✅ | **4** |
| **验证等级 VAL（L0 模型自述 → L2 客观 ground truth → L5 不可能）** 给防御分级 + 验收语言 | D4-5 VAL `2610.04504v1` | —（分类法） | ✅ | **4** |
| agent 自选历史 tool result 替换为短 note，原文进**可恢复归档**（可显式 recovery） | D4-6 `2610.10590v1` | harness 层归档 + 恢复接口 | ✅ | **3**（次要） |
| **把"提问"做成可排序的可选动作** + mandatory/opportunistic 两模式 + ISE 指标 + 答案质量退化对照 | D5-1 `2606.11349v2` | 动作空间 + 受控答案通道 | ✅ | **4** |
| 用户按任务校准信任；**不可逆 + 对外可见**驱动信任撤出；**无预览即执行→delegation regret** | D5-2 `2607.18257v2` | 20 人用户研究 | N/A | **5（变量选择）** |
| 工具/skill 评估有效性的批评性综述（estimand 与主张对不齐） | D5-4 `2609.33153v2` | — | N/A | **5（方法论）** |
| 及时主动协助（可穿戴，工作记忆建模） | D5-5 `2507.21378v1` | 未读 | 未评估 | — |
| 主动语音助手：何时、如何（不）交互 | D5-6 `2005.01322v1` | 未读 | 未评估 | — |

**⚠️ 本表读法**：适配度 5 的条目里，**只有 D2-2、D3-1、D4-1、D4-2 是"机制级可搬"**；D1-3 是"格式级可搬"；D4-3、D5-2、D5-4 是"约束/变量级可搬"（它们不提供机制，只告诉你别怎么设计）。**没有任何一行的适配度是"直接上手"**——都需要落地到 Windows 桌面语境重新验证。

---

## §3 最该抄的 3 条

以下三条是我读完这批文献后**建议优先搬进工程**的机制，都具体到落点。三条互不重叠：第 1 条管**要不要动手**，第 2 条管**分档怎么裁**，第 3 条管**发现问题之后怎么把它变成可复用动作**。

### 抄第 1 条 · POLAR 的"执行前逆序列打分"——把可撤销从"事后能撤"提前到"事前能判"

**抄什么（机制，来自 D4-1）**：给每个动作类型定义它的**逆**，对候选动作做**逆搜索**导出**候选逆序列 π**，据此算出**分级的可逆性分数**，**分数低于阈值的调用在执行前被剪掉**。判定必须是**结构化、可审计**的，而不是一句 allow/block。

**为什么是我们（本文推断）**：我们现在的可撤销性是"**事后**"的。`desktop_*` 工具先写撤回日志再动手，气泡带"撤销"（`AGENTS.md:37,56`）。这套东西回答的是"做完之后能不能撤回去"，**回答不了"这件事到底该不该由我做"**。POLAR 补的正是这一环：**在动手之前，用一个结构化判定说清"这个动作的逆存在吗、撤回去的代价是什么"**。

**具体怎么落（本文推断）**：
1. **Layer A（动作本体，静态）**：在 `vista/benchmarks/desktop/actions.py` 的动作定义上增加两个字段——
   - `inverse_kind` ∈ {`reversible`（有精确逆：改名、移动可还原）, `compensable`（无精确逆但有可接受的补偿：删除到回收站可还原, 覆盖文件需备份才能还原）, `irreversible`（发邮件、提交表单、对外发布）}；
   - `external_visibility` ∈ {`local`, `outward`}（是否在用户之外留下痕迹）。
   注意：`actions.py` 现在已有"前台/系统/安全进程拒绝"的硬拒绝名单，`inverse_kind`/`external_visibility` 是**在硬拒绝之外**的连续分级，两者不冲突。
2. **Layer B（状态投影，动态）**：动手指前先查当前会话状态——目标进程是否仍在、目标文件是否有备份或是否进了回收站、相关窗口是否还开着。**逆序列存在与否依赖状态**，这正是 POLAR 分两层的理由。
3. **裁决**：`irreversible` 或 `outward` → 直接进"必须先问"档（呼应 D4-4 的 default-deny）；`compensable` → 进"做完汇报"档，且**必须先把撤回日志写成功**（写不成功就不许动手）；`reversible` 且 `local` → 可以进"默默做"档。
4. **必须一并抄它的负面结果**：POLAR 在 18 个 model–domain cell 里只有 8 个为正，retail 与更强的模型常常回退，作者明说 **reward 不是防止伤害的直接度量**。所以这条落地后**必须自己测**，不能假定有效。

### 抄第 2 条 · GAIE 的"确定性分档函数 + 每档证据物"——分档不能由模型自报置信度裁定

**抄什么（机制，来自 D4-2）**：一个**确定性的决策函数**按**有限个可枚举输入**把动作分派到少数几档；**每一档规定必须留下的证据物**。不要发明中间地带，档位就是 3 档。

**为什么是我们（本文推断，理由来自 D4-3）**：D4-3 的三难说明，只要"模型自报置信度"和"按该置信度放行"同时存在、且自主有收益，分数就会**系统性偏向动手**（Brier 下膨胀按 **w_A/(2w_C)** 缩放，检测需要 **Ω(1/Δ²)** 次观测——即你几乎不可能在合理时间内发现它在偏）。我们**不训练模型**，所以这个不可能性不直接作用在我们身上；**但它的对立面成立**：只要我们让模型给自己打分并据以放行，**我们就落进 autonomous-sycophant 角**。
D5-2 独立印证了输入变量的选择：驱动用户信任撤出的**不是 stakes，而是"不可逆 + 对外可见"**（中等风险的邮件任务信任掉得最狠 M=3.10、审批要求最高 M=4.65，而高风险但可核验的任务没有同样反应）。

**具体怎么落（本文推断）**：
1. **分档输入（4 个，全部可枚举、不由模型自由裁量）**：
   - `reversibility`（来自第 1 条的三值）
   - `external_visibility`（`local` / `outward`）
   - `blast_radius`（影响范围：单个文件 / 一批文件 / 系统级）
   - `has_preview`（这个动作能不能在执行前给用户看一个可核验的预览）
2. **分派函数（确定性代码，不是提示词）**：
   - 全 `reversible` + `local` + 单文件 + 可预览 → **档 1 默默做**（写完撤回日志即可）；
   - 含 `compensable` 或 `blast_radius` 较大 → **档 2 做完汇报**（动手后必须发一条"我做了什么 + 撤销入口"）；
   - 出现 `irreversible` 或 `outward`，**或** `has_preview = false` → **档 3 必须先问**。
   注意 `has_preview = false` 单独就能升到档 3——依据是 D5-2：**没有预览就执行，即使结果成功也产生 delegation regret。**
3. **每档的证据物（直接照搬 GAIE 的"required evidence artifacts"）**：档 1 至少留**撤回日志 + 一条事后可查的审计记录**；档 2 留**"我做了什么"的可回溯记录**（可以复用现有 `offer.json`/`offers.jsonl` 的形态）；档 3 留**用户看到的那份预览内容**（依据 D4-4：审批要绑定到**实际将要执行的动作**，所以预览必须由真实动作重建，不能是模型对它的描述）。
4. **给这套分档加上验收语言（来自 D4-5）**：我们要能说出每一条放行的依据是 **L0**（模型说没事）/ **L1**（确定性规则判的）/ **L2**（客观事实核出来的）。说不出等级，"失败率 0"就没有信息量。
5. **备选参照（D3-3 的 tool pool 四项规格）**：如果以后让 agent 自己攒脚本，准入标准 / 容量上限 / 淘汰策略 / 检索与干扰项这四件事**免训练也需要**，SMITH 只是把它和 RL 绑在一起了。

### 抄第 3 条 · Motif 的"两段式确认" + Voyager 的"验证过才进库"——把发现变成可复用动作

**抄什么（机制，来自 D1-1 与 D3-2）**：
- **Motif**：排序分数 = **频率 × 未来发生可能性**（不是只按频率，因为用户只看前几条）；流程是**发现 → 推荐 → 用户确认 `program design` → 才生成程序**；**任何自动化一旦发生就要通知用户**；监控可随时暂停、可加黑名单。
- **Voyager**：**只有 self-verification 确认任务完成的程序才 commit 进 skill library**；程序**用描述的 embedding 索引**、相似情境检索；复杂技能由简单程序**组合**而成（消融显示 self-verification 最重要：去掉它发现物品数 **−73%**；去掉 skill library 后期平台化）。
- **CUAWright（D3-1）给容器**：不要固定工具清单。**bash 是唯一动作接口，文件系统是可演化的工具空间**（OSWorld 2.0 partial reward 相对 +33.2%、成本 −37.5%）。

**为什么是我们（本文推断）**：我们的 `companion` 每轮三选一，**发现和行动之间没有"可复用"这一层**——每次发现问题都要重新从零想一遍怎么做。Motif 给了**触发到程序的拓扑**，Voyager 给了**程序入库的门槛**，CUAWright 给了**存放与执行的容器**。三者拼起来正好是一条完整链路：发现 → 确认设计 → 生成脚本 → 验证成功 → 入库 → 下次直接检索复用。

**具体怎么落（本文推断）**：
1. **发现的排序**：从 `events.jsonl` 里找重复序列时，排序用**频率 × 复发可能性**（Motif 的 LLM 打分），不要只按次数——否则每天点一次的固定动作会一直排在前面。
2. **两段式**：先给用户看**"我打算把这件事变成什么"（program design）**，确认之后再生成代码。Motif 明确把这两步分开；这正好对应我们现有 `offer` 的确认语义，只是确认的对象从"要不要我做"变成"要不要把它做成一个固定的做法"。
3. **入库门槛**：脚本**只有被验证跑成功才登记成技能**，登记时存**它的自然语言描述 + embedding**，下次按描述检索。Voyager 的消融说明这一步不能省。
4. **容器**：技能存在一个**约定目录**里（CUAWright 的做法），用 bash 直接跑——我们已有这个能力，不需要新建基础设施。
5. **必须一并抄的两个"通知与边界"义务**：
   - Motif：**"any automation occurs 就要通知用户"** ——当自动化的执行不再有交互时，"通知"是唯一的可见性来源；
   - Motif 的自述残余风险：PII 抽取有限、可被用于行为画像/监控、prompt injection、**生成脚本可能恶意或有 bug**、本地被入侵，真部署还需**审计日志 + 更紧的 grant sandboxing**。
6. **与"可撤销"的张力必须正面处理**：让 agent 写脚本并执行，撤回的对象是**脚本**还是**它的副作用**？这是第 1 条（逆序列打分）与第 3 条（自造工具）的接缝，也是本文件**§4 第 6 条**要说的问题。

---

## §4 这份调研证明不了什么

这一节是本文件最重要的部分。**如果你只读一节，读这一节。**

### 1. 本调研**没有**回答标题问题：没有任何 benchmark 度量过"自己动手 vs 问用户"

我把最接近的两条都读完了：
- **D5-1** 是把"问"做成可选动作、并做了答案质量退化对照，但它比较的是 **"问 vs 不问"**，不是 **"动手 vs 问"**；它的 67.0% vs 50.8% 是**它自己的 HTS 层次分类任务**上的数字，**不能迁移**成"我们的场景里自己动手更好"。
- **D5-2** 度量的是用户的信任与审批意愿，**它没有对照组，也没有让 agent 真的自己动手再测结果**；它是 20 名学生的 5 点量表研究。

因此**正确的说法是**：本调研给了备选机制和一组设计约束，**没有给出"哪个更好"的证据**。要回答那个问题，我们必须**自己做对照实验**。而 **D5-4** 正好告诉我们这个实验有多容易做错：配对运行本身**不能**识别"调用效应"（当评估在被处理 run 内部以触发为条件时）；配对增益/回退计数描述的是**耦合协议下的不一致性**，**不是**"期望结果变差的任务占比"；**部署总效应**与**同预算效率**是两个不同问题，可能给出相反答案。

### 2. POLAR 的效果不支持"可逆性打分普遍有用"

18 个 model–domain cell 里**只有 8 个提升**；retail 与**更强的 agent 常常回退**；作者自己写明 **"Reward is not a direct measure of prevented harm."** 把它从 τ²-bench 的 airline/retail 工具调用搬到 Windows 桌面动作，属于**外推**，而且是在一个**作者自己都报告了混合结果**的方法上外推。

### 3. ECLAIR 的 40% 是我们能拿到的"能不能自己做完"最诚实的数字，但它不适用于我们

- 40% 是**仅凭自然语言描述**的端到端完成率，场景是 **WebArena 抽出的 30 个工作流**（Gitlab / Adobe Magento），模型是 **2024 年的 GPT-4**，环境**不是 Windows**，事件格式**不是我们的 `{ts,type,app,title,dur_s,path?}`**。
- **不要把 93% / 0.94 / 0.95 和 40% 混着引用**：前三个是**步骤理解**指标（工作流理解、步骤识别的 precision/recall），40% 才是**执行完成**指标。两者不是同一个量。
- 作者把 human-AI collaboration、validation、self-improvement 明确列为**未解决的开放挑战**——这不是"已解决，可以抄"，而是"已知难点"。

### 4. 没有任何一条给出 Windows 桌面动作的风险分级清单，"本体"必须我们自己写

- **D4-1（POLAR）** 的 Layer A 是 **per-domain、静态**的动作本体——它的域是 airline/retail 工具调用。
- **D4-2（GAIE）** 的四输入是**监管语境**（regulatory impact / customer proximity / data sensitivity），不是桌面语境。
- **D4-3（三难）** 是 RL 理论。
- 所以：**"哪些 Windows 动作算 reversible / compensable / irreversible"这张表，本文件里没有任何一篇提供**。而且写本体是**主观的**——POLAR 附录 C.5 专门有一张 "ontology authoring decision table"，说明连作者自己都需要一张表来约束本体的写法。我们写自己的本体时，同样需要用一张显式规则表来约束，并且**必须接受它是主观约定而不是从文献推导出来的结论**。

### 5. TMI 的数字不能迁移到我们的输入上

**0.974 分组一致性 / 74.9% 步骤重建 / +30.0% held-out 准确率**，全部是在**包含截图与键鼠事件**的多模态 trace 上取得的（作者还强调"活动只以低层事件被观察到"是核心困难之一）。我们只有 `{ts, type, app, title, dur_s, path?}`。
**它证明的是**"低层事件能恢复出结构化任务模型"这个方向可行；**它没有证明**"只靠我们这个字段集能做到"。**任务边界怎么切**（尤其是**多个任务交织**时，这正是 TMI 标题里的 "interleaved"）在我们的输入上是一个**未解问题**。D2-4 的标题（**unsegmented** UI logs）说明连 RPA 这条更成熟的线，也把"先分段"当成需要专门论文解决的难点。

### 6. "自造工具"与"所有动作可撤回"之间存在未被任何文献解决的张力

- **D3-1（CUAWright）** 的核心主张就是让 agent 用 **bash + 文件系统**自由创建工具并执行，且它在真实数字任务上更好、更便宜。
- 但我们的硬约束是"**所有动作可撤回**"。让 agent 写一个脚本再跑，**撤回的对象是什么？** 脚本文件本身（好撤），还是脚本执行后产生的副作用（往往是 `irreversible`）？**本文件里没有任何一篇回答这个问题。**
- 相关地，**D4-6** 承认 reversibility 在**上下文/工件层面**的边界：它省了一半 token，但**同一次续跑出现了"上下文更少、人工评估质量更低"**，且效果**依赖工作负载**（无关任务零节省）。这是很好的示范：**"可恢复"不等于"变好"。**

### 7. 我核实不到的东西，以及它们对结论的影响

- **POLAR 与 Voyager 正文引用的经典**（HCI undo、数据库事务与补偿、idempotency / retry 语义等）我**没有独立核实书目**，本文件**没有出现它们的编号**。这意味着：**"可撤销性的形式化"这个子方向的学术源头在本文中是空的**——我做的是**从 2026 年的工程论文倒推机制**，不是沿着理论主线梳理。若要做正式选型，这一块需要补检索。
- **方向 2 的两条源头**（D2-6 Leno 等 2020 BISE、D2-7 van der Aalst 2020）**只核到 Crossref 书目，正文未读**；D2-3 的 51 页综述也**只核到书目**。
- **方向 1 的 D1-4、D1-5；方向 3 的 D3-4/5/6；方向 5 的 D5-5/6** 全部**只核到书目**，内容未读。**表里标"未评估"的行就是这些**，不要把它们当作已评估。
- **2026 年这批论文的同行评审状态多数未核实**。只有 `comment` 字段自己写明会议的（D1-3 DL4C@ICML 2026、D2-4 ICPM 2020、D4-1 AACL-IJCNLP 2026 Findings、D5-2 VL/HCC 2026、D5-5 UIST'25）我才标注了发表场合。**其余按预印本对待。**

### 8. "成熟方法"这个前提在方向 1/3/4/5 上不成立

- **方向 2 之外**，我读到的最好的机制全部是 **2026 年**的预印本：D1-1 Motif（2026-07）、D1-2 TMI（2026-08）、D3-1 CUAWright（2026-10）、D4-1 POLAR（2026-10）、D4-2 GAIE（2026-06）、D4-4 VAC（2026-09）、D4-5 VAL（2026-10）、D5-1（2026-06）。**Voyager 是 2023 年的**，是本批唯一有几年时间的非方向 2 工作。
- 真正"成熟"（十年以上、有共识术语与评测传统）的只有**方向 2**：process mining / robotic process mining / task mining。
- **所以本次检索的正确用法是**：把方向 2 当**方法学来源**（怎么从噪声日志里聚类出 routine、怎么定义分段），把方向 3/4 当**2026 年的前沿实践**（可抄机制，但要自己验证），**方向 1 当格式规范**（D1-3 层级演示格式几乎零成本），**方向 5 当反面清单**（告诉你别把什么当证据）。

### 9. 检索本身的偏差（元层面）

- "发现问题后自己动手解决"在文献里**没有统一术语**。我试过的词包括 proactive repair、automated remediation、self-healing、plan repair、undo、reversibility、tool creation、workflow induction、PBD、RPA mining。**我使用的中文表述可能对应到完全不同的英文子领域**，而本次只用 arXiv API + Crossref 的关键词检索。
- **我没有检索到任何以"发现问题后的自主修复"为题的系统性综述**。因此本文件的 5 个方向分类是**我按机制拼出来的，不是文献里已有的分类**——这也意味着**可能存在我完全没覆盖到的相关工作**。
- 我**没有**检索非英文文献、专利、工业界技术报告（除 D2-1 的案例研究外），也**没有**做引文回溯（backward/forward citation chaining）。要判断"是否成熟"，引文回溯是必要的下一步。

---

## §5 参考文献

**按编号排序**。标注含义见 §0.1。**"适配度"不在本节重复**（见 §2），本节只给可核实字段。

### arXiv（编号、日期、作者、发表备注均取自 arXiv 官方 API / HTML）

1. **`2607.10531v1`** — *Motif: Discovering and Automating Personal Web Workflows* — 2026-07-12 — Shaokang Jiang, Daye Nam 等 — **【已读原文】**
2. **`2608.20319v1`** — *Inducing Task Models from Computer-Use Traces* — 2026-08-20 — Yucheng Jiang, Zora Zhiruo Wang, Ruishi Chen 等 — 代码 `https://github.com/Yucheng-Jiang/task-model-induction` — **【已读原文】**
3. **`2606.20978v1`** — *How Should Agents Read Demonstrations? Hierarchical Structure Beats Flat Action Logs* — 2026-06-18 — Honjar Xing, Jefferson Lin, Henry Lieberman (MIT CSAIL) — comment: Accepted at DL4C Workshop, ICML 2026 — **【已读原文】**
4. **`2510.10049v1`** — *ALLOY: Generating Reusable Agent Workflows from User Demonstration* — 2025-10-11 — Jiawen Li, Zheng Ning, Yuan Tian 等 — **【仅核书目】**
5. **`2604.26258v3`** — *FlowBot: Inducing LLM Workflows with Bilevel Optimization and Textual Gradients* — 2026-04-29 — Hongyeon Yu, Young-Bum Kim, Yoon Kim 等 — **【仅核书目】**
6. **`2607.00597v2`** — *Multi-Turn Agentic Scientific Literature Search via Workflow Induction* — 2026-07-01 — Jisen Li, Bingxuan Li, Nanyi Jiang 等 — comment: 17 pages, 12 figures — **【仅核书目】**
7. **`2405.03710v1`** — *Automating the Enterprise with Foundation Models* (ECLAIR) — 2024-05-03 — Michael Wornow\*, Avanika Narayan\*, Krista Opsahl-Ong, Quinn McIntyre, Nigam H. Shah, Christopher Ré (Stanford) — 代码 `https://github.com/HazyResearch/eclair-agents` — **发表状态未核实** — **【已读原文】**
8. **`2510.08118v2`** — *Accurate and Noise-Tolerant Extraction of Routine Logs in Robotic Process Automation (Extended Version)* — 2025-10-11 — Massimiliano de Leoni, Faizan Ahmed Khan (Univ. of Padua), Simone Agostinelli (Universitas Mercatorum) — comment: 16 pages, 5 figures — **【已读原文】**
9. **`2204.00751v2`** — *Robotic Process Automation Using Process Mining – A Systematic Literature Review* — 2022-04-02 — Najah Mary El-Gharib, Daniel Amyot — comment: 51 pages, 5 figures, 7 tables — **【仅核书目】**
10. **`2008.05782v2`** — *Identifying candidate routines for Robotic Process Automation from unsegmented UI logs* — 2020-08-13 — V. Leno, A. Augusto, M. Dumas 等 — comment: **International Conference on Process Mining 2020** — **【仅核书目】**
11. **`2008.05804v1`** — *Process Discovery for Structured Program Synthesis* — 2020-08-13 — Dell Zhang, Alexander Kuhnle, Julian Richardson — **【仅核书目】**
12. **`2610.04116v1`** — *CUAWright: A Minimal Unified Interface for Digital Agents* — 2026-10-02 — Yadong Lu, Theodore Lee, Yifei Li 等（8 位作者） — comment: 20 pages, 10 figures — **【已读原文】**
13. **`2305.16291v2`** — *Voyager: An Open-Ended Embodied Agent with Large Language Models* — 2023-05-25（v2 2023-10-19） — Guanzhi Wang, Yuqi Xie, Yunfan Jiang, Ajay Mandlekar, Chaowei Xiao, Yuke Zhu, Linxi "Jim" Fan, Anima Anandkumar — 项目页 `https://voyager.minedojo.org` — **【已读原文】**
14. **`2608.24571v1`** — *Joint Optimization of Tool Creation and Use for Large Language Model Agents* (SMITH) — 2026-08-25 — Zhi Rui Tam, Chieh-Yen Lin, Yun-Nung Chen — **【已读原文】**
15. **`2609.39018v1`** — *Make Code as Policy Great Again: Frontier Agents Write, Call, and Evolve Robot Tools* — 2026-09-30 — Shijia Ge, Alex Zhou, Jianshu Zeng 等 — **【仅核书目】**
16. **`2607.22832v1`** — *MEMENTO: Memory-Guided Memetic Code-as-Policy Evolution* — 2026-07-24 — Alkis Sygkounas, Victor Aregbede, Amy Loutfi 等 — **【仅核书目】**
17. **`2609.06792v1`** — *Improving Proficiency and Efficiency of Android GUI Agents via Self-Generating Tool Actions* — 2026-09-06 — Juyong Lee, Woogyeol Jin, Kimin Lee — **【仅核书目】**
18. **`2610.08082v1`** — *POLAR: Ontology-Guided Risk Prevention for Tool-Calling LLM Agents* — 2026-10-06 — Yunju Kang, Seonghyeon Cho (Soongsil Univ.), Irene Li (Univ. of Tokyo), Yeo-Chan Yoon (Jeju National Univ.), Chanjun Park (Soongsil Univ.) — comment: **Accepted Findings of AACL-IJCNLP 2026** — **【已读原文】**
19. **`2606.22484v2`** — *Governed AI-Assisted Engineering: Graduated Human Oversight for Agentic Code Generation in Regulated Domains* (GAIE) — 2026-06-21 — Richard Kang — **发表状态未核实** — **【已读摘要】**
20. **`2605.25739v2`** — *The Behavioral Credibility Trilemma: When Calibrated Autonomy Becomes Impossible* — 2026-05-25 — Lauri Lovén, Nam Do, Hassan Mehmood (Univ. of Oulu), Sasu Tarkoma (Univ. of Helsinki) 等 — comment: 49 pages, 3 figures, 5 tables — **【已读原文】**
21. **`2609.18411v2`** — *The Verifiable Action Card: Trustworthy Human-in-the-Loop Control for Secure Autonomous Agents* (VAC) — 2026-09-16（v2） — Hasnain Irshad, Anam Mughees, Neelam Mughees, Abdullah Mughees, Imtiaz Ali Soomro — comment: 18 pages — **【已读摘要】**
22. **`2610.04504v1`** — *The Same Zero: Why Identical ASR Can Imply Different Guarantees in LLM-Agent Security*（应用 Verification Autonomy Levels, VAL） — 2026-10-03 — YaJie Yin — **【已读摘要】**
23. **`2610.10590v1`** — *Agent-Controlled Forgetting for Tool-Using Agents: Reversible Context Curation in Practice* — 2026-10-06 — Jan-Peter Franke — comment: 13 pages, 1 figure，代码 `https://github.com/boldprojekte/agent-forgetting-research` — **【已读摘要】**
24. **`2606.11349v2`** — *Knowing When to Ask: Self-Gated Clarification for Hierarchical Language Agents*（提出 `ActionRating`） — 2026-06-09 — Aijing Gao, Yiming Kang, Mengdie Flora Wang 等 — **发表状态未核实** — **【已读原文】**
25. **`2607.18257v2`** — *Assistant or Actor? Student Trust, Control, and Delegation Regret When Using a General-Purpose AI Agent* — 2026-05-14（v2 2026-10-02） — Shiva Pochampally, Shengwei An, Yan Chen 等 — comment: **Presented at the 2026 IEEE Symposium on Visual Languages and Human-Centric Computing (VL/HCC)** — **【已读摘要】**
26. **`2609.33153v2`** — *What Does a Skill Actually Do? Estimands and Evaluation Validity for Tool and Skill Use in LLM Agents: A Critical Review* — 2026-09-27 — Shuyang Zhang — comment: 50 pages, critical narrative review — **【已读摘要】**
27. **`2507.21378v1`** — *ProMemAssist: Exploring Timely Proactive Assistance Through Working Memory Modeling in Multi-Modal Wearable Devices* — 2025-07-28 — Kevin Pu, Ting Zhang, Naveen Sendhilnathan 等 — comment: **Accepted to UIST'25** — **【仅核书目】**
28. **`2005.01322v1`** — *Building Proactive Voice Assistants: When and How (not) to Interact* — 2020-05-04 — O. Miksik, I. Munasinghe, J. Asensio-Cubero — comment: 17 pages, technical report — **【仅核书目】**

### Crossref 核实（非 arXiv 传统文献；只核到书目，正文未读）

29. Leno, Polyvyanyy, Dumas, La Rosa, Maggi — *Robotic Process Mining: Vision and Challenges* — **2020** — *Business & Information Systems Engineering* — **DOI 10.1007/s12599-020-00641-4** — type: journal-article — **【仅核书目，Crossref】**
30. van der Aalst — *On the Pareto Principle in Process Mining, Task Mining, and Robotic Process Automation* — **2020** — *Proceedings of the 9th International Conference on Data Science, Technology and Applications* — **DOI 10.5220/0009979200050012** — type: proceedings-article — **【仅核书目，Crossref】**

### 明确不列入的

- **POLAR 与 Voyager 正文引用的 HCI undo / 数据库事务与补偿 / idempotency 等经典**：**书目未核实，故不给编号**（见 §4 第 7 条）。
- 任何我在**其它分区**（08a 中断与打扰、08b 在线算法、08c 主动性框架）见过的文献：**不在本文件重复**，需要时见对应文件。

---

*文件结束。本文件为只读调研产物；未修改 `E:\OpenLookout` 下任何其它文件，未启停任何进程，未调用任何 `desktop_*` 工具，未写入 `sprite_home\`。所有临时抓取文件位于 `E:\OpenLookout\tmp_lit9b\` 并在完成时删除。*
