# 08a · HCI「中断管理 / 可打断性」判据调研

> 分区：HCI 中断管理（interruption management）与可打断性（interruptibility）预测。
> 交付对象：`src/openlookout/sprite/proactive/timing.py`（开口时机判据与阈值）及其兄弟 `help.py`（冷却参数）。
> 起因：`docs/strategy/_recon/08c-proactive-agent-era.md:434-438` 明写「如需『冷却』的显式形式化，本分区@不到，属 HCI/在线算法分区」——本报告就是被点名的那次跨分区补课。
> 一句话结论：文献能背书的是**判据的形状**（期望效用 + 断点 + 「能否/愿否接受」与「需不需要」分两轴），背书不了我们**任何一个具体阈值数字**；而「冷却」在 HCI 里确实没有独立的形式化，只有 intervention fatigue / user burden 这一类名字。

---

## 0. 核实口径

先读这一节，它决定后面每条结论的可信度。

### 0.1 本机检索环境的限制（为什么有些条目停在「摘要级」）

- 本会话 `web_search` 无 API key（不可用）；`web_fetch` 把外部域名误判为内网并拒绝。改用 `curl.exe` / python `urllib` 直连。
- **可用**的通道：arXiv 官方 API、Crossref API、OpenAlex API、Semantic Scholar API、Unpaywall API、PMC（Europe PMC 抽取文本）、部分高校/作者主页的 PDF。
- **实测不可用于学术检索的通道**（已记录，勿重试）：`lite.duckduckgo.com` 返回 HTTP 202 人机验证页且不含结果；`www.bing.com/search` 返回 HTTP 200 但结果与查询**完全无关**（与 `docs/strategy/_recon/08b-online-algorithms.md:11` 的记载一致）；`search.marginalia.nu` 需 JS，只回导航链接；Brave 429、Ecosia 403、Mojeek 403、CiteSeerX 429、`html.duckduckgo.com` SSL EOF。
- `dl.acm.org/doi/...` 与 `/doi/pdf/...` 一律 **403**（本机无订阅）。
- **决定性的负面结论**：用 Unpaywall 逐条判定，本报告涉及的 8 篇 ACM 论文 —— Horvitz CHI 1999、Fogarty CHI 2003、Fogarty TOCHI 2005、Adamczyk & Bailey CHI 2004、Mark 等 CHI 2005、Iqbal & Horvitz CHI 2007、Iqbal & Bailey CHI 2007、Iqbal & Bailey CHI 2008 —— **全部 `is_oa=false` 且无任何 OA location**，即不存在合法开放全文。作者主页与存档也已逐个试过并失败：`shamsiqbal.com` 无 Wayback 快照，`brianpbailey.com`、`bailey.cs.illinois.edu` SSL EOF，MSR 旧 publication URL 404，`ics.uci.edu/~gmark/` 目录页仅 319 字节且后续请求被限流 403。
- 因此本报告对这部分论文的可信度上限是**官方摘要原文**（OpenAlex `abstract_inverted_index` 重建），若只得到「作者/会议/页码/DOI」则标【仅核书目】，绝不把转述当原文。

### 0.2 可信度标注（沿用 08b 三档口径，另加一档子类）

| 标注 | 含义 | 本报告对应 | 能拿它干什么 |
| --- | --- | --- | --- |
| 【已读原文】 | 拿到**全文**（PDF/HTML/PMC 抽取文本）并逐字读过 | Horvitz CHI 1999、Horvitz 等 UAI 1999、Iqbal & Bailey CHI 2006、Mark 等 CHI 2008、Fogarty TOCHI 2005、Nahum-Shani 等 JITAI 2018、Trella 等 npj 2026、Ho 等 Quick Question、本机 `timing.py` 源码、4 个账本 | 可直接引用数字 |
| 【已读原文·摘要级】 | 只读到**官方摘要原文**，正文未获 | Adamczyk & Bailey CHI 2004、Mark 等 CHI 2005、Iqbal & Horvitz CHI 2007、Iqbal & Bailey CHI 2007、Iqbal & Bailey CHI 2008、Fogarty CHI 2003 | 可引用其**主张方向**，不可引用具体数字 |
| 【仅核书目】 | 只核到 title/作者/venue/年份/页码/DOI | 上述各篇的书目信息 | 只能用于定位，不能用于支撑论断 |
| 【未核实】 | 追不到出处，或只在二手转述里见过 | 见 §4.2 | 不要写进设计依据 |

正文里**「我的推断」一律单独成行并与「原文陈述」分列**。

---

## 1. 逐篇卡片

每张卡：**出处** → **机制** → **关键数字** → **免训练与否** → **对我们 harness 的可用性**。

### A. Horvitz — Principles of Mixed-Initiative User Interfaces（CHI 1999）

**出处**：Eric Horvitz，CHI '99，pp.159-166，DOI `10.1145/302979.303030`。【仅核书目】+【已读原文】（本机抽取文本 `tmp_lit/08a_hci/horvitz_chi99.txt`；Crossref 核到书目，正文来自文本抽取）。

**机制（原文，逐字）**：把「要不要开口」写成期望效用比较。四种结果的效用 `u(A,G)`（行动且用户需要）、`u(A,¬G)`（行动但用户不需要）、`u(¬A,G)`（沉默但用户需要）、`u(¬A,¬G)`（沉默且不需要）被映射到 0-1 尺度：

```
Eq.(1)  eu(A|E)  = p(G|E)·u(A,G) + p(¬G|E)·u(A,¬G)
Eq.(2)  eu(A|E)  = p(G|E)·u(A,G) + [1-p(G|E)]·u(A,¬G)
Eq.(3)  eu(¬A|E) = p(G|E)·u(¬A,G) + [1-p(G|E)]·u(¬A,¬G)
```

（分别位于 `horvitz_chi99.txt` 行 421-422 / 426 / 447。）阈值 `p*` 由令 Eq.(2)=Eq.(3) 解出：**当 `p(G|E) > p*` 才行动**。原文强调 `u(A,¬G)` 的值受用户注意力状态影响甚大（行 482-489）：用户专注越深，不需要的行动的效用越低。

