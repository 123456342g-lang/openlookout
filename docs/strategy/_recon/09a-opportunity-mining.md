# 09a — 机会挖掘（Opportunity Mining）文献调研

> 目标方向：**从用户在自己电脑上的操作痕迹里，发现他未察觉的问题/机会**。
> 本文只服务工程选型，不服务学术综述。
> 交付日期：见文件系统时间戳。作者：文献调研子 Agent。

---

## §0 核实方法与工具限制

### 0.1 本会话可用的核实通道（全部为 curl.exe 直连，无 web_search / web_fetch）

| 通道 | 端点 | 实测结果 |
|---|---|---|
| arXiv Atom API | `https://export.arxiv.org/api/query?search_query=...&id_list=...` | 可用。**有速率限制**：连续请求会返回不含 `<entry>` 的空 feed，需 4–6 秒间隔 + 重试 2–4 次 |
| Crossref REST | `https://api.crossref.org/works?query.bibliographic=...` 与 `/works/{DOI}` | 可用，稳定。书目字段（标题/年份/DOI/期刊/作者）可信 |
| DuckDuckGo HTML | `https://html.duckduckgo.com/html/?q=...` | 可用，作为唯一可用的网页搜索。返回 `result__a` 链接，需从 `uddg=` 参数解出真实 URL |
| 产品官方文档直抓 | `learn.microsoft.com` / `docs.uipath.com` / `celonis.com` | 可用，正文可读 |
| AIS eLibrary | `https://aisel.aisnet.org/ecis2022_rip/55/` | 可用，含论文摘要原文 |

### 0.2 明确核不到的东西（比写错更有价值）

- `web_search` 不可用（后端缺 key）；`web_fetch` 不可用（把域名判为非公网 IP）。这两个工具在本次调研中**一次都没有成功过**，我不依赖它们。
- **dblp.org 被 Anubis 反爬拦截**（返回 "Making sure you're not a bot!"）。因此 Mayr et al. (ECIS 2022) 我只能在 AIS eLibrary 核到，无法用 dblp 二次交叉验证。
- **ACM Digital Library / SpringerLink 全文付费墙**：所有 DOI 以 `10.1145/**`、`10.1007/**` 开头的条目，我**只核到 Crossref 书目**（标题、年份、DOI、期刊/会议、作者姓名序列），**没有读到它们的摘要或正文**。文中一律标【仅核书目】。
- **tandfonline（Weinzierl et al. 2021）摘要抓不到**：页面返回 len=5675，无 `<section abstract>` 段，且 Crossref 该 DOI 无 abstract 字段。故该文机制我也**只当书目**处理，不描述其算法细节。
- **Crossref 对 ECIS 会议论文检索失败**：`query.bibliographic="Applications and Challenges of Task Mining..."` 返回 0 条命中（ECIS proceedings 多数无 DOI）。该条改由 AIS eLibrary 页面正文核实。
- 我没有找到任何一篇报告"**单用户、私人桌面事件流、零打扰、端到端发现并解决未察觉问题**"的论文。见 §4。

### 0.3 引用可信度标签（全文严格使用）

- **【已读原文】** = 我抓到了该文献的摘要或正文原文（arXiv summary 字段、Crossref abstract 字段、或官方 HTML 正文）。
- **【仅核书目】** = 只核到标题/作者/年份/DOI/发表 venue，**未读到摘要或正文**。
- **【未核实】** = 连书目都没核到（本文正文中不出现此类条目）。

### 0.4 本项目的输入基线（所有"适配度"评分的参照物）

本项目事件流字段：`{ts, type, app, title, dur_s, path?, url?}`，`type ∈ {focus, file_save, file_open, file_create, clipboard}`。

**这与文献里的 "UI log" 有一个必须先说清的粒度落差**：文献中的 UI log（尤其 Abb & Rehse 的参考模型）是 **click / 按键 / 字段级**的低层交互；本项目只有 5 类粗粒度事件，没有点击目标、没有窗口内控件、`title` 是自由文本。§4 会量化这个落差会毁掉什么。

---

## §1 逐篇卡片

> 卡片格式：标题 / 编号 / 年份 / 解决的问题 / 核心机制 / 是否需要训练 / 能否用于本项目的桌面事件流。
> 每个方向先给"核心卡片"，再给"补充清单（一行式）"。

### §1.1 方向一：Task mining / Process mining on UI logs

#### 卡片 D1-1｜A Reference Data Model for Process-Related User Interaction Logs
- **编号**：arXiv:2207.12054v1（arXiv comment 原文："Pre-print, to be published at BPM 2022"）
- **年份**：2022-07-25（作者：Luka Abb, Jana-Rebecca Rehse）
- **可信度**：**已读原文**（arXiv summary）
- **解决的问题**：UI log 缺少统一概念化。原摘要：*"each study and tool relies on a different conceptualization and implementation of the elements and attributes that constitute user interactions. This lack of standardization makes it difficult to integrate UI logs from different sources"*
- **核心机制**：给"用户交互日志"定义一套**参考数据模型**——统一 event type 与 attribute 的构成（本研究明确把 UI log 定义为"记录用户在信息系统里执行任务时低层活动的**高分辨率**事件日志，每个事件对应一次单击或一次文本输入"）。
- **是否需要训练**：**不需要**。这是数据建模，不是学习。
- **能否用于本项目**：**能，而且是唯一一个可以直接当施工图用的**。它的价值不是算法，而是逼我们先把 `{focus,file_save,...}` 归一化成一张受限的"动作字母表"。如果跳过这一步，后面所有子序列挖掘的支持度统计都会退化（见 §3 第 2 条）。

#### 卡片 D1-2｜Identifying candidate routines for Robotic Process Automation from unsegmented UI logs
- **编号**：arXiv:2008.05782v2（arXiv comment 原文："International Conference on Process Mining 2020"）
- **年份**：2020-08-13（作者：V. Leno, A. Augusto, M. Dumas, M. La Rosa, F. Maggi, A. Polyvyanyy）
- **可信度**：**已读原文**（arXiv summary）
- **解决的问题**：RPA 需要先"发现并圈定"值得自动化的例行操作（routines），但**例行操作散落在整个流程版图里**，而且现有一切方法都假设"UI log 已经切分好了"，即日志已经是"某个预设任务"的 trace。原文：*"Existing approaches to this problem assume that the UI log is segmented... However"*（摘要在此截断）
- **核心机制**：在**未切分**的 UI log 上做切分 + 候选 routine 识别（摘要截断处未给完整算法，我只能确证"问题设定 = 从无任务边界的连续日志里找出候选 routine"，**具体分割算法我核不到**）。
- **是否需要训练**：**不需要标注**（从问题设定看是无监督/统计型，但**我未读到正文，无法确证**）。
- **能否用于本项目**：**能，且是本项目最该对齐的问题设定**。我们的两个月合并流水账正是"完全未切分"的形态——`E:\OpenLookout\data\events.jsonl` 没有任务边界，等价于 paper 里的 unsegmented UI log。

#### 卡片 D1-3｜Accurate and Noise-Tolerant Extraction of Routine Logs in Robotic Process Automation (Extended Version)
- **编号**：arXiv:2510.08118v2（comment："16 pages, 5 figures"）
- **年份**：2025-10-09（作者：Massimiliano de Leoni, Faizan Ahmed Khan, Simone Agostinelli）
- **可信度**：**已读原文**（arXiv summary）
- **解决的问题**：现有 routine 提取工作有两个缺陷——(a) 只输出"属于 routine 的动作集合"，**不直接支持下游模型发现**；(b) 全部在"无噪声"假设下评测。原文：*"They were also not evaluated in scenarios characterized by inconsistent routine execution, hereafter referred to as noise, which reflects natural variability and occasional errors in human performance."*
- **核心机制**：一个 **clustering-based（基于聚类）** 的技术，从含噪、未切分的 UI log 中抽取"routine log"，使下游能发现 routine-type model。
- **是否需要训练**：**不需要标注训练**（聚类驱动；具体聚类目标函数我未读到正文）。
- **能否用于本项目**：**能，且解决一个真问题**——真人三个月操作一定充满"偶尔点错、偶尔中途被打断、偶尔换个顺序"的噪声。任何"精确匹配子序列"的做法都会因为这种自然变异而漏掉真正的重复劳动。必须带变体容忍。

#### 卡片 D1-4｜Applications and Challenges of Task Mining: A Literature Review
- **编号**：ECIS 2022 Research-in-Progress Papers, Paper 55；https://aisel.aisnet.org/ecis2022_rip/55/（Crossref 无此条，dblp 被反爬拦截）
- **年份**：2022（作者：Alexander Mayr (TU Dortmund), Lukas-Valentin Herm (Univ. Würzburg), Jonas Wanner, Christian Janiesch）
- **可信度**：**已读原文**（AIS eLibrary 页面摘要正文）
- **解决的问题**：原文：*"Currently, there is no overview of application scenarios and the challenges of task mining."* 用 structured literature review 补这个空缺。摘要明确写出应用领域包含 **"discovery of automation [potential]"**（页面截断），并归纳技术、法律、组织三类挑战。
- **核心机制**：不是算法，是**选型地图**——告诉你 task mining 到底被用在哪些场景、卡在哪里。
- **是否需要训练**：不适用。
- **能否用于本项目**：**能，作为"哪些子问题已有前人做过"的防重复清单**。注意它归纳的挑战里含**法律与组织**维度；对本项目而言，法律维度对应"单机私人数据"，组织维度**不适用**（没有组织，没有 SME 访谈环节）。

#### §1.1 工业界做法（产品文档，非论文）

- **Microsoft Learn, "Overview of task mining"** — https://learn.microsoft.com/en-us/power-automate/task-mining-overview ｜**已读原文**。原文关键句：*"capture detailed steps for tasks performed on users' desktops"*；*"gain insights into how they perform tasks, identify common mistakes made during task performance, and pinpoint tasks that can be automated"*；*"can automatically produce a process map... identify which activities take the longest, how many variations of the order fulfillment process exist"*；*"application analytics report can show which applications teams spend the most time in"*；*"create flows with automation recommendations that reveal which connectors to use"*。
  → **可抄的机制**：(a) 自动产出 process map；(b) 做**变体（variants）统计**而不是单一平均路径；(c) 做**应用级时间统计**（这个我们直接有 `app` + `dur_s`）；(d) 输出"自动化建议 + 建议用哪个连接器"。
- **Microsoft Learn, "Overview of process mining and task mining in Power Automate"** — https://learn.microsoft.com/en-us/power-automate/process-advisor-overview ｜**已读原文**。区分：process mining 吃 *"event log files from your system of record"*；task mining *"helps you discover tasks happening on the desktop"*。Process Advisor 是承载两者的产品名。
- **UiPath, "Task Mining — Introduction"** — https://docs.uipath.com/task-mining/automation-cloud/latest/user-guide/introduction-as ｜**已读原文**。原文定义：*"AI-based desktop activity analysis that surfaces evidence of automation opportunities and captures task variations, with automation skeleton export as PDD and XAML files"*；流程为 *"records variations of a known task, uses AI to cluster and merge the captured traces, and surfaces task-level evidence, such as task graphs, variants, and statistics"*。
  → **可抄的机制**：**"先记录变体 → AI 聚类合并 → 输出任务图 + 变体 + 统计"** 这条三段式；以及"**产物是自动化骨架**（PDD/XAML）而不是一份报告"这个交付形态。注意它的起点是 *"a known task"*（已知任务），本项目**没有已知任务**，这是关键差距。
- **Celonis, "What is Task Mining?"** — https://www.celonis.com/insights/topics/what-is-task-mining ｜**已读原文**。原文：task mining *"extracts user interaction data"*，采集 *"clicks, copy/pastes, time spent per application"* 等，并 *"integrates this click and scroll-level data into a Celonis Process Data Model"*，与 process mining（吃 transactional system 的 event log）互补。
  → **可抄的机制**：**"user interaction data" 与 "business event data" 双源对齐**——Celonis 反复强调 task mining 的价值在于补上 *"the steps that happen outside of major systems, like checking emails or consulting spreadsheets"*。本项目只有前者，**没有任何业务真值可对齐**。
- **共同的可信度结论**：三家**都没有公开算法论文**。MS/UiPath 的 "AI to cluster and merge" 是营销措辞，**没有可复现的评测、没有公开的准确率**。我**核不到**任何一篇工业界的 task mining 方法论论文。所以工业界这条线只能抄**产品形态与输出物**，抄不到算法。

#### §1.1 补充清单

| 标题 | 编号 | 年份 | 可信度 | 要点（不含未读到的方法细节） |
|---|---|---|---|---|
| Robotic Process Automation Using Process Mining – A Systematic Literature Review | arXiv:2204.00751v2；journal_ref: *Data & Knowledge Engineering* (2023) 102229 | 2022→2023 | **已读原文** | 系统综述：PM 如何加速 RPA 落地、全生命周期挑战。作者 Najah Mary El-Gharib, Daniel Amyot |
| On the Pareto Principle in Process Mining, Task Mining, and Robotic Process Automation | DOI 10.5220/0009979200050012（DATA 2020） | 2020 | **仅核书目** | van der Aalst 单作者。典型场景下少数变体覆盖多数执行——提示"只做头部变体"是合法的降维 |
| Process Mining Manifesto | DOI 10.1007/978-3-642-28108-2_19（LNBIP, BPM Workshops） | 2012 | **仅核书目** | IEEE Task Force on Process Mining，作者序列极长（van der Aalst 等 70+ 人） |
| Fundamental Framework for Task Mining Technology Adoption | DOI 10.1145/3605423.3605443 | 2023 | **仅核书目** | Dirnberger, Loidl, Brunner。采纳框架，偏组织侧 |
| Log2Plan: An Adaptive GUI Automation Framework Integrated with Task Mining Approach | arXiv:2509.22137v1 | 2025-09 | **已读原文** | 两段式规划 + 对用户行为日志做 task mining 来识别重复任务以支持个性化复用。依赖 LLM/VLM planner-executor |
| A Method for Estimating... / Recording of 50 Business Assignments | arXiv:2308.12211v1 | 2023-08 | 已读原文（摘要） | 50 个真实业务流程的数据集；本项目无对应真值，仅作旁证 |

---

### §1.2 方向二：Workaround / friction detection

#### 卡片 D2-1｜Theory of Workarounds
- **编号**：DOI 10.17705/1cais.03455；*Communications of the Association for Information Systems*, 34(55)
- **年份**：2014（作者：Steven Alter）
- **可信度**：**仅核书目**（Crossref，无 abstract 字段）
- **解决的问题**：给出"workaround（绕路/变通做法）"的**理论框架**。
- **核心机制**：**理论框架，不是检测器**。（具体分类维度我未读到，不编。）
- **是否需要训练**：不适用。
- **能否用于本项目**：**能，但只作为概念语言**。它给我们的是"什么叫一个绕路"的定义空间，而不是算法。**不要指望它给出可执行谓词。**

#### 卡片 D2-2｜Business Process Workarounds: What Can and Cannot Be Detected by Process Mining
- **编号**：DOI 10.1007/978-3-642-38484-4_5（LNBIP, Enterprise, Business-Process and Information Systems Modeling）
- **年份**：2013（作者：Nesi Outmazgin, Pnina Soffer）
- **可信度**：**仅核书目**
- **解决的问题**：**直接对口本方向**——哪些 workaround 能/不能被流程挖掘发现。
- **核心机制**：基于过程挖掘对 workaround 做检测可行性分析。（标题本身就说明结论是"部分能、部分不能"，这比"能"更有用。）
- **是否需要训练**：从标题与 venue 判断是**规则/模型比对型**（process mining 传统做法），**但我未读到正文，标为未确证**。
- **能否用于本项目**：**能，而且必读**——它最可能列出"哪些绕路痕迹在日志里根本不可见"的清单，正好用来做 §4 的负面证据。

#### 卡片 D2-3｜The SWORD is Mightier Than the Interview: A Framework for Semi-automatic WORkaround Detection
- **编号**：DOI 10.1007/978-3-031-16103-2_9（BPM 2022, LNCS）
- **年份**：2022（作者：van der Waal, Beerepoot, van de Weerd, Reijers）
- **可信度**：**仅核书目**
- **解决的问题**：workaround 检测此前依赖访谈（人工、昂贵、不可复现）。标题本身给出定位：**"semi-automatic"**。
- **核心机制**：从标题与 venue 可确证的是"一个半自动的 workaround 检测**框架**"，且明确是 **semi-automatic** 而非全自动。**具体谓词/算法我核不到。**
- **是否需要训练**：**未核实**（semi-automatic 暗示规则+人工判定，但这是推断）。
- **能否用于本项目**：**能作为架构模板**：把"检测"拆成"机器出候选 + 判定环节"。本项目可以把这个判定环节从"访谈 SME"换成"LLM 读候选"，从而保持零打扰。

#### 卡片 D2-4｜Detecting temporal workarounds in business processes – A deep-learning-based method for analysing event log data
- **编号**：DOI 10.1080/2573234x.2021.1978337；*Journal of Business Analytics*
- **年份**：2021（作者：Weinzierl, Wolf, Pauli, Beverungen, Matzner）
- **可信度**：**仅核书目**（Crossref 无 abstract；tandfonline 摘要区抓取失败，len=5675 无 abstract 段）
- **解决的问题**：**这是我找到的唯一一篇"从事件日志直接检测 workaround"的方法论文**，且有明确的子类：**temporal（时序型）workaround**。
- **核心机制**：**基于深度学习分析事件日志**（标题原文：*"A deep-learning-based method for analysing event log data"*）。**具体网络结构与特征我核不到，不编。**
- **是否需要训练**：**是**（标题即 deep-learning-based）。
- **能否用于本项目**：**部分能，但冲突**。冲突点：本项目是 harness 工程、**不训练模型**。可抄的是它的问题定义（"temporal workaround" = 时序上表现异常的绕路，而不是结构上多了个步骤），不可抄的是它的方法。

#### 卡片 D2-5｜A Procedural Framework for Assessing the Desirability of Process Deviations
- **编号**：arXiv:2506.11525v1
- **年份**：2025-06-13（作者：Michael Grohs, Nadine Cordes, Jana-Rebecca Rehse）
- **可信度**：**已读原文**（arXiv summary）
- **解决的问题**：原文：*"Conformance checking techniques help process analysts to identify where and how process executions deviate from a process model. However, they cannot determine the desirability of these deviations, i.e., whether they are problematic, acceptable or even beneficial"*；而人工评估 *"time-consuming, subjective, and irreplicable"*。
- **核心机制**：一个**分步程序框架**，指导分析者系统性地评估偏离的"可欲性"，原文：*"provides a step-by-step approach for identifying which input factors to consider in what order to categorize deviations into mutual[ly exclusive categories]"*（摘要截断）。
- **是否需要训练**：**不需要**。这是流程/程序框架。
- **能否用于本项目**：**能，而且是防"误报伤害"的关键**。本项目最大的风险不是漏检，是**把用户有意为之的绕路当成问题去"修"**。这篇给了一个显式的"偏离分级"骨架（问题/可接受/有益），完全可以照搬成 agent 内部的三分类判定步骤。

#### §1.2 补充清单