**关键数字**：无常数阈值。`p*` 是**四效用的函数**，论文没有给出任何固定数字。

**免训练与否**：框架本身免训练；但 `p(G|E)` 需要估计（论文用的是贝叶斯网络）。

**对我们的可用性（高）**：`timing.py` 的 docstring 已经写着 `V(开口) − V(沉默) = 关联度 × 时效 × 可撤回性 − 打扰代价`——**这就是 Horvitz 期望效用框架的一个工程化实例**。本报告为它补上文献源头，并指出两处差异：
- 我们用**加权乘积 + 减项**代替 p 与 u 的显式分解，`p*` 被替换成常数 `V_SILENCE = 0.25`。**这个 0.25 没有文献对应**（见 §4.1）。
- Horvitz 明确说误打断的代价随用户**专注深度**上升；我们目前只有 `busy`（事件率）一个粗代理，没有"专注深度"。

> 我的推断（非原文）：把 `reversibility` 看成 `u(A,¬G)` 的一个自变量是自洽的（越可撤回的行动，误伤成本越低），但 **Horvitz 原文没有这样分解**，我们把它写成乘法因子属于自造形式。

### B. Horvitz, Jacobs, Hovel — Attention-Sensitive Alerting（UAI 1999）

**出处**：UAI 1999，p.305 起，arXiv:`1301.6707`（arXiv 版收录的就是 UAI 1999 本文）。【已读原文】摘要段 +【仅核书目】。

**机制**：PRIORITIES 系统。摘要逐字："utility-directed procedures for mediating the flow of potentially distracting alerts and communications to computer users"；"balance the **context-sensitive costs of deferring alerts** with the **cost of interruption**"；"inferring the expected criticality of email"。

**关键数字**：摘要无数字。

**免训练与否**：需要内容推断（criticality），非纯计数。

**对我们的可用性（中）**：它给了我们**「延迟的代价」与「打断的代价」必须同时出现在同一个目标里**这个形式要求。`timing.py` 的 `−disturbance` 只建模了打断代价，**没有建模延迟代价**（即"现在不说，这条信息晚点给还有没有价值"）。`recency = exp(-age/TAU_S)` 是我们对"时效"唯一的近似。

### C. Iqbal & Bailey — Leveraging Characteristics of Task Structure to Predict the Cost of Interruption（CHI 2006）

**出处**：CHI 2006，pp.741-750，DOI `10.1145/1124772.1124882`，开放绿版 PDF：`https://www.ideals.illinois.edu/items/11122/bitstreams/40961/data.pdf`。【已读原文】（`tmp_lit/08a_hci/iqbal_bailey_chi06.txt`）。

**机制**：中断代价（COI）的**客观代理量 = resumption lag**（被打断后恢复到打断前任务状态的耗时）。候选预测因子是任务结构的若干特征，最后用逐步回归 + K-means 分三档 + MLP 分类。

**关键数字（原文）**：
- 全因子回归 `F(12,336)=11.23, p<0.0001`，`adjusted R²=0.25`；stepwise 后保留**三个因子**：Level / Carry Over / Difficulty of Next Subtask，`adjusted R²=0.26`（原文措辞："26% of the variance in Resumption Lag"）。
- 三因子系数：Level `0.38 (t=5.581, p=0.0001)`、Carry Over `0.158 (t=2.351, p=0.019)`、Difficulty of Next Subtask `0.077 (t=2.063, p=0.040)`、常数 `6.197`。原文自认这只是 a **modest** correlation coefficient。
- K-means 三簇（resumption lag，秒）：COI_Low `n=75, M=5.938, SD=0.612`；COI_Medium `n=177, M=7.252, SD=0.376`；COI_High `n=85, M=8.628, SD=0.505`；两两 ANOVA `p<.0001`。
- MLP（1 隐层 3 输出）10 折交叉验证正确率 **63.2%**（chance 33%，`p<.0001`）；最严重的错误（把 COI_Low 预测成 COI_High）占 **4.7%**。
- 引 [14]：a user's interruptibility could be best classified into at most **3 classes**。
- 子任务难度分 6 级（Table 1：1 = Motor movements 最轻 … 6 = Mathematical reasoning 最重）。

**免训练与否**：Level / Carry Over / Difficulty 这三个因子在**实验室任务**里需要任务结构信息，不是免训练的；但它证明了一件对我们更要紧的事——**这类预测的准确率天花板很低**（R²≈0.26，三分类 63.2%）。

**对我们的可用性（高，且是"降期望"的那种有用）**：这条给本项目的价值不是拿来算，而是**校准我们的承诺**。文献里最认真做的实验室模型也只到 63.2% 三分类、R²=0.26。因此 `timing.py` 承诺"避开最坏"是诚实的，承诺"精确识别好时机"是过度的。**最多分 3 档**这一点也被引文佐证。

### D. Iqbal & Bailey — Detecting and Differentiating Breakpoints（CHI 2007）

**出处**：CHI 2007，pp.697-706，DOI `10.1145/1240624.1240732`（OpenAlex 引用 98 / S2 引用 107）。【已读原文·摘要级】+【仅核书目】。正文 Unpaywall 判定 closed，无 OA。

**机制**：不识别底层任务，只从交互行为里检测 **perceptually meaningful breakpoints**，并**区分三种粒度（three types）**。生态采样 + 观察者看录像标注 breakpoint 作为标定。

**关键数字**：摘要只说模型"detect and differentiate breakpoints with **reasonably high accuracy**"，**无具体数字**。

**免训练与否**：原文未给；摘要强调"不需要识别底层任务"这一点，与我们"只看账本不看任务语义"的立场一致。

**对我们的可用性（中高）**：这是我们 `action_boundary` 触发（`type ∈ ACTION_TYPES`）的**直接思想祖先**：用操作边界当断点，而不是去理解用户在干什么。它同样支持「断点分三类」这一粒度上限。

### E. Iqbal & Bailey — Effects of Intelligent Notification Management（CHI 2008）

**出处**：CHI 2008，pp.93-102，DOI `10.1145/1357054.1357070`（OpenAlex 引用 195 / S2 引用 236）。【已读原文·摘要级】+【仅核书目】。closed。

**机制**：两个实验，把通知**推迟到断点（defer-to-breakpoint）**再投递。

**关键数字（摘要原文措辞）**：研究一：模型"detect breakpoints **reasonably well**, but **struggle to differentiate their type**"；研究二："scheduling notifications at breakpoints **reduces frustration and reaction time** relative to delivering them immediately"；并指出通知内容的**相关性**决定应在**哪一类**断点投递。

**对我们的可用性（高，两条）**：
1. **"推迟到断点"确实降低了 frustration 与反应时"** —— 这是我们 `SETTLE_S`（稳定 6 s 才开口）+ action_boundary 策略的**唯一同向实证**（摘要级）。
2. 内容相关性 × 断点类型是**交互项** —— 对应我们的 `RELATEDNESS` 表。原文只说了这个方向，**没有给任何数值**，我们的 `{"file_save":1.00,"clipboard":0.95,"file_open":0.90,"focus":0.60}` 全部是自造（见 §4.1）。

### F. Iqbal & Horvitz — Disruption and Recovery of Computing Tasks（CHI 2007）

**出处**：CHI 2007，pp.677-686，DOI `10.1145/1240624.1240730`（OpenAlex 引用 298 / S2 引用 366）。【已读原文·摘要级】+【仅核书目】。closed。

**机制**：多任务行为的**现场研究**（field study），聚焦任务的 **suspension 与 resumption**；用工具记录用户与软件应用及其窗口的交互，以及来信的 IM/邮件提醒。

**关键数字**：**未能获得**（本次检索未取到任何数字）。

**对我们的可用性（高，方法论对标）**：这是与我们场景最像的一篇——**同一台机器上的被动日志 + 任务挂起/恢复**。这使得"用 `operations.jsonl` 算 resumption 量"有了直接的方法学先例（但具体数字我核不到，见 §4.2）。

### G. Adamczyk & Bailey — If Not Now, When?（CHI 2004）

**出处**：CHI 2004，pp.271-278，DOI `10.1145/985692.985727`（OpenAlex 引用 531 / S2 引用 646）。【已读原文·摘要级】+【仅核书目】。closed。

**机制**：测量在任务执行中**不同时刻**打断在 **task performance、emotional state、social attribution** 三方面的影响；用 event perception 技术先建任务模型，再按预测认知负荷挑打断时刻。

**关键数字（摘要原文措辞）**：结论是不同打断时刻在**情绪状态与正向社会归因**上有差异。**摘要并未声称任务绩效有差异**。

**对我们的可用性（中）**：与 E 同向（"更好/更差的时机确实存在，但影响落在情绪与归因上"）。同时提醒：**把我们自己的"时机好坏"直接说成效率差异是超出原文的**。

### H. Mark, Gudith, Klocke — The Cost of Interrupted Work: More Speed and Stress（CHI 2008）

**出处**：CHI 2008，DOI `10.1145/1357054.1357072`；PDF 取自 `https://ics.uci.edu/~gmark/chi08-mark.pdf`。【已读原文】（`tmp_lit/08a_hci/mark_chi08.txt`，pypdf 抽取 4 页）。

**机制**：3×2 被试内实验，48 名被试（81% 德国大学生，平均年龄 26），中断频率为**每 2 分钟**一次（Baseline / Same-context / Different-context 三条件）。测完成时间、错误数、邮件质量、主观量表。

**关键数字（原文）**：
- **核心反直觉结论：被中断反而更快完成。** Time to perform task（分钟，SD）：Baseline **22.77 (7.60)**、Same-context **20.31 (5.94)**、Different-context **20.60 (4.93)**；`F(2,77.98)=3.36, p<.05`；成对 B vs S `F(1,46)=4.22, p<.05`，B vs D `F(1,46)=4.13, p<.05`，**S vs D 无显著差异**。
- 错误数无差异 `F(2,92)=1.70, p<.19`；礼貌度无差异；邮件字数 B 31.49 / S 29.17 / D 30.16，`F(2,92)=3.34, p<.04`。
- **代价转移到主观负荷**（1-20 量表）：Stress B 6.92(3.85) / S 9.46(3.97) / D 9.13(4.10)；Mental workload B 10.02(3.90) / S 10.83(3.96) / D 11.50(3.55)，`F(2,92)=3.82, p<.03`；Frustration B 4.73 / S 6.63 / D 6.48；Time pressure B 11.02 / S 12.69 / D 12.17；Effort B 9.50 / S 11.04 / D 11.52。
- 人格预测中断代价：openness to experience `β=-.363, t=-2.22, p=.03`；need for personal structure `β=-.346, t=-2.13, p=.04`；`F(2,47)=3.41, p<.04, R²=.14`。
- 媒介（电话 vs IM）无差异。
- **诚实点：该文没有报告"恢复要 23 分钟"**（见 §4.2 第 2 条）。

**免训练与否**：不涉及免训练模型；它是一篇"代价究竟落在哪里"的实证。

**对我们的可用性（高，且是警告）**：
1. 我们的 docstring 里 `V(开口) − V(沉默)` 隐含"沉默省时间"。Mark 2008 说**时间上被打断并不更慢**，代价落在 stress / mental workload / frustration。所以我们的目标函数若要贴实证，**收益项不该是"省时间"，而是"减少主观负荷，或者说错话的代价"**。
2. 同/异上下文**无差异**——对我们是负结果：`timing.py` 里没有任何"跨应用上下文切换"的惩罚项，这**反而与实证一致**，不要再去加。
3. **每 2 分钟一次**这个频率对本机不可能，但它说明"高频繁扰"是可以被做实验的；我们真正要防的是长期 burden（见 K/L）。