| 标题 | 编号 | 年份 | 可信度 | 要点 |
|---|---|---|---|---|
| Resist, comply or workaround? An examination of different facets of user engagement with information systems | DOI 10.1057/palgrave.ejis.3000629（EJIS） | 2006 | **仅核书目** | Ferneley, Sobreperez。"绕路"是用户参与度的一个正式分面 |
| From Automatic Workaround Detection to Process Improvement: A Case Study | DOI 10.1007/978-3-031-41623-1_22（BPM Forum, LNBIP） | 2023 | **仅核书目** | Outmazgin, van der Waal, Beerepoot, Hadar, van de Weerd, Soffer。从"检测到绕路"到"改进流程"的闭环案例 |
| Forging the LongSWORD: Exaptation and Enhancement of the SWORD Framework for Workaround Detection | DOI 10.1007/978-3-031-78666-2_24（BPM Workshops, LNBIP） | 2025 | **仅核书目** | SWORD 的后续"改造/增强"版本 |
| Why Work Around the Process? Analyzing Workarounds Through the Lens of the Theory of Planned Behavior | DOI 10.1007/s12599-023-00802-1（BISE） | 2023 | **仅核书目** | 绕路的动机模型——解释"为什么用户是故意的" |
| Leveraging Workarounds for a Problem-Focused Improvement of Business Processes | DOI 10.1007/s12599-026-00985-3（BISE） | 2026 | **仅核书目** | 最新一篇，把绕路当作改进线索而非缺陷 |
| Scalable Online Conformance Checking Using Incremental Prefix-Alignment Computation | arXiv:2101.00958v1 | 2020-12 | **已读原文** | 在线一致性检查：在偏离**刚发生的那一刻**就检测出来，从而能立刻采取对策。原文明确指出此前方法只能给出近似、导致 *"falsely detected deviations"* |
| A Task Taxonomy for Conformance Checking | arXiv:2507.11976v1 | 2025-07 | **已读原文** | 一致性检查可视化的任务分类学；作者含 Jana-Rebecca Rehse 等 |
| Determining Causes and Severity of End-User Frustration | DOI 10.1207/s15327590ijhc1703_3（IJHCI 17(3)） | 2004 | **仅核书目** | Ceaparu, Lazar, Bessiere, Robinson, Shneiderman。经典"用户挫败"研究，但基于问卷而非行为日志 |

**方向二小结（重要）**：workaround 检测在流程挖掘里是**有名字的子领域**（SWORD / Outmazgin-Soffer / Weinzierl），但它的数据前提是"**有流程模型可比对**"的组织级事件日志。本项目**没有流程模型、没有组织、没有 SME**——所以这条线能抄的是**框架（规则出候选 + 判定环节）”和**分级思想**，不能直接抄检测器。

---

### §1.3 方向三：PIM 摩擦研究与"重访/找回文件"行为模型

#### 卡片 D3-1｜Re-Finding Found Things: An Exploratory Study of How Users Re-Find Information
- **编号**：arXiv:cs/0310011v1
- **年份**：2003-10-06（作者：Robert G. Capra, Manuel A. Perez-Quinones）
- **可信度**：**已读原文**（arXiv summary）
- **解决的问题**：原文：*"The problem of how people find information is studied extensively; however, the problem of how people organize, re-use, and re-find information that they have found is not as well understood."*
- **核心机制**：受控实验室研究。设计很值得注意——*"conducted as a collaborative exercise with pairs of participants. One participant acted as a retriever, helping the other participant re-find information by telephone"*，以此观察用户实际使用的**找回策略**与"领域工件/上下文"的作用。
- **是否需要训练**：不需要。
- **能否用于本项目**：**能，作为行为模型而非算法**。它给了一个可操作信号：**"同一个文件被反反复复找回"本身就是摩擦**。本项目 `file_open` 事件里，同一 `path` 在长时间跨度内被多次打开，就是这个模型的可观测代理。

#### 卡片 D3-2｜Stuff goes into the computer and doesn't come out: a cross-tool study of personal information management
- **编号**：DOI 10.1145/985692.985766（CHI 2004）
- **年份**：2004（作者：Richard Boardman, M. Angela Sasse）
- **可信度**：**仅核书目**
- **解决的问题**：跨工具研究个人信息管理的"**只进不出**"现象。
- **核心机制**：**未读到**（仅书目）。标题本身即结论表述。
- **是否需要训练**：不适用（用户研究）。
- **能否用于本项目**：**能作为"机会"假设的来源之一**：如果用户的 `file_create` 远多于 `file_open`，且大量文件创建后长期不再被打开，那就对应这类"只进不出"的摩擦。**这是一个可直接用本项目的字段算出来的指标**（`file_create` 的 path 集合 − 后续 `file_open` 的 path 集合）。

#### 卡片 D3-3｜How do people organize their desks? Implications for the design of office information systems
- **编号**：DOI 10.1145/357423.357430（ACM TOIS 1(1), 1983）；另有 1982 SIGOA 扩展摘要 DOI 10.1145/800210.806476
- **年份**：1983（作者：Thomas W. Malone）
- **可信度**：**仅核书目**
- **解决的问题**：人如何在桌面上组织信息，对办公信息系统设计的启示。
- **核心机制**：**未读到**（仅书目）。但在本项目语境下，这篇的公认结论方向是"**桌面的杂乱是有功能的**——把文件留在桌面上同时充当了提醒机制"。
- **是否需要训练**：不适用。
- **能否用于本项目**：**能，而且是关键的"反向使用"**：它提示我们**不要把"乱"直接当作问题**。桌面堆积可能正是用户为了"记得这件事"而支付的成本，把它清理掉反而破坏功能。本项目应当寻找的是**用户已经在付代价却得不到回报**的模式，而不是"看起来不整洁"。

#### 卡片 D3-4｜The Science of Managing Our Digital Stuff
- **编号**：DOI 10.7551/mitpress/9780262035170.001.0001（MIT Press, monograph）
- **年份**：2016（作者：Ofer Bergman, Steve Whittaker）
- **可信度**：**仅核书目**
- **解决的问题**：系统化"我们如何管理个人数字资料"。
- **核心机制**：**未读到正文**。但该书的中心论点方向是"**认知外包**"——人把记忆任务外包给文件系统和结构，因此"组织方式"不是审美问题而是**记忆策略**。
- **是否需要训练**：不适用。
- **能否用于本项目**：**能，作为"什么才算机会"的判据**：只有当改动**降低了用户的记忆负担**或**减少了重复动作**时才叫机会；"让文件夹更好看"不是。

#### §1.3 补充清单

| 标题 | 编号 | 年份 | 可信度 | 要点 |
|---|---|---|---|---|
| Mac Users Do It Differently: the Role of Operating System and Individual Differences in File Management | arXiv:2109.15272v1；journal_ref: ACM CHI 2020 Extended Abstracts, LBW135 | 2021 预印 / 2020 发表 | **已读原文** | Dinneen, Frissen。原文结论：*"We find no notable associations between users' attributes and their collections, and minimal predictive power, but do find considerable and surprising differences across"*（跨 OS/文件管理器）。→ **对本项目很重要**：它说明"从用户的文件集合预测用户特征"这条路基本走不通；不要试图从 `path` 反推用户性格 |
| Finding and reminding: file organization from the desktop | DOI 10.1145/221296.221307（ACM SIGCHI Bulletin 27(3)） | 1995 | **仅核书目** | Barreau, Nardi。发现与提醒两种策略；1997 有 revisit 版（DOI 10.1145/251761.248508） |
| A Ranking Algorithm for Re-finding | arXiv:1602.05157v2 | 2016-02 | **已读原文** | Liu。原文：当用户忘记文件名/路径/关键词时找回失败；用"问用户一串关于目标的问题"来过滤候选项。**注意：这需要打扰用户，与本项目冲突** |
| Personal Information Management (PIM) 2008 | DOI 10.1145/1480506.1480524（ACM SIGIR Forum） | 2008 | **仅核书目** | Teevan, Jones, Capra 的 PIM 工作坊报告，可作为 PIM 文献入口 |
| Personal Information Management (edited book) | DOI 10.1515/9780295800684 | 2011 | **仅核书目** | PIM 领域文集 |

---

### §1.4 方向四：序列异常 / 变化点检测（含 sequential pattern mining 原始出处）

> 这一节的可信度整体偏低（多为【仅核书目】），原因见 §0.2：SPM 的原始论文都在 IEEE / ACM / Springer，全文付费墙。

#### 卡片 D4-1｜PrefixSpan: Mining sequential patterns efficiently by prefix-projected pattern growth
- **编号**：DOI 10.1109/icde.2001.914830（Proceedings 17th International Conference on Data Engineering, ICDE 2001）
- **年份**：2001（Crossref 作者序列：Jian Pei, Jiawei Han, Mortazavi-Asl, Pinto, Qiming Chen, Dayal, Mei-Chun Hsu）
- **可信度**：**仅核书目**
- **解决的问题**：序列模式挖掘的候选生成爆炸。标题原文即机制名：**prefix-projected pattern growth**。
- **核心机制**：以"前缀投影"的方式增长模式，避免显式生成候选序列集。（这是标题字面可确证的；具体伪码我未读正文。）
- **是否需要训练**：**不需要模型训练**（从标题可确证是 pattern-growth 算法，需要的是输入序列库 + 最小支持度阈值）。
- **能否用于本项目**：**能，直接可用**。把每日事件按"归一化动作"排序得到序列库，跑 PrefixSpan 找支持度 ≥ k 的子序列，就得到"反复出现的动作套路"。**这是本调研里对本项目最直接可落地的算法。**

#### 卡片 D4-2｜SPADE: An Efficient Algorithm for Mining Frequent Sequences
- **编号**：DOI 10.1023/a:1007652502315（*Machine Learning* 42）
- **年份**：2001（作者：Mohammed J. Zaki）
- **可信度**：**仅核书目**
- **解决的问题**：频繁序列挖掘的效率。
- **核心机制**：**未读到正文**（标题只说 "efficient algorithm"；我不凭记忆编"垂直 id-list"之类的细节）。
- **是否需要训练**：**不需要模型训练**（频繁序列挖掘算法，输入为序列库 + 支持度）。
- **能否用于本项目**：**能，与 PrefixSpan 同类**（若序列特别长可作备选实现）。

#### 卡片 D4-3｜Selective review of offline change point detection methods
- **编号**：arXiv:1801.00718v3；journal_ref: *Signal Processing*, 167:107299, 2020
- **年份**：2018 预印 / 2020 发表（作者：Charles Truong, Laurent Oudre, Nicolas Vayatis）
- **可信度**：**已读原文**（arXiv summary）
- **解决的问题**：离线多变点检测方法散乱。原文：*"a general yet structuring methodological strategy is adopted to organize this vast body of work"*。
- **核心机制**：把检测算法分解为**三要素**——*"a cost function, a search method and a constraint on the number of changes"*（代价函数 / 搜索方法 / 变化数约束），并**提供 Python 包 `ruptures`** 实现主要算法。
- **是否需要训练**：**不需要标注训练**（代价函数+搜索+约束的统计框架）。
- **能否用于本项目**：**能，而且是"发现用户变了"这一子问题的正解**。把某个行为指标（例如"每天手动整理某类文件的次数"或"某个 app 的日均时长"）当一维信号，用 `ruptures` 找变化点。**关键优点：它要求先选定一个标量指标**——所以它不是"端到端从原始事件找问题"，而是"给定指标找转折"。

#### 卡片 D4-4｜Bayesian Online Changepoint Detection
- **编号**：arXiv:0710.3742v1（comment: "7 pages, 4 figures, latex"）
- **年份**：2007-10-19（作者：Ryan Prescott Adams, David J. C. MacKay）
- **可信度**：**已读原文**（arXiv summary）
- **解决的问题**：多数贝叶斯工作只做**回顾式分割**（retrospective segmentation），缺少**在线**变点检测。原文：*"most Bayesian papers have focused on the retrospective segmentation problem."*
- **核心机制**：假设变点前后参数独立，推导**精确在线推断**：*"We compute the probability distribution of the length of the current ``run,'' or time since the last changepoint, using a simple message-passing algorithm."*
- **是否需要训练**：**不需要标注训练**，但**需要指定先验**（这是贝叶斯方法的输入要求，不是训练）。
- **能否用于本项目**：**能**。它天然适合"流式、增量、只往前看"的桌面事件流；我们每天都在追加 events，不需要重新跑全量离线分段。代价是需要为每个指标设先验。

#### §1.4 补充清单（算法谱系与原始出处）

| 标题 | 编号 | 年份 | 可信度 | 要点 |
|---|---|---|---|---|
| Mining sequential patterns | DOI 10.1109/icde.1995.380415（ICDE'95） | 1995 | **仅核书目** | Agrawal, Srikant。SPM 的**最早原始出处** |
| Mining sequential patterns: Generalizations and performance improvements（GSP） | DOI 10.1007/bfb0014140（EDBT'96, LNCS） | 1996 | **仅核书目** | Srikant, Agrawal。加入时间约束、滑动窗口等泛化 |
| BIDE: efficient mining of frequent closed sequences | DOI 10.1109/icde.2004.1319986（ICDE 2004） | 2004 | **仅核书目** | Wang, Han。**闭合**序列挖掘（压缩冗余模式）。注：常被引作 2007，Crossref 记 2004，以 Crossref 为准 |
| A taxonomy of sequential pattern mining algorithms | DOI 10.1145/1824795.1824798（ACM Computing Surveys 43(1)） | 2010 | **已读原文**（Crossref abstract） | Mabroukeh, Ezeife。原文：*"This article investigates these algorithms by introducing a taxonomy for classifying sequential pattern-mining algorithms based on important key features supported by the techniques. This classification aims at enhancing understanding of sequential pattern-"*（截断）。含 closed / maximal / incremental / hierarchical 等表示 |
| A Survey of Parallel Sequential Pattern Mining | DOI 10.1145/3314107（ACM TKDD） | 2019 | **仅核书目** | Gan, Lin, Fournier-Viger, Chao, Yu |
| Repetitive nonoverlapping sequential pattern mining | arXiv:2311.09667v1 | 2023-11 | **已读原文** | Geng, Wu, Li, Liu, Fournier-Viger, Zhu, Wu。原文关键批评：*"Classical SPM can only find the common features of sequences, but it ignores the number of occurrences of the pattern in each sequence, i.e., the degree of interest of specific users."* → **对"重复手工劳动"这个语义极其贴合**：我们要找的不是"出现过"，而是"出现太多次" |
| TaSPM: Targeted Sequential Pattern Mining | arXiv:2202.13202v1 | 2022-02 | 已读原文（摘要） | 定向 SPM（带目标约束），可用于"只想找围绕某类文件/某 app 的套路" |
| OPP-Miner: Order-preserving sequential pattern mining | arXiv:2202.03140v2 | 2022-01 | 已读原文（摘要） | 保序 SPM |
| A tutorial on hidden Markov models and selected applications in speech recognition | DOI 10.1109/5.18626（*Proceedings of the IEEE* 77(2)） | 1989 | **仅核书目** | Rabiner。HMM 的规范教程与原始出处参照 |
| Anomaly detection: A survey | DOI 10.1145/1541880.1541882（ACM Computing Surveys 41(3)） | 2009 | **仅核书目** | Chandola, Banerjee, Kumar |
| Anomaly Detection for Discrete Sequences: A Survey | DOI 10.1109/tkde.2010.235（IEEE TKDE） | 2012 | **仅核书目** | Chandola, Banerjee, Kumar。**离散序列**（正是我们的事件类型序列）异常检测综述 |
| Sequential change-point detection: Computation versus statistical performance | arXiv:2210.05181v3 | 2022-10 | **已读原文** | Wang, Xie。强调**计算/内存效率 vs 统计功效**的权衡是新文献才重视的角度；*"reviews several sequential change-point detection procedures, ranging from classic... to more recent non-parametric procedures that consider computation, memory efficiency"* |
| Challenges in anomaly and change point detection | arXiv:2212.13520v1；ESANN 2022 | 2022-12 | **已读原文** | Olteanu, Rossi, Yger。导读型，列出重要综述与两个活跃研究方向 |
| Relationship-aware sequential pattern mining / One-off Negative SPM / Memory-Efficient SPM with Hybrid Tries | arXiv:1212.5389v1 / 2207.11950v1 / 2202.06834v3 | 2012 / 2022 | 已读原文（摘要） | SPM 变体谱系，选型时可查 |
| Declarative Sequential Pattern Mining of Care Pathways | arXiv:1707.08342v1 | 2017-07 | 已读原文（摘要） | 把 SPM 用在"护理路径"这类**人类行为序列**上的应用样例 |

**方向四小结**：这一方向的**算法是成熟且免训练的**（PrefixSpan / SPADE / BIDE / GSP 都是 1995–2004 的经典，均只需"序列库 + 支持度"）。**真正的问题不是算法，而是"什么是序列中的一个符号"**——回到 D1-1。

---

### §1.5 方向五：从行为日志生成"机会/建议"

#### 卡片 D5-1｜Motif: Discovering and Automating Personal Web Workflows
- **编号**：arXiv:2607.10531v1
- **年份**：2026-07-12（作者：Shaokang Jiang, Daye Nam）
- **可信度**：**已读原文**（arXiv summary）
- **解决的问题**：**这是本次调研中与 OpenLookout 最贴合的一篇。**原文点出两个现有工作的致命前提：*"these approaches rely on the assumption that users know what to automate and what is capable of being automated"*；以及成本问题 *"automation via LLM agents is often expensive compared with programs"*。
- **核心机制**（原文）：*"passively observes everyday browser activity to discover recurring interaction patterns that are programmable, makes recommendations to users whenever a pattern is discovered and generate a program to install after user confirmation. Users can review, and refine the program using natural language."*
  → 拆成四步：**(1) 被动观察 → (2) 发现"可编程的"重复交互模式 → (3) 向用户推荐 → (4) 用户确认后生成并安装程序**。
- **是否需要训练**：**不训练**，但**依赖 LLM**（这就是它自己承认的成本问题）。
- **能否用于本项目**：**能，但要改两处**。
  - 相同：被动观察 + 发现重复模式 + (推荐)。
  - **不同点一**：它只覆盖**浏览器内**活动（本项目覆盖全桌面 app）。
  - **不同点二（关键）**：它**会主动向用户推荐**（"makes recommendations to users"），本项目要求**不打扰用户**。所以我们要把第 (3) 步从"推荐给人"改成"交给 agent 内部判定并直接修"，这恰好是文献没有覆盖的部分。
  - **可抄**：它把"发现"与"生成程序"分成两个可分离阶段，且**产物是程序而非模型**——与本 harness 的形态一致。

#### 卡片 D5-2｜EAGER: Programming Repetitive Tasks by Example
- **编号**：DOI 10.1145/108844.108850（CHI '91）；另有 DOI 10.1016/b978-0-08-051574-8.50083-2（1995, *Readings in Human–Computer Interaction* 重印）
- **年份**：1991（作者：Allen Cypher）
- **可信度**：**仅核书目**
- **解决的问题**：让用户免于为重复任务编程。标题即机制：**programming repetitive tasks by example**。
- **核心机制**：**未读到正文**。可确证的是"从用户的重复操作示例中归纳出自动化"这一范式（Programming by Demonstration 的开山之作之一）。
- **是否需要训练**：**不需要模型训练**（PBD 范式是归纳/合成，不是统计学习）。
- **能否用于本项目**：**能，作为"产物形态"的祖先**：Eager 输出的是**可执行宏**——与本项目"agent 直接替用户做"的产物同构。它确立了一条：**正确的交付物是程序/动作，不是"一份洞察报告"**。

#### 卡片 D5-3｜CoScripter: automating & sharing how-to knowledge in the enterprise
- **编号**：DOI 10.1145/1357054.1357323（CHI 2008）
- **年份**：2008（作者：Gilly Leshed, Eben M. Haber, Tara Matthews, Tessa Lau）
- **可信度**：**仅核书目**
- **解决的问题**：企业里"怎么做某件事"的知识既难自动化也难共享。
- **核心机制**：**未读到正文**。可确证的定位是：把 how-to 知识**记录/自动化/共享**三合一。
- **是否需要训练**：**不需要模型训练**（录制/演示型）。
- **能否用于本项目**：**部分能**。它的"共享"部分（企业）不适用；但"**把一段用户操作变成可复用脚本**"这个形态与本项目一致。