### I. Mark, González, Harris — No Task Left Behind?（CHI 2005）+ 「23 分钟」神话

**出处**：CHI 2005，DOI `10.1145/1054972.1055017`（OpenAlex 引用 500 / S2 引用 570）。【已读原文·摘要级】+【仅核书目】。closed，正文核不到。

**机制**：24 名 information worker 的详细观察研究（working spheres / 碎片化与恢复）。

**关键数字（摘要原文措辞）**：工作高度碎片化，**57% 的 working spheres 被打断**；内部打断多来自个人事务、外部打断多来自核心工作；多数被打断的工作当天恢复，但**恢复前平均隔着多于两个中间活动**——原文是 "more than two **intervening activities** occur before it is"，**以活动计数，不是秒数**。

**对我们的可用性（中）**：`operations.jsonl` 的 `ts` 一样可以算"中间活动数"。**用活动计数比用秒数更接近这篇的原意**（见 §3）。

### J. Fogarty 等 — Predicting Human Interruptibility with Sensors（TOCHI 2005 / CHI 2003）

**出处**：TOCHI 2005, 12(1):119-146，DOI `10.1145/1057237.1057243`；作者 James Fogarty, Scott E. Hudson, Christopher G. Atkeson, Daniel Avrahami, Jodi Forlizzi, Sara Kiesler, Johnny C. Lee, Jie Yang（CMU HCII）。CHI 2003 版 pp.257-264，DOI `10.1145/642611.642657`。【已读原文】TOCHI 2005（`tmp_lit/08a_hci/fogarty_tochi2005.txt`）+【已读原文·摘要级】CHI 2003。

**机制**：在一个真实办公室里录工作日（**7am–6pm**）的音视频，用 ESM（经验采样）让人自报可打断性；再把音视频**人工编码成模拟传感器值**，用决策树 / 朴素贝叶斯预测"是否 Highly Non-Interruptible"。特征命名法是 `Sensor(Statistic-Window)`。

**关键数字（原文）**：
- 4 名被试的办公室；ESM 平均**每小时两次**；**672 份可打断性自报**（587 份有可用录像；54 份被试听到提示未回应）；**40 名 estimator 被试**付费看录像做人工判断。
- 人工估计（"Highly Non-Interruptible vs 其他"）准确率 **76.9%**（`χ²(1,4800)=1.01, p>.31`），与 **68% 的 chance 基线无显著差异**。
- 基于人工模拟传感器的决策树（wrapper 特征选择）：**82.4%**（`χ²(1,1344)=37.56, p<.001`；显著优于 estimator 被试 `χ²(1,3072)=9.51, p<.01`；混淆矩阵 413 / 61.5%、44 / 6.5%、74 / 11.0%、141 / 21.0%）。
- 同 10 个特征的朴素贝叶斯：**81.25%**。
- "Easy to Build" 5 传感器子集：朴素贝叶斯 **78.9%**、决策树 **79.2%**（混淆 396 / 58.9%、61 / 9.1%、79 / 11.8%、136 / 20.2%）。
- 特征实例：`AnyTalk(Imm)`、`AnyTalk(Count-30)`、`AnyTalk(Net-120)`、`Telephone(All-30)`、`Telephone(All-120)`、`Mouse(Imm)`、`Mouse(All-120)`、`Mouse(Change-30)`、`Mouse(Net-60)`、`Desk(Change-120)`、`Monitor(Any-300)`、`Writing(Count-30)`、`Writing(Count-60)`、`Papers(Count-300)`、`TimeofDay(HourOnly)`。
- 原文："if allowed to use only **one** sensor, a sensor related to **talking or the telephone** is the most useful"。estimator 被试觉得 **15 s** 录像已够，30 s 并未提高准确率。
- CHI 2003 版摘要：模型整体准确率"**about 78%**"；"a model tuned to avoiding unwanted interruptions does so for **90%** of its predictions, while retaining **75%** overall accuracy"。

**免训练与否**：统计量（Imm/Count-N/All-N/Net-N/Change-N/Any-N）**全部是免训练的计数**，只有分类器要训。**但必须诚实**：这些"传感器"多是**人工看录像编码出来的模拟值**，不是装机硬件。所以 82.4% **不能**读成"真实装机日志也能到 82%"。

**对我们的可用性（最高）**：见 §3 第 1 条。这套 `Sensor(Statistic-Window)` 是我们账本特征工程的**现成词汇表**，而且窗口 30/60/120/300 s 与我们 `WINDOW_S=90` 是同一量级。

### K. Nahum-Shani 等 — Just-in-Time Adaptive Interventions（JITAI）

**出处**：Annals of Behavioral Medicine 52(6):446-462，DOI `10.1007/s12160-016-9830-8`，PMC5364076。【已读原文】（`tmp_lit/08a_hci/jitai_abm2018.txt`）。

**机制（原文，逐字）**：JITAI 六要素 = distal outcome / proximal outcomes / **decision points** / intervention options / **tailoring variables** / **decision rules**。
- decision point："A decision point is a time at which an intervention decision is made."
- **State of vulnerability/opportunity**："A period of susceptibility to negative health outcomes (vulnerability) or to positive health behavior changes (opportunity)"。
- **Receptivity**："the individual's **transient ability and/or willingness** to receive, process, and utilize just-in-time support; receptivity is a function of both **internal (e.g., mood)** and **contextual (e.g., location)** factors"；"Receptivity might change rapidly in the course of a day"；"if a person is in a meeting s/he might be receptive to an intervention delivered via a **text message**, but not receptive to a **phone call**"。
- **Decision rules**："A way to operationalize the adaptation by specifying **which intervention option to offer, for whom, and when** (i.e., under which experiences/contexts)"。Table 2 给示例决策规则。
- Intervention fatigue (i.e., burnout)："a state of emotional or cognitive weariness associated with intervention engagement"；引 Heckman 等，把 intervention fatigue 概念化为随 **intervention burden**（"the demands of an intervention in terms of time and effort"）、个体日常负荷、个体资源容量（注意力、情绪）与 illness burden **交互**而波动的心智/情绪状态。