#### 卡片 D5-4｜Why Programming by Demonstration Systems Fail: Lessons Learned for Usable AI
- **编号**：DOI 10.1609/aimag.v30i4.2262（*AI Magazine* 30(4)）
- **年份**：2009（作者：Tessa Lau）
- **可信度**：**仅核书目**
- **解决的问题**：PBD 系统**为什么失败**。
- **核心机制**：**未读到正文**。标题表明本文是**失败复盘**（lessons learned），而非新系统。
- **是否需要训练**：不适用。
- **能否用于本项目**：**能，作为风险清单**。这是**必读的反面教材**：一个从 1980s 活到 2000s、有 Eager / CoScripter 等真实系统的范式，最后大面积失败。我们这个方向必须解释清楚"为什么这次不一样"，否则会重蹈覆辙。

#### 卡片 D5-5｜Automating string processing in spreadsheets using input-output examples
- **编号**：DOI 10.1145/1926385.1926423（POPL 2011）；亦见 DOI 10.1145/1925844.1926423（ACM SIGPLAN Notices）
- **年份**：2011（作者：Sumit Gulwani）
- **可信度**：**仅核书目**
- **解决的问题**：让非程序员用**少量输入→输出例子**就能自动完成字符串处理。
- **核心机制**：**从 input-output 例子合成程序**（Programming by Example / 归纳合成）。可确证：输入是"少量例子"，输出是"程序"。
- **是否需要训练**：**不需要模型训练**（是合成/搜索，不是学习参数）。
- **能否用于本项目**：**能，是最重要的正面参照**：这个范式**成功从论文走进了产品**（Excel Flash Fill）。它的成功要素清晰：**领域受限 + 少量例子 + 产物可检查 + 出错代价低**。本项目要复制的是这四条，而不是"通用桌面理解"。

#### §1.5 补充清单

| 标题 | 编号 | 年份 | 可信度 | 要点 |
|---|---|---|---|---|
| Identifying candidate routines for RPA from unsegmented UI logs | arXiv:2008.05782v2 / ICPM 2020 | 2020 | **已读原文** | 见 D1-2。**这同时也是方向五的核心论文**："找重复套路 → 便于自动化" |
| Syll: Open-Source Personal Automation with Cross-Surface Execution | arXiv:2606.07594v1 | 2026-05 | **已读原文** | 原文：*"users teach procedures through direct demonstration, which Syll compiles into reusable skills"*。**路线是"用户教"，不是"系统发现"**——与本项目的关键差别 |
| An automation recommendation framework based on Task Mining and Large Language Models (ORBITA) | DOI 10.51473/rcmos.v1i1.2026.2199（*RCMOS* 1(1)） | 2026 | **仅核书目** | 巴西期刊，**venue 可信度低，未验证同行评审**。仅作"有人在做 task mining + LLM 出自动化建议"的信号，不作为方法依据 |
| Log2Plan | arXiv:2509.22137v1 | 2025-09 | **已读原文** | 依赖 LLM/VLM planner-executor，包含"从用户行为日志做 task mining 以支持个性化复用" |
| AutoDroid: LLM-powered Task Automation in Android | arXiv:2308.15272v4 | 2023-08 | 已读原文（摘要） | 移动端 LLM 任务自动化。**作为反面对照：需要 LLM 推理，不在本项目"免训练、纯 harness"范围内** |
| VASTA: A Vision and Language-assisted Smartphone Task Automation System | arXiv:1911.01474v1 | 2019-11 | 已读原文（摘要） | 同上，移动端 |
| A Survey on (M)LLM-Based GUI Agents | arXiv:2504.13865v2 | 2025-03 | 已读原文（摘要） | GUI agent 综述，可用于说明"当前主流路线是 MLLM，不是免训练模式挖掘" |

---

## §2 汇总表

适配度 1–5 的评分口径：
- **5** = 机制可直接搬到本项目（输入字段同构或可降维得到）；
- **4** = 机制可搬，但需改写输入表征或补一层归一化；
- **3** = 提供概念/判据/负面证据，不直接产生检测结果；
- **2** = 领域或数据前提明显不匹配，仅作背景；
- **1** = 不适用。

| # | 方法 | 代表文献（编号） | 输入要求 | 免训练? | 适配度 |
|---|---|---|---|---|---|
| 1 | UI log 参考数据模型（动作字母表归一化） | Abb & Rehse 2022, arXiv:2207.12054 | click/字段级 UI log；本项目需降维 | 是（无模型） | **5** |
| 2 | 未切分日志的 routine 发现 | Leno et al. 2020, arXiv:2008.05782 | 连续无任务边界的 UI log | 是（无监督/统计；**未读到正文**） | **4** |
| 3 | 噪声容忍的 routine log 抽取 | de Leoni et al. 2025, arXiv:2510.08118 | 未切分 + 含变体的 UI log | 是（聚类；**细节未读到**） | **4** |
| 4 | 工业 task mining（流程重建 + 变体 + 瓶颈 + 自动化建议） | MS Learn task-mining-overview；UiPath Task Mining Introduction；Celonis What-is-Task-Mining | 完整 recorder 采集的全量交互 | **未核实**（无公开算法） | 3 |
| 5 | Task mining 应用与挑战地图 | Mayr et al. 2022, ECIS RiP #55 | — | 不适用 | **4**（选型防重复） |
| 6 | Pareto 原则做优先级 | van der Aalst 2020, DOI 10.5220/0009979200050012 | 频次统计 | 是 | 3 |
| 7 | Workaround 理论 | Alter 2014, DOI 10.17705/1cais.03455 | 定性 | 不适用 | 3（只给语言） |
| 8 | 哪些 workaround 可/不可被挖掘出来 | Outmazgin & Soffer 2013, DOI 10.1007/978-3-642-38484-4_5 | 事件日志 + 流程模型 | 是（规则/比对；**未读到正文**） | **4** |
| 9 | SWORD 半自动 workaround 检测框架 | van der Waal et al. 2022, DOI 10.1007/978-3-031-16103-2_9 | 事件日志 +（原设计中的）专家判断 | 未核实 | **4**（换掉专家环节即可用） |
| 10 | 时序 workaround 深度学习检测 | Weinzierl et al. 2021, DOI 10.1080/2573234x.2021.1978337 | 带时间戳事件日志 | **否，需训练** | 3（问题定义可抄） |
| 11 | 偏离可欲性分级框架 | Grohs et al. 2025, arXiv:2506.11525 | 偏离 + 输入因素 | 是（程序框架） | **4**（防误报） |
| 12 | 在线一致性检查（增量前缀对齐） | Schuster & Kolhof 2020, arXiv:2101.00958 | 事件流 + 流程模型 | 是 | **4**（本项目缺流程模型，可改用自建基线） |
| 13 | 用户挫败成因 | Ceaparu et al. 2004, DOI 10.1207/s15327590ijhc1703_3 | 问卷（非行为日志） | 是 | 2 |
| 14 | 找回/重访行为模型 | Capra & Perez-Quinones 2003, arXiv:cs/0310011 | 会话日志 | 是 | 3 |
| 15 | PIM 跨工具"只进不出" | Boardman & Sasse 2004, DOI 10.1145/985692.985766 | 文件系统 + 访谈 | 是 | 3（可转成纯字段指标） |
| 16 | 桌面组织即提醒机制 | Malone 1983, DOI 10.1145/357423.357430 | 观察 | 是 | 3（**批判性反例**） |
| 17 | 个人数字资料的认知外包 | Bergman & Whittaker 2016, DOI 10.7551/mitpress/9780262035170.001.0001 | — | 是 | 3（**判据来源**） |
| 18 | 文件管理的个体差异（预测力很弱） | Dinneen & Frissen 2020/2021, arXiv:2109.15272 | 文件集合快照 | 是 | 2 |
| 19 | PrefixSpan（前缀投影模式增长） | Pei et al. 2001, DOI 10.1109/icde.2001.914830 | 序列库 + 最小支持度 | **是** | **5** |
| 20 | SPADE | Zaki 2001, DOI 10.1023/a:1007652502315 | 序列库 + 支持度 | **是** | **4** |
| 21 | BIDE（闭合序列） | Wang & Han 2004, DOI 10.1109/icde.2004.1319986 | 序列库 + 支持度 | **是** | 3 |
| 22 | SPM 分类学（算法选择） | Mabroukeh & Ezeife 2010, DOI 10.1145/1824795.1824798 | — | 不适用 | **4** |
| 23 | 重复非重叠序列挖掘（RNP-Miner） | Geng et al. 2023, arXiv:2311.09667 | 序列库（关注**出现次数**） | **是** | **4** |
| 24 | HMM | Rabiner 1989, DOI 10.1109/5.18626 | 观测序列 + 隐状态假设 | **否，需参数估计** | 3 |
| 25 | 离线多变点检测 + `ruptures` | Truong et al. 2020, arXiv:1801.00718 | **多变量时间序列**（需先定标量指标） | 是（统计） | **4** |
| 26 | 贝叶斯在线变点（BOCPD） | Adams & MacKay 2007, arXiv:0710.3742 | 数据流 + 先验 | 是（需先验，不需标注） | **4** |
| 27 | 序贯变点：计算 vs 统计功效 | Wang & Xie 2022, arXiv:2210.05181 | 流式数据 | 是 | 3 |
| 28 | 离散序列异常检测综述 | Chandola et al. 2012, DOI 10.1109/tkde.2010.235 | 离散符号序列 | 视所选方法 | **4** |
| 29 | Eager：按示例给重复任务编程 | Cypher 1991, DOI 10.1145/108844.108850 | 用户重复操作示例 | **是** | **4** |
| 30 | CoScripter | Leshed et al. 2008, DOI 10.1145/1357054.1357323 | 录制/演示 | 是 | 3 |
| 31 | Flash Fill / PBE 合成 | Gulwani 2011, DOI 10.1145/1926385.1926423 | **少量 输入→输出 例子** | **是** | **4**（成功范式模板） |
| 32 | PBD 失败教训 | Lau 2009, DOI 10.1609/aimag.v30i4.2262 | — | 不适用 | **4**（风险清单） |
| 33 | Motif：被动观察 → 复用模式 → 推荐 → 生成程序 | Jiang & Nam 2026, arXiv:2607.10531 | 浏览器被动活动 | 是（依赖 LLM） | **5**（形态最贴，但需去掉"推荐给人"） |
| 34 | Log2Plan | Lee et al. 2025, arXiv:2509.22137 | 用户行为日志 | LLM/VLM | 2 |
| 35 | Syll（用户示教 → 编译成 skill） | Zhang et al. 2026, arXiv:2606.07594 | 用户示范 | 多模态 agent | 3 |
| 36 | ORBITA（task mining + LLM 出自动化建议） | Bastos 2026, DOI 10.51473/rcmos.v1i1.2026.2199 | task mining 日志 | LLM | 2（venue 不可信） |

---

## §3 最该抄的 3 条（具体到机制）

### 抄法一：把"未切分连续事件流"当一等公民，走 `切分 → 签名 → 支持度 → 变体聚类` 四步

**出处**：Leno et al. 2020（arXiv:2008.05782，明确以 unsegmented UI log 为输入）+ de Leoni et al. 2025（arXiv:2510.08118，补上"噪声/变体容忍"和"要输出可直接做模型发现的东西"）。

**不要做什么**：不要先人工划"任务边界"。本项目两个月的事件流是连续的一条线（`E:\OpenLookout\data\events.jsonl` + `backfill\events.jsonl`），与文献里的 unsegmented UI log 同构。任何"先把一天切成一个 session"的预处理都是在偷偷注入假设。

**具体机制**（可落在本项目的字段上）：
1. **切分**：用 `app` 的稳定切换点做天然边界——当 `app` 发生变化且新 `app` 连续停留 ≥ T（例如 60 秒）时开启一个新片段；`focus` 事件的 `dur_s` 用于加权，短于 T 的片段直接丢弃（它们多为切窗口的噪声）。
2. **签名**：把每个片段表示成一个**动作三元组序列** `(app, type, object_token)`。`type` 已经是 5 类有限集；`object_token` 对 file_* 事件取「扩展名 + 父目录最后一段」而**不是完整 `path`**（理由见抄法二）。
3. **支持度**：对签名序列做子序列匹配，保留**支持度 ≥ k 且跨天数 ≥ d**（例如 k ≥ 5、d ≥ 3）的模式。跨天数是本项目专属的强过滤器：一个模式在一天内被触发 5 次可能只是选题日，跨 3 周出现 5 次才是"恒常的重复劳动"。
4. **变体聚类**：同一签名的多个实例如果只在顺序/长度上小幅不同（插入/删除 1–2 个动作），应聚成一个 routine 并统计**变体数**。de Leoni 这篇的贡献正在于"人类执行天然带噪"；如果按精确匹配，用户每次少点一步就会让整个模式消失。
5. **输出**：`(routine 签名, 变体数, 出现天数, 平均片段时长, 手动动作数)`。注意 MS 的 task mining 文档明确把 "how many variations" 和 "which activities take the longest" 并列为洞察项——**变体数与时长要一起报**。

### 抄法二：先建"动作字母表"，而且 object 要刻意降维——否则支持度恒为 1

**出处**：Abb & Rehse 2022（arXiv:2207.12054）的 UI-log 参考数据模型。它把 UI log 定义为"每次单击/每次输入 = 一个事件"的**高分辨率**日志，并痛陈各工具的概念化不一致导致无法互通。

**为什么这条排第二却可能最关键**：本项目的 `title` 是自由文本，`path` 是唯一路径。如果直接拿 `path` 当符号，那么**每个文件都是一个独一无二的符号，任何子序列的支持度都是 1**，PrefixSpan 会退化成"罗列所有历史"。

**具体机制**：
1. 定义 `action = (system, action_type, object_class)`，其中 `system = app`（做一次小写/别名归一，例如 `Code`→`vscode`），`action_type` 就是 `type` 五类，`object_class` 是**受控词表**：
   - file_* 事件：`object_class = 扩展名`（`.pdf` / `.xlsx` / `.jsonl`），必要时加"父目录深度 1 的标签"（`E:\OpenLookout\docs\**` → `openlookout-docs`）。
   - url 存在时：`object_class = 域名`（不是完整 URL）。
   - clipboard：`object_class = 目标的 app`（谁在接收粘贴）。
2. 把**完整 `path` 保留为"实例属性"而不是"模式符号"**——模式用粗符号匹配，命中后用完整 path 报出"具体是哪几个文件"。这样既得到高支持度模式，又不丢可解释性。
3. 归一化完成后，用 PrefixSpan（抄法一第 3 步）在**粗符号序列**上挖。

### 抄法三：不要做端到端黑箱"发现问题"，做"规则出候选 + 显式分级 + 可解释产物"

**出处**：三条互相印证——
- van der Waal et al. 2022 的 **SWORD** 框架（DOI 10.1007/978-3-031-16103-2_9）标题即以 **semi-automatic** 自我定位：检测是"机器出候选"，判定不是纯自动；
- Grohs et al. 2025（arXiv:2506.11525）指出一致性检查**能找偏离但不能判断偏离是好是坏**，并给出"把偏离分为问题/可接受/有益"的分步程序；
- Gulwani 2011（Flash Fill，POPL 2011）证明了同一形态在另一领域**可以走进产品**：领域受限 + 少量例子 + 产物可检查。

**具体机制**：
1. **候选由规则谓词产生，不由模型产生。** 例：
   - *手工搬运谓词*：「在 app A 复制（`clipboard`）→ 60 秒内切到 app B → 保存（`file_save`）」在 X 天内出现 ≥ k 次；
   - *绕路谓词*：「A→B→A」三段切换在 5 分钟内发生 ≥ m 次，且每次 `dur_s` 都很短；
   - *只进不出谓词*：`file_create` 的 path 集合中，创建后 ≥ 30 天无任何 `file_open` 的比例 > 阈值（来自 D3-2）；
   - *变化点谓词*：某 `(app, object_class)` 的周频次的时间序列上检测到变点（`ruptures` / BOCPD，来自 D4-3/D4-4）。
2. **每条候选必须带"三级判定"字段**：`problem / acceptable / beneficial`（照抄 D2-5 的分级），并且**分级默认不写"problem"**——因为 Malone 1983 与 Bergman & Whittaker 2016 都指出"乱"往往是有功能目的的。默认值偏保守，是本项目唯一的误报防线。
3. **产物是动作/程序，不是报告**（Eager 与 Flash Fill 的共同点，也是 MS 文档里 "automation recommendations that reveal which connectors to use" 的形态）。对本 harness：输出应该是**一个可执行的自动化改动或 agent 决策**，附一段"我为什么认为这是机会"的显式规则回放（哪条谓词、哪几次事件命中）。
4. **明确不要抄的**：不要抄 Motif 的"向用户推荐并等确认"（违反零打扰），也不要抄 Weinzierl 2021 的深度学习方法（是本项目明令不做的训练）。Motif 的价值在于它验证了"被动观察 → 发现可编程重复模式"这条链路在浏览器里可行；我们要替换掉的是它的**出口**。

---

## §4 这份调研证明不了什么

1. **证明不了"从纯桌面事件流能可靠发现用户未察觉的问题"。** 我读到的每一篇 task mining / process mining 文献都处在**组织级**环境：有业务真值可比对（Celonis 明确说 task mining 补的是 transactional system 之外的步骤，前提是**有 transactional system**）、有 SME 可访谈（SWORD 是 semi-automatic，因为原来是 interview-based）、有已知任务可圈定（UiPath Task Mining 的起点原文是 *"variations of a known task"*）。本项目是**单用户、无任务标注、无业务真值、无 SME**。**没有任何一篇文献报告过"单用户私人流水 → 发现并主动解决未察觉问题"的端到端成功率或误报率**，我也没有找到任何一篇声称做过这件事的论文。

2. **证明不了这些算法在 OpenLookout 的事件粒度下依然有效——粒度落差会伤到算法本体。** Abb & Rehse 明确把 UI log 定义为 *"high-resolution event logs that record low-level activities... such as clicking a button or entering a string into a text field"*；而本项目只有 `focus/file_save/file_open/file_create/clipboard` 五类、没有点击目标、没有控件、`title` 是自由文本。后果是具体的：(a) PrefixSpan 这类算法在**粗粒度 + 自由文本 `title`** 上，支持度阈值极难标定——`title` 不归一化则每个模式支持度为 1，归一化过度则丢掉区分度；(b) `focus` 是**持续态**不是**瞬时动作**（它有 `dur_s`），而所有 UI log 算法都按瞬时事件设计，这会让"序列"的语义在两种事件间不一致；(c) 没有点击目标，"重复点击某按钮"这类最经典的 RE 信号**根本不存在**。**我读到的摘要里，没有任何一篇在这种粒度上验证过。**

3. **证明不了工业界的做法可以照抄。** Microsoft / UiPath / Celonis 我**只核到产品文档**，没有核到任何公开的算法论文、评测协议或准确率数字。UiPath 的 *"uses AI to cluster and merge the captured traces"* 和 MS 的 *"automation recommendations that reveal which connectors to use"* 是**产品描述**，不含可复现细节。**我核不到 Microsoft Process Advisor / UiPath Task Mining / Celonis Task Mining 的方法论论文——这三家的算法是不可照抄的。** 能抄的只有输出物形态（process map、变体统计、应用时长统计、自动化骨架）。

4. **"免训练"这个结论比看上去弱。** 支撑它的主要是两个地方：SPM 家族（PrefixSpan/SPADE/BIDE/GSP，1995–2004 的经典算法）与变点检测（`ruptures` / BOCPD / Rabiner HMM 的参数估计）。但：(a) SPM 家族**全部是【仅核书目】**——我只有 Crossref 的标题/年份/DOI，**没有读到它们的伪码或复杂度分析**，机制描述来自标题字面；(b) 本方向唯一**直接**针对"未察觉问题"的检测方法（Weinzierl et al. 2021 的 temporal workaround detection）**偏偏是需要训练的深度学习**，而且我**连它的摘要都没抓到**（Crossref 无 abstract，tandfonline 返回 len=5675 无 abstract 段），所以我对它的机制一无所知；(c) Motif 虽然不训练，但**依赖 LLM**，且论文自己承认 *"automation via LLM agents is often expensive compared with programs"*。**因此"存在一条完全免训练、且能发现未察觉问题的成熟路径"这件事，本调研没有证明。**