**关键数字**：无（框架性论文）。

**免训练与否**：decision rule 形式（if-then）天然免训练。

**对我们的可用性（高，且直接回答 §4.2 第 3 条）**：JITAI 把"需不需要（vulnerability/opportunity）"和"能不能/愿不愿接收（receptivity）"**分节、分别定义**——这是把二者当**两个不同来源的量**的文献依据。**但原文从未把它写成"独立的一轴"**；该说法是我的归纳。

### L. Trella 等 — 在线 AI 决策算法的监控（npj Digital Medicine 2026）

**出处**：Trella, Ghosh, …, Nahum-Shani, Murphy,"Effective monitoring of online AI decision-making algorithms in just-in-time adaptive interventions"，npj Digital Medicine，DOI `10.1038/s41746-026-02669-4`，PMC13518862。【已读原文】（`tmp_lit/08a_hci/jitai_npj2026.txt`）。

**机制**：给在线自适应算法做**运行期健康监控**：红/黄/绿三级严重度，越级则触发 fallback methods（预置备份日程、`p=0.5` 随机、剔除坏数据、沿用最近一次决策规则）。案例是 Oralytics（NCT05624489，79 人）与 MiWaves（NCT05824754，122 人）。

**对我们的可用性（中高）**：这是"我们怎么知道 timing 判据没跑坏"的现成模板——但我们**目前没有任何 outcome 数据**（`outcomes.jsonl` 为 0 字节），所以只能先落地"红黄绿 + fallback"，暂时无法验证 fallback 是否触发得对。

### M. Ho 等 — Quick Question: Interrupting Users for Microtasks with RL

**出处**：arXiv:`2007.09515v1` [cs.HC]，2020-07-18；发表于 2nd Workshop on Human in the Loop Learning (HiLL), ICML 2020, virtual。【已读原文】（`tmp_lit/08a_hci/ho_quickquestion.txt`）。

**机制**：把"什么时候向用户推微任务"建成 MDP，动作 = {notify, stay silent}；用户回应 = 正奖励，忽略 = 负奖励；算法 **A2C（Advantage Actor Critic）**，**每个用户单独训练一个 agent**；与监督学习基线对比（SL 收到的回应数更高）。

**关键数字**：**5 周用户研究、30 名被试**；其余数字未在本轮抽取中确认。

**免训练与否**：**要训练**（每用户一个 agent），且需要用户逐次反馈——我们目前**没有**这个反馈回路。

**对我们的可用性（低，当下）**：方向对（"什么时候开口"当成序贯决策），但它需要每用户训练 + 大量反馈样本。在 `offers.jsonl` 只有 298 行、`outcomes.jsonl` 为空的前提下，**这条路现在走不通**；它更适合作为"等我们有了反馈闭环之后的下一步"。

---

## 2. 汇总表

### 2.1 判据 × 证据 × 可算性

| # | 判据 | 出处 | 关键实测数字 | 免训练? | 本机账本可算? |
| --- | --- | --- | --- | --- | --- |
| 1 | 期望效用比较（`V(开口) − V(沉默)`，阈值 `p*`） | Horvitz CHI 1999 §A【已读原文】 | 无常数阈值；`p*` 是四效用函数 | ✅ 框架免训练 | ✅ `timing.py` 已实现为 `score > V_SILENCE` |
| 2 | 误打断代价随**专注深度**上升 | Horvitz CHI 1999 §A【已读原文】 | — | ✅ | ⚠️ 只有 `busy`（10 s 内 ≥5 事件）当粗代理 |
| 3 | 延迟代价与打断代价同处一个目标 | Horvitz 等 UAI 1999 §B【已读原文】 | — | 需内容推断 | ❌ 我们**没有**延迟代价项 |
| 4 | 操作边界当断点（action boundary） | Iqbal & Bailey CHI 2006/2007 §C/§D【已读原文/摘要级】 | — | ✅ | ✅ `type ∈ {file_save, clipboard, file_open}`，`timing.py` 已用 |
| 5 | 断点/可打断性**最多分 3 类** | Iqbal & Bailey 2006 引 [14] §C；2007 三类断点 §D【已读原文】 | 三分类 CV **63.2%**，chance 33% | ✅ | ✅ 建议不做 >3 档 |
| 6 | 推迟到断点可降 frustration 与反应时 | Iqbal & Bailey CHI 2008 §E【摘要级】 | 无数字 | ✅ | ✅ 我们的 `SETTLE_S` 就是它 |
| 7 | 内容相关性 × 断点类型是交互项 | Iqbal & Bailey CHI 2008 §E【摘要级】 | 无数字 | ✅ | ⚠️ `RELATEDNESS` 表方向对、**数值自造** |
| 8 | 不同时机在情绪/社会归因上有差异 | Adamczyk & Bailey CHI 2004 §G【摘要级】 | 无数字；**摘要未称绩效有差异** | ✅ | ⚠️ 只能支持方向 |
| 9 | resumption lag 作为中断代价代理 | Iqbal & Bailey CHI 2006 §C【已读原文】 | K-means 三簇 M=5.938 / 7.252 / 8.628 s | ✅ | ✅ 见 §2.2 的"返回延迟" |
| 10 | 中间**活动数**（非秒数）衡量恢复延迟 | Mark 等 CHI 2005 §I【摘要级】 | 57% working spheres 被打断；恢复前 >2 个中间活动 | ✅ | ✅ 可用 `ts` 数中间 focus 事件 |
| 11 | 中断的时间代价 ≈ 0，代价在主观负荷 | Mark 等 CHI 2008 §H【已读原文】 | B 22.77 vs S 20.31 vs D 20.60 分钟（更快）；stress 6.92→9.46 | 不适用 | ❌ 本机无主观量表 |
| 12 | 同/异上下文**无**差异 | Mark 等 CHI 2008 §H【已读原文】 | S vs D 不显著 | 不适用 | ✅ 支持我们不设该项 |
| 13 | 装机传感器预测可打断性 | Fogarty TOCHI 2005 §J【已读原文】 | 决策树 **82.4%**、NB 81.25%、Easy-to-Build 79.2%/78.9%；chance **68%** | 统计量免训练 | ⚠️ 我们无麦克风/电话；且原文传感器是**人工模拟** |
| 14 | `Sensor(Statistic-Window)` 特征命名法 | Fogarty TOCHI 2005 §J【已读原文】 | 窗口 30/60/120/300 s | ✅ | ✅ **可直接搬**，见 §3 |
| 15 | 可打断性 ≠ 需要（receptivity 与 vulnerability 分列） | JITAI 2018 §K【已读原文】 | — | ✅ | ✅ 用 `offers.jsonl` 应答延迟 |
| 16 | intervention fatigue / burden（"冷却"的真名） | JITAI 2018 §K【已读原文】 | — | ✅ 概念 | ⚠️ 无现成可观测量；`REPEAT_*` 是占位 |
| 17 | 决策规则 = 给谁、给什么、何时给 | JITAI 2018 §K【已读原文】 | — | ✅ | ✅ 与 `timing.py` 四种触发同构 |
| 18 | 红黄绿 + fallback 的在线监控 | Trella 等 npj 2026 §L【已读原文】 | — | ✅ | ❌ 缺 outcome 数据 |