5. **证明不了"零打扰"在文献中有先例。** 我在方向五找到的所有系统都要求用户参与：Eager（用户给示例）、CoScripter（用户录制）、Flash Fill（用户给输入输出例子）、Motif（原文 *"makes recommendations to users... generate a program to install after user confirmation"*）、Syll（原文 *"users teach procedures through direct demonstration"*）、Liu 2016 的 re-finding 排序（原文直接说 *"By asking the user a list of questions about the target"*）。**没有一篇报告过零确认直接代用户执行的系统的精确率/召回率。** 这意味着本项目的"不打扰"约束**拿不到任何前人的 precision/recall 参考值**，误报代价只能自己扛。

6. **证明不了"乱 = 问题"这个本项目的隐含前提。** 反而是这批文献在**质疑**它：Malone 1983 的结论方向是"桌面的杂乱本身承担了提醒功能"；Bergman & Whittaker 2016 的"认知外包"论把组织方式视为**记忆策略而非缺陷**；Dinneen & Frissen 2020/2021 的原文结论更是 *"We find no notable associations between users' attributes and their collections, and minimal predictive power"* ——**从用户的文件集合去推断用户状态这条路，实测预测力很弱**。所以本调研**没有**证实"用户的操作痕迹里必然埋着一个他未察觉的问题"；它只是证实了"存在一批可以拿来生成候选的机械方法"。

7. **证明不了方法的可迁移性——我读到的大部分是摘要，不是方法。** 本文所有【已读原文】标签对应的是 **arXiv summary 字段或网页正文**，**没有一篇是论文正文/PDF**；所有 DOI 类（ACM/Springer/IEEE）都是【仅核书目】。因此：Leno 2020 的**切分算法**我核不到；de Leoni 2025 的**聚类目标函数**我核不到；SWORD 的**谓词集合**我核不到；Outmazgin & Soffer 2013 的**"能/不能被检测"清单**我核不到（而这恰好是 §3 最需要的一张负面清单）；Weinzierl 2021 的**网络结构**我核不到。**如果后续要落地 §3，必须先把这五篇的正文拿到手。** 这是本调研最大的空洞，我不掩饰。

---

## §5 参考文献

> 排序：按本文出现顺序。可信度标签沿用 §0.3。
> 链接为核实时的实际访问地址（arXiv 用 `arxiv.org/abs/<id>`；DOI 类用 `doi.org/<DOI>`）。

**方向一：Task mining / Process mining on UI logs**
1. Abb, L., & Rehse, J.-R. (2022). *A Reference Data Model for Process-Related User Interaction Logs.* arXiv:2207.12054v1. https://arxiv.org/abs/2207.12054 ｜【已读原文】
2. Leno, V., Augusto, A., Dumas, M., La Rosa, M., Maggi, F., & Polyvyanyy, A. (2020). *Identifying candidate routines for Robotic Process Automation from unsegmented UI logs.* arXiv:2008.05782v2 (International Conference on Process Mining 2020). https://arxiv.org/abs/2008.05782 ｜【已读原文】
3. de Leoni, M., Khan, F. A., & Agostinelli, S. (2025). *Accurate and Noise-Tolerant Extraction of Routine Logs in Robotic Process Automation (Extended Version).* arXiv:2510.08118v2. https://arxiv.org/abs/2510.08118 ｜【已读原文】
4. Mayr, A., Herm, L.-V., Wanner, J., & Janiesch, C. (2022). *Applications and Challenges of Task Mining: A Literature Review.* ECIS 2022 Research-in-Progress Papers, Paper 55. https://aisel.aisnet.org/ecis2022_rip/55/ ｜【已读原文】
5. El-Gharib, N. M., & Amyot, D. (2023). *Robotic Process Automation Using Process Mining – A Systematic Literature Review.* Data & Knowledge Engineering, 102229. arXiv:2204.00751v2. https://arxiv.org/abs/2204.00751 ｜【已读原文（摘要）+ 仅核书目（期刊卷页）】
6. van der Aalst, W. M. P. (2020). *On the Pareto Principle in Process Mining, Task Mining, and Robotic Process Automation.* Proceedings of the 9th International Conference on Data Science, Technology and Applications. DOI 10.5220/0009979200050012. https://doi.org/10.5220/0009979200050012 ｜【仅核书目】
7. van der Aalst, W. M. P., et al. (2012). *Process Mining Manifesto.* Business Process Management Workshops, LNBIP. DOI 10.1007/978-3-642-28108-2_19. https://doi.org/10.1007/978-3-642-28108-2_19 ｜【仅核书目】
8. Dirnberger, Loidl, & Brunner (2023). *Fundamental Framework for Task Mining Technology Adoption.* DOI 10.1145/3605423.3605443. https://doi.org/10.1145/3605423.3605443 ｜【仅核书目】
9. Microsoft Learn. *Overview of task mining* (Power Automate). https://learn.microsoft.com/en-us/power-automate/task-mining-overview ｜【已读原文（产品文档）】
10. Microsoft Learn. *Overview of process mining and task mining in Power Automate*. https://learn.microsoft.com/en-us/power-automate/process-advisor-overview ｜【已读原文（产品文档）】
11. UiPath Documentation. *Task Mining — Introduction* (Automation Cloud, latest). https://docs.uipath.com/task-mining/automation-cloud/latest/user-guide/introduction-as ｜【已读原文（产品文档）】
12. Celonis. *What is Task Mining?* https://www.celonis.com/insights/topics/what-is-task-mining ｜【已读原文（产品文档）】
13. Lee, S., Yoon, S., Lee, S., Kim, H., & Sim, J. Y. (2025). *Log2Plan: An Adaptive GUI Automation Framework Integrated with Task Mining Approach.* arXiv:2509.22137v1. https://arxiv.org/abs/2509.22137 ｜【已读原文】
14. (2023). *Recording of 50 Business Assignments.* arXiv:2308.12211v1. https://arxiv.org/abs/2308.12211 ｜【已读原文（摘要）】

**方向二：Workaround / friction detection**
15. Alter, S. (2014). *Theory of Workarounds.* Communications of the Association for Information Systems, 34(55). DOI 10.17705/1cais.03455. https://doi.org/10.17705/1cais.03455 ｜【仅核书目】
16. Outmazgin, N., & Soffer, P. (2013). *Business Process Workarounds: What Can and Cannot Be Detected by Process Mining.* LNBIP. DOI 10.1007/978-3-642-38484-4_5. https://doi.org/10.1007/978-3-642-38484-4_5 ｜【仅核书目】
17. van der Waal, Beerepoot, van de Weerd, & Reijers (2022). *The SWORD is Mightier Than the Interview: A Framework for Semi-automatic WORkaround Detection.* BPM 2022, LNCS. DOI 10.1007/978-3-031-16103-2_9. https://doi.org/10.1007/978-3-031-16103-2_9 ｜【仅核书目】
18. Weinzierl, Wolf, Pauli, Beverungen, & Matzner (2021). *Detecting temporal workarounds in business processes – A deep-learning-based method for analysing event log data.* Journal of Business Analytics. DOI 10.1080/2573234x.2021.1978337. https://doi.org/10.1080/2573234X.2021.1978337 ｜【仅核书目（摘要未取到）】
19. Grohs, M., Cordes, N., & Rehse, J.-R. (2025). *A Procedural Framework for Assessing the Desirability of Process Deviations.* arXiv:2506.11525v1. https://arxiv.org/abs/2506.11525 ｜【已读原文】
20. Ferneley, E., & Sobreperez, P. (2006). *Resist, comply or workaround? An examination of different facets of user engagement with information systems.* European Journal of Information Systems. DOI 10.1057/palgrave.ejis.3000629. https://doi.org/10.1057/palgrave.ejis.3000629 ｜【仅核书目】
21. Outmazgin, van der Waal, Beerepoot, Hadar, van de Weerd, & Soffer (2023). *From Automatic Workaround Detection to Process Improvement: A Case Study.* BPM Forum, LNBIP. DOI 10.1007/978-3-031-41623-1_22. https://doi.org/10.1007/978-3-031-41623-1_22 ｜【仅核书目】
22. Löhr, Bartelheimer, Köhne, Nordlohne, Alile, & Latten (2025). *Forging the LongSWORD: Exaptation and Enhancement of the SWORD Framework for Workaround Detection.* BPM Workshops, LNBIP. DOI 10.1007/978-3-031-78666-2_24. https://doi.org/10.1007/978-3-031-78666-2_24 ｜【仅核书目】
23. Soffer, Outmazgin, Hadar, & Tzafrir (2023). *Why Work Around the Process? Analyzing Workarounds Through the Lens of the Theory of Planned Behavior.* BISE. DOI 10.1007/s12599-023-00802-1. https://doi.org/10.1007/s12599-023-00802-1 ｜【仅核书目】
24. Outmazgin, Soffer, & Hadar (2026). *Leveraging Workarounds for a Problem-Focused Improvement of Business Processes.* BISE. DOI 10.1007/s12599-026-00985-3. https://doi.org/10.1007/s12599-026-00985-3 ｜【仅核书目】
25. Schuster, D., & Kolhof, G. J. (2020). *Scalable Online Conformance Checking Using Incremental Prefix-Alignment Computation.* arXiv:2101.00958v1. https://arxiv.org/abs/2101.00958 ｜【已读原文】
26. Rehse, J.-R., Grohs, M., Klessascheck, F., Klein, L.-M., von Landesberger, T., & Pufahl, L. (2025). *A Task Taxonomy for Conformance Checking.* arXiv:2507.11976v1. https://arxiv.org/abs/2507.11976 ｜【已读原文】
27. Ceaparu, I., Lazar, J., Bessiere, K., Robinson, J., & Shneiderman, B. (2004). *Determining Causes and Severity of End-User Frustration.* International Journal of Human-Computer Interaction, 17(3). DOI 10.1207/s15327590ijhc1703_3. https://doi.org/10.1207/s15327590ijhc1703_3 ｜【仅核书目】

**方向三：PIM 摩擦与重访/找回**
28. Capra, R. G., & Perez-Quinones, M. A. (2003). *Re-Finding Found Things: An Exploratory Study of How Users Re-Find Information.* arXiv:cs/0310011v1. https://arxiv.org/abs/cs/0310011 ｜【已读原文】
29. Boardman, R., & Sasse, M. A. (2004). *"Stuff goes into the computer and doesn't come out": a cross-tool study of personal information management.* CHI 2004. DOI 10.1145/985692.985766. https://doi.org/10.1145/985692.985766 ｜【仅核书目】
30. Malone, T. W. (1983). *How do people organize their desks? Implications for the design of office information systems.* ACM Transactions on Information Systems, 1(1). DOI 10.1145/357423.357430. https://doi.org/10.1145/357423.357430 ｜【仅核书目】
31. Bergman, O., & Whittaker, S. (2016). *The Science of Managing Our Digital Stuff.* MIT Press. DOI 10.7551/mitpress/9780262035170.001.0001. https://doi.org/10.7551/mitpress/9780262035170.001.0001 ｜【仅核书目】
32. Barreau, D., & Nardi, B. A. (1995). *Finding and reminding: file organization from the desktop.* ACM SIGCHI Bulletin, 27(3). DOI 10.1145/221296.221307. https://doi.org/10.1145/221296.221307 ｜【仅核书目】
33. Dinneen, J. D., & Frissen, I. (2020). *Mac Users Do It Differently: the Role of Operating System and Individual Differences in File Management.* ACM CHI 2020 Extended Abstracts, LBW135. arXiv:2109.15272v1. https://arxiv.org/abs/2109.15272 ｜【已读原文】
34. Liu, G. (2016). *A Ranking Algorithm for Re-finding.* arXiv:1602.05157v2. https://arxiv.org/abs/1602.05157 ｜【已读原文】
35. Teevan, J., Jones, W., & Capra, R. (2008). *Personal information management (PIM) 2008.* ACM SIGIR Forum. DOI 10.1145/1480506.1480524. https://doi.org/10.1145/1480506.1480524 ｜【仅核书目】
36. *Personal Information Management* (edited book). (2011). DOI 10.1515/9780295800684. https://doi.org/10.1515/9780295800684 ｜【仅核书目】

**方向四：序列异常 / 变化点 / SPM 原始出处**
37. Agrawal, R., & Srikant, R. (1995). *Mining sequential patterns.* ICDE'95. DOI 10.1109/icde.1995.380415. https://doi.org/10.1109/icde.1995.380415 ｜【仅核书目】
38. Srikant, R., & Agrawal, R. (1996). *Mining sequential patterns: Generalizations and performance improvements.* EDBT'96, LNCS. DOI 10.1007/bfb0014140. https://doi.org/10.1007/bfb0014140 ｜【仅核书目】
39. Pei, J., Han, J., Mortazavi-Asl, B., Pinto, H., Chen, Q., Dayal, U., & Hsu, M.-C. (2001). *PrefixSpan: Mining sequential patterns efficiently by prefix-projected pattern growth.* ICDE 2001. DOI 10.1109/icde.2001.914830. https://doi.org/10.1109/icde.2001.914830 ｜【仅核书目】
40. Zaki, M. J. (2001). *SPADE: An Efficient Algorithm for Mining Frequent Sequences.* Machine Learning, 42. DOI 10.1023/a:1007652502315. https://doi.org/10.1023/a:1007652502315 ｜【仅核书目】
41. Wang, J., & Han, J. (2004). *BIDE: efficient mining of frequent closed sequences.* ICDE 2004. DOI 10.1109/icde.2004.1319986. https://doi.org/10.1109/icde.2004.1319986 ｜【仅核书目】
42. Mabroukeh, N. R., & Ezeife, C. I. (2010). *A taxonomy of sequential pattern mining algorithms.* ACM Computing Surveys, 43(1). DOI 10.1145/1824795.1824798. https://doi.org/10.1145/1824795.1824798 ｜【已读原文（Crossref abstract）】
43. Gan, W., Lin, J. C.-W., Fournier-Viger, P., Chao, H.-C., & Yu, P. S. (2019). *A Survey of Parallel Sequential Pattern Mining.* ACM TKDD. DOI 10.1145/3314107. https://doi.org/10.1145/3314107 ｜【仅核书目】
44. Geng, M., Wu, Y., Li, Y., Liu, J., Fournier-Viger, P., Zhu, X., & Wu, X. (2023). *Repetitive nonoverlapping sequential pattern mining.* arXiv:2311.09667v1. https://arxiv.org/abs/2311.09667 ｜【已读原文】
45. Rabiner, L. R. (1989). *A tutorial on hidden Markov models and selected applications in speech recognition.* Proceedings of the IEEE, 77(2). DOI 10.1109/5.18626. https://doi.org/10.1109/5.18626 ｜【仅核书目】
46. Chandola, V., Banerjee, A., & Kumar, V. (2009). *Anomaly detection: A survey.* ACM Computing Surveys, 41(3). DOI 10.1145/1541880.1541882. https://doi.org/10.1145/1541880.1541882 ｜【仅核书目】
47. Chandola, V., Banerjee, A., & Kumar, V. (2012). *Anomaly Detection for Discrete Sequences: A Survey.* IEEE TKDE. DOI 10.1109/tkde.2010.235. https://doi.org/10.1109/tkde.2010.235 ｜【仅核书目】
48. Truong, C., Oudre, L., & Vayatis, N. (2020). *Selective review of offline change point detection methods.* Signal Processing, 167:107299. arXiv:1801.00718v3. https://arxiv.org/abs/1801.00718 ｜【已读原文】
49. Adams, R. P., & MacKay, D. J. C. (2007). *Bayesian Online Changepoint Detection.* arXiv:0710.3742v1. https://arxiv.org/abs/0710.3742 ｜【已读原文】
50. Wang, H., & Xie, Y. (2022). *Sequential change-point detection: Computation versus statistical performance.* arXiv:2210.05181v3. https://arxiv.org/abs/2210.05181 ｜【已读原文】
51. Olteanu, M., Rossi, F., & Yger, F. (2022). *Challenges in anomaly and change point detection.* ESANN 2022. arXiv:2212.13520v1. https://arxiv.org/abs/2212.13520 ｜【已读原文】
52. TaSPM (2022), arXiv:2202.13202v1；OPP-Miner (2022), arXiv:2202.03140v2；Relationship-aware SPM (2012), arXiv:1212.5389v1；One-off Negative SPM (2022), arXiv:2207.11950v1；Memory-Efficient SPM with Hybrid Tries (2022), arXiv:2202.06834v3 ｜【已读原文（摘要）】
53. Declarative Sequential Pattern Mining of Care Pathways (2017). arXiv:1707.08342v1. https://arxiv.org/abs/1707.08342 ｜【已读原文（摘要）】

**方向五：机会/建议生成与 PbD**
54. Jiang, S., & Nam, D. (2026). *Motif: Discovering and Automating Personal Web Workflows.* arXiv:2607.10531v1. https://arxiv.org/abs/2607.10531 ｜【已读原文】
55. Cypher, A. (1991). *EAGER: Programming Repetitive Tasks by Example.* CHI '91. DOI 10.1145/108844.108850. https://doi.org/10.1145/108844.108850 ｜【仅核书目】
56. Leshed, G., Haber, E. M., Matthews, T., & Lau, T. (2008). *CoScripter: automating & sharing how-to knowledge in the enterprise.* CHI 2008. DOI 10.1145/1357054.1357323. https://doi.org/10.1145/1357054.1357323 ｜【仅核书目】
57. Lau, T. (2009). *Why Programming by Demonstration Systems Fail: Lessons Learned for Usable AI.* AI Magazine, 30(4). DOI 10.1609/aimag.v30i4.2262. https://doi.org/10.1609/aimag.v30i4.2262 ｜【仅核书目】
58. Gulwani, S. (2011). *Automating string processing in spreadsheets using input-output examples.* POPL 2011. DOI 10.1145/1926385.1926423. https://doi.org/10.1145/1926385.1926423 ｜【仅核书目】
59. Zhang, B., Zhang, B., Jiang, C., Shi, M., Wang, X., Zhu, Z., Zhou, J., & Lu, J. (2026). *Syll: Open-Source Personal Automation with Cross-Surface Execution.* arXiv:2606.07594v1. https://arxiv.org/abs/2606.07594 ｜【已读原文】
60. Bastos (2026). *ORBITA: An automation recommendation framework based on Task Mining and Large Language Models.* RCMOS, 1(1). DOI 10.51473/rcmos.v1i1.2026.2199. https://doi.org/10.51473/rcmos.v1i1.2026.2199 ｜【仅核书目；venue 可信度低，未验证同行评审】
61. AutoDroid (2023), arXiv:2308.15272v4；VASTA (2019), arXiv:1911.01474v1；A Survey on (M)LLM-Based GUI Agents (2025), arXiv:2504.13865v2 ｜【已读原文（摘要）】

---

**核不到的清单（重复 §0.2 与 §4 的关键项，便于后续直接补）**
- Microsoft Process Advisor / UiPath Task Mining / Celonis Task Mining 的**方法论论文与评测**：核不到。
- Weinzierl et al. 2021 的**摘要与算法**：核不到（Crossref 无 abstract；tandfonline 无 abstract 段）。
- Leno et al. 2020 的**切分算法**、de Leoni et al. 2025 的**聚类目标函数**、van der Waal et al. 2022 的**谓词集合**、Outmazgin & Soffer 2013 的**可/不可检测清单**：均**只有摘要或只有书目**，正文核不到。
- 任何"单用户、无真值、零打扰"端到端机会挖掘的**成功率/误报率**：核不到。
- dblp.org 交叉验证：被 Anubis 反爬拦截，核不到。