### 2.2 四个账本 → 判据的字段级映射（免训练可算量）

本机 4 个账本（`E:\OpenLookout\sprite_home\perceive\`）本轮**只读**统计结果如下（脚本 `tmp_lit/08a_hci/ledger.py`、`ledger2.py`；未写入、未启停进程）：

| 账本 | 行数 / 字节 | 起作用的字段 | 本轮实测 |
| --- | --- | --- | --- |
| `operations.jsonl` | 2261 / 326408 | `ts` `type` `app` `title` `dur_s`（另有 `dst_app`/`dst_title`/`hash`/`len`/`path`/`src_app`/`src_title`） | type: focus 2196 / file_save 44 / clipboard 20 / file_open 1；20 个 app |
| `offers.jsonl` | 298 / 130567 | `t` `t_answer` `id` `kind` `result` `confidence` `text` `action` `error` | result: shown 198 / auto_started 54 / auto_failed 36 / auto_completed 9 / retracted 1 |
| `decisions.jsonl` | 383 / 195834 | `t` `kind` `intent` `confidence` `decision` `state` `policy` | (quiet,conversation) 139 / (offer,None) 84 / (quiet,outcome) 83 … |
| `timing.jsonl` | 21 / 10547 | `score` `s_now` `s_max` `busy_n` `kind` `fire` `since_last_event_s` … | fire=true 6 / false 15；busy=true **0**；settled=true 16 |

**哪些文献判据可以直接映射成用这些字段算出来的量**（用户问题 2 的核心）：

| 文献量 | 本机可算定义（只用上表字段） | 本轮实测值 |
| --- | --- | --- |
| **返回延迟 / resumption lag**（§C 逐字：resumption lag 是 COI 的代理量） | 离开 app A 后，`ts` 上**下一次** `type=focus` 且 `app=A` 的时间差 | n=376；p25 **4.0 s**、中位 **22.0 s**、p75 85.0 s、p90 335.0 s、max 5407 s（用户 brief 记的中位 21 s 与此一致） |
| **区间驻留（streak dwell）** | 同一 `app` 连续 `focus` 段的 `ts` 跨度 | n=395；p25 2 s、中位 **6 s**、p75 23 s、p90 64 s、max 541 s |
| **断点密度 / 事件率**（§J 的 `Count-N` 族） | 任意 30/60/120/300 s 窗内 `focus`+`clipboard`+`file_save`+`file_open` 计数 | 相邻 `focus` 间隔中位 **1.0 s**、p90 8 s、max 152 s；>60 s 仅 **9 次（0.4%）** |
| **操作边界**（§D） | `type ∈ {file_save, clipboard, file_open}` 的时刻 | 共 65 次 |
| **中间活动数**（§I，原文口径） | 返回 app A 之前夹在中间的 `focus` 事件个数 | 可算（本轮未统计） |
| **receptivity（应答延迟）**（§K "transient ability and/or willingness"） | `offers.jsonl` 的 `t_answer − t` | n=100；中位 **1.9 s**、p75 **85.7 s**、p90 133.6 s、max 326.0 s |
| **`dur_s` 的可靠性** | — | n=2196；中位 **0.0**、p90 8、max 60；**零值 1671（76%）**、<5 s 共 1928（88%）→ **该字段目前基本无信息量，不要当真值用** |

**必须承认的样本限制**：`operations.jsonl` 的 focus 事件按小时分布为 7 点 867、8 点 1114、9 点 209、10 点 6 —— **整个日志只覆盖约 3 小时**（07–10 点），单一被试本机，20 个 app。Fogarty 是 4 人 × 工作日 7am–6pm；我们比它小一到两个数量级。

---

## 3. 对我们最有用的 3 条

### 第 1 条：把 Fogarty 的 `Sensor(Statistic-Window)` 当成我们账本特征工程的现成词汇表

**依据**：§J【已读原文】。Fogarty 用 `Sensor(统计量-窗口)` 命名法枚举特征（`AnyTalk(Imm)`、`Mouse(Change-30)`、`Writing(Count-60)`、`Monitor(Any-300)`…），统计量只有 Imm / Count-N / All-N / Net-N / Change-N / Any-N 六种，窗口只有 30/60/120/300 s 四档，**全部免训练**。

**行动**：把 `operations.jsonl` 能产出的特征按同一命名法列全，例如 `Focus(Count-30)`、`Focus(Change-60)`、`Action(Count-90)`、`FileSave(Net-300)`、`App(Change-120)`、`Idle(Any-60)`、`TimeOfDay(HourOnly)`。然后**对照现状**：`timing.py` 目前只用了「WINDOW_S=90 内的类型计数 + 相邻 app 变更 + settle + 4 s 边界」这四五种量，属于这张表里极小的一角。**这一步不需要任何文献数字，只需要文献的命名法**，而且它把"我们还能算什么"从灵感问题变成填表问题。

### 第 2 条：接受实证上界——不要承诺精细判别，只承诺避开最坏；同时把代价项从"时间"改成"负荷"

**依据**：§C【已读原文】最认真的实验室模型也只有三分类 **63.2%**、`R²=0.26`；§J 82.4% 的上界是在**人工模拟传感器**上得到的，且 chance 基线已有 68%；§E【摘要级】说推迟到断点能降低 frustration 与反应时，但**没有数字**。§H【已读原文】更狠：被打断**花的时间更少**（22.77 → 20.31 / 20.60 分钟），代价落在 stress（6.92 → 9.46）与 mental workload 上，而且同/异上下文**无差异**。

**行动**：(a) 在文档里把 `timing.py` 的定位写成"避开最坏时机"而不是"识别最佳时机"，并明确最多 3 档；(b) 收益项（`V(沉默)`）不要写成"省时间"，改成"少打扰 / 少致负荷"——这直接对应 §H 的实证；(c) **不要**再去加"跨应用上下文"惩罚项，§H 的 S vs D 不显著不支持它。

### 第 3 条：把 receptivity 从 need 里拆出来，用 `t_answer − t` 当它的本机可观测量；并把「冷却」正名为 intervention fatigue / burden

**依据**：§K【已读原文】—— JITAI 把 "state of vulnerability/opportunity"（需要）与 "receptivity"（transient ability and/or willingness）**分节定义**，并明说 receptivity 由 internal（mood）与 contextual（location）因素决定、可在一天内快速变化；同一段还给了"开会时能收短信、但不能接电话"的例子。同一篇里 intervention fatigue / burden 是"冷却"在文献里**唯一**的形式化入口。

**行动**：(a) 承认"时机合适"（need/opportunity）与"用户此刻愿接"是**两个量**，后者在本机的直接代理就是 `offers.jsonl` 的 `t_answer − t`（本轮实测中位 **1.9 s**、p75 **85.7 s**，n=100）——**注意 p75 与中位差 45 倍，说明"除了秒回的人，还有一大批人很晚才答"，这正是 receptivity 的分布**；(b) 把 `REPEAT_HARD_S=180` / `REPEAT_COOLDOWN_S=900` / `help.py` 的 `OFFER_COOLDOWN_S=300` / `COMPANION_COOLDOWN_S=600` 在文档里**从"冷却模块"改写成"intervention burden 的工程近似"**，并删掉任何"冷却是一套独立机制"的暗示。

---

## 4. 这份调研证明不了什么

### 4.1 结构性限制

1. **证明不了我们任何一个阈值。** `WINDOW_S=90.0`、`SETTLE_S=6.0`、`BUSY_S=10.0`、`BUSY_N=5`、`TAU_S=45.0`、`THETA_HI=9.0`、`THETA_TRANS=7.0`、`BACKLOG_N=40`、`REPEAT_HARD_S=180.0`、`REPEAT_COOLDOWN_S=900.0`、`SMOOTH=0.5`、`BACKLOG_APPS=3`、`V_SILENCE=0.25`、`BUSY_PENALTY=0.35`、`REPEAT_PENALTY=0.40`、`RELATEDNESS` 表——**文献里没有任何一个数字与之对应**。Fogarty 的 30/60/120/300 是**特征统计窗**，不是开火阈值；Horvitz 的 `p*` 是随效用变化的，**没有常数**。
2. **证明不了"可撤回性（reversibility）"是一项独立因子。** `timing.py` 里 `reversibility = 1.0` 是常数，注释写"说话本身可撤回"——**这是我的推断，不是文献结论**（Horvitz 原文没有把 `u(A,¬G)` 分解出可撤回性）。
3. **无法在本机验证任何判据的有效性**，包括我们自己的 `timing.py`：`sprite_home/perceive/outcomes.jsonl` **0 字节**，`offers.jsonl` 只有 `shown/auto_started/auto_failed/auto_completed/retracted` 这类**结果位**，没有"用户是否受益"。没有闭环 = 没有效度。
4. **样本量级差一到两个数量级**：我们的 logs 只覆盖约 **3 小时**、单一被试、20 个 app；Fogarty 是 4 人 × 7am–6pm 工作日，Iqbal & Horvitz 2007 是现场研究，Mark 2008 是 48 人实验。
5. **场景不同**：所有 HCI 结论来自**有明确任务**的实验室/办公室研究；我们的场景是"无人指定任务的桌面陪伴"。"need"在文献里指"用户的任务是否受益"，在我们这里**没有对应物**。
6. **年代不同**：这批文献是 1999–2008 的老 HCI，除 §L/§M 外**没有** LLM / 持续感知桌面 agent 的设定；"什么时候开口"能否迁移到主动式 LLM agent，**文献未验证**。
7. **可信度上限提醒**：本报告的【已读原文】只覆盖 9 篇/份；`78%`、`82.4%`、`63.2%` 这些准确率分别来自**人工模拟传感器 / Wizard-of-Oz / 实验室任务**，**不能**读成"真实装机日志上也能达到"。

### 4.2 证伪 / 核不到的条目清单（用户点名要的）

1. **「可打断性预测 82.4%」被当成真实传感器结果 —— 更正。** 该数字出自 §J Fogarty TOCHI 2005，其"传感器"是**人工看录像编码出来的模拟值**；且同一研究的 chance 基线是 **68%**（类别不平衡），82.4% 的边际增益远小于字面。
2. **「被打断后要 23 分钟 15 秒才能回到任务」—— 在 Mark 等 CHI 2008 原文中不存在**（该文只有"更快"，无任何 23 min）。通行出处是 Mark/González/Harris CHI 2005 §I，而其摘要说的是"**多于两个中间活动**"（**活动计数，不是秒数**）。CHI 2005 正文 closed，**这个数字我核不到** → 标【未核实】，不得引用。
3. **「receptivity 是独立于 need 的一轴」—— 找不到显式出处。** JITAI 原文把 vulnerability/opportunity 与 receptivity 分节定义（§K，逐字已录），但**从未**写成"独立轴/独立维度"；检索 independent / distinct / axis 等词无命中。**这是我的归纳。**
4. **「冷却（cooldown）是独立模块 / 有理论对应」—— 核不到一件。** 本次逐篇检索后**支持**项目内既有结论（`docs/strategy/ALGORITHM-SELECTION.md:126`、`docs/strategy/_recon/08b-online-algorithms.md:286`、`docs/strategy/_recon/08c-proactive-agent-era.md:434-438`）：文献里它只以 intervention fatigue / user burden / over-triggering 的形式存在，**没有计时器式形式化**。我没有推翻它，只是给它补了唯一可能的入口（§K）。
5. **Adamczyk & Bailey CHI 2004 的具体数字 —— 核不到**（closed）。且摘要**只说情绪状态与正向社会归因有差异，没说任务绩效有差异**——与流行的转述相反。
6. **Iqbal & Horvitz CHI 2007 的现场研究数字 —— 核不到**（closed），只拿到摘要（suspension/resumption + 日志工具）。
7. **Iqbal & Bailey CHI 2007 / CHI 2008 的准确率数字 —— 核不到**（closed）。摘要措辞只有 "reasonably well"、"reduces frustration and reaction time"，**无数字**。
8. **Fogarty CHI 2003 的 78% / 90% —— 只到摘要级**，且**不可**与 TOCHI 2005 的 82.4% 混用（不同研究、不同被试、不同类别定义）。
9. **Horvitz CHI 1999 的 `p*` 不存在常数**。任何把它写成固定阈值的转述都是二次加工；我们的 `V_SILENCE=0.25` 是自造。

---

## 5. 参考文献（真实可核对）

| # | 文献 | 出处 / 编号 | 可信度 |
| --- | --- | --- | --- |
| 1 | Horvitz. Principles of Mixed-Initiative User Interfaces | CHI 1999, pp.159-166, DOI `10.1145/302979.303030` | 【已读原文】+【仅核书目】 |
| 2 | Horvitz, Jacobs, Hovel. Attention-Sensitive Alerting | UAI 1999, p.305 起, arXiv:`1301.6707` | 【已读原文】摘要段 |
| 3 | Iqbal & Bailey. Leveraging Characteristics of Task Structure to Predict the Cost of Interruption | CHI 2006, pp.741-750, DOI `10.1145/1124772.1124882` | 【已读原文】 |
| 4 | Iqbal & Bailey. Understanding and developing models for detecting and differentiating breakpoints during interactive tasks | CHI 2007, pp.697-706, DOI `10.1145/1240624.1240732` | 【已读原文·摘要级】 |
| 5 | Iqbal & Bailey. Effects of intelligent notification management on users and their tasks | CHI 2008, pp.93-102, DOI `10.1145/1357054.1357070` | 【已读原文·摘要级】 |
| 6 | Iqbal & Horvitz. Disruption and recovery of computing tasks: field study, analysis, and directions | CHI 2007, pp.677-686, DOI `10.1145/1240624.1240730` | 【已读原文·摘要级】 |
| 7 | Adamczyk & Bailey. If not now, when? The effects of interruption at different moments within task execution | CHI 2004, pp.271-278, DOI `10.1145/985692.985727` | 【已读原文·摘要级】 |
| 8 | Mark, Gudith, Klocke. The Cost of Interrupted Work: More Speed and Stress | CHI 2008, DOI `10.1145/1357054.1357072` | 【已读原文】 |
| 9 | Mark, González, Harris. No Task Left Behind? Examining the Nature of Fragmented Work | CHI 2005, DOI `10.1145/1054972.1055017` | 【已读原文·摘要级】 |
| 10 | Fogarty, Hudson, Atkeson, Avrahami, Forlizzi, Kiesler, Lee, Yang. Predicting Human Interruptibility with Sensors | TOCHI 2005, 12(1):119-146, DOI `10.1145/1057237.1057243` | 【已读原文】 |
| 11 | Fogarty, Hudson, Atkeson. … (CHI 2003 版) | CHI 2003, pp.257-264, DOI `10.1145/642611.642657` | 【已读原文·摘要级】 |
| 12 | Nahum-Shani, Smith, Spring, Collins, Witkiewitz, Tewari, Murphy. Just-in-Time Adaptive Interventions (JITAIs) in Mobile Health | Ann Behav Med 52(6):446-462, DOI `10.1007/s12160-016-9830-8`, PMC5364076 | 【已读原文】 |
| 13 | Trella, Ghosh, …, Nahum-Shani, Murphy. Effective monitoring of online AI decision-making algorithms in JITAIs | npj Digital Medicine, DOI `10.1038/s41746-026-02669-4`, PMC13518862 | 【已读原文】 |
| 14 | Ho, Balaji, Koseoglu, Sandha, Pei, Srivastava. Quick Question: Interrupting Users for Microtasks with Reinforcement Learning | arXiv:`2007.09515v1` [cs.HC]；HiLL Workshop @ ICML 2020 | 【已读原文】 |

**本报告用到的本机材料（`tmp_lit/` 将在收尾时删除）**：`horvitz_chi99.txt`、`horvitz_alerting.txt`、`iqbal_bailey_chi06.txt`、`mark_chi08.txt`、`fogarty_tochi2005.txt`、`jitai_abm2018.txt`、`jitai_npj2026.txt`、`ho_quickquestion.txt`，及脚本 `verify.py` / `oalink.py` / `s2.py` / `grab.py` / `tryurls.py` / `pdftext.py` / `snippet.py` / `show.py` / `unpaywall.py` / `crab.py` / `abs.py` / `ls.py` / `wb.py` / `ideals.py` / `ax.py` / `ledger.py` / `ledger2.py`。
