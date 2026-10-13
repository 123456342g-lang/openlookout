# 08b · 在线/免训练的「意外度 · 变点 · 边界 · 停止」算法调研

> 分区：在线、闭式、免梯度训练的意外度 / 变点 / 边界 / 停止（SPRT、最优停止）算法。
> 交付对象：`E:\OpenLookout\src\openlookout\sprite\proactive\timing.py` 的候选替代/增强。
> **LLM 时代的 proactive agent 综述不在本文件范围（由他人负责）。**

## 0. 核实口径（先读这一节，它决定每条结论的可信度）

本次调研环境里：
- `web_search` **不可用**（缺 `DEEPSEEK_API_KEY`）；
- DuckDuckGo HTML 端点返回人机验证页；Bing `format=rss` 返回与本查询**完全无关**的结果（被反爬/缓存污染，不可作为检索依据）；
- arXiv PDF 域名走透明代理，`web_fetch` 工具会因「非公网 IP」拒绝，但 `Invoke-WebRequest` 直连**可用**。

因此改用 **Crossref API + arXiv API + 直接抓原文 PDF/HTML**。每条结论标三档：

| 标记 | 含义 |
|---|---|
| **【已读原文】** | 我下载并读了论文正文（或官方摘要正文），公式/结论逐字来自该文本 |
| **【仅核书目】** | 只核到 DOI / 刊名 / 年份 / 作者（Crossref 命中），**正文没读到**；机制描述来自通行理解，属我的推断 |
| **【未核实】** | 检索不到，或结果明显无关；**不得作为方案依据** |

「我的推断」与「原文陈述」在正文中分列，凡推断均显式标注。

---

## 1. 算法卡片

### 卡片 A — 贝叶斯意外（Bayesian Surprise）

**出处**
- Laurent Itti, Pierre F. Baldi, *Bayesian Surprise Attracts Human Attention*, NIPS 2005（Advances in Neural Information Processing Systems 18）, pp. 547–554, MIT Press. 官方页：<https://papers.nips.cc/paper_files/paper/2005/hash/0172d289da48c48de8c5ebf3de9f7ee1-Abstract.html>　**【已读原文（官方摘要正文）】**
- 期刊扩展版：*Vision Research* 49(10):1295–1306, 2009，DOI `10.1016/j.visres.2008.09.007`；PDF：<https://ilab.usc.edu/publications/doc/Itti_Baldi09vr.pdf>　**【已读原文】**
- 后续统一表述：P. F. Baldi, L. Itti, *Of bits and wows: A Bayesian theory of surprise with applications to attention*, Neural Networks 23(5):649–666, 2010，DOI `10.1016/j.neunet.2009.12.007`　**【仅核书目】**（PDF 在 iLab 主页存在，本次未读）

**算法形式（原文 Eq. 4，逐字）**

```
S(D, M) = KL(P(M|D), P(M)) = ∫_M P(M|D) · log [ P(M|D) / P(M) ] dM
```

- 记 `D` 为新观测数据，`M` 为观察者的**模型/假设空间**（`M ∈ 𝓜`），`P(M)` 是先验信念，`P(M|D)` 是贝叶斯更新后的后验。原文：“D carries no surprise if it leaves the observer's beliefs unaffected”，因此“we formally measure surprise by quantifying the distance (or dissimilarity) between the posterior and prior distributions”，并被选为 **KL 散度**（`KL(P(M|D), P(M))`，对后验取期望），原文给的理由是 KL 不对称但在重参数化下不变。
- 单位「wow」：单个模型 `M` 的意外 = `log₂ P(M|D)/P(M)`（两次信念差异 = 1 wow）。

**与我现在这套的 Shannon 意外差在哪（这是本卡片的核心）**

原文对比（**【已读原文】**）：
1. **积分域不同**：*“Shannon's entropy requires integration over the space D of all possible data observations, while surprise requires integration over the space M of all models of the observer.”* 我的 `s_t = −log₂P(app_t|app_{t−1}) − log₂P(type_t)` 积的是**数据空间**（这件事本身多罕见），贝叶斯意外积的是**模型空间**（这件事让我的信念改了多少）。
2. **白雪悖论（原文实测数字）**：随机雪花在会话中**永远最无聊**，却携带**最大的 Shannon 信息量**；“there are many more possible random images than there exists natural images”，所以 snow 的熵高于自然场景。原文实测：2 万帧电视节目样本中，雪的 **Shannon 信息约是电视的 20 倍/秒**，而**雪每秒的 surprise 约是电视的 1/17**。推论（原文）：有意思/意外的数据常常携带**中等**的 Shannon 信息，位于「完全可预测（全黑帧）」与「完全不可预测（雪）」之间。
3. **这是我手调阈值最容易踩的坑**：`−log₂P` 对「本来就高熵、但早已习惯」的状态持续给高分（比如一个 app 集合很杂的前台），而真正的「模型切换」未必拿最高分。

**在线复杂度 / 是否免训练 / 超参数**
- 若模型空间用**共轭指数族**（原文 §2.3 明确 “conjugate-exponential models are particularly convenient”，并说 surprise “can always be computed numerically, but also analytically in many practical cases”），belief 更新只需**充分统计量增量更新**；对 K 个符号的 categorical/Dirichlet，单步是 O(K)（KL 闭式含 digamma）。
- **免训练：是**（无梯度、无 EM；只需先验）。
- **超参数**：先验的超参（如 Dirichlet 浓度 `α`，取全 1 即 1 个）+ 「模型空间怎么划」这个结构选择。工程上约 **1–2 个**。

**可实现的递推（明确区分来源）**
- **原文给的、可直接照抄的算例（Eq. 5–9，2×2 列联表）【已读原文】**：先验 `P(M)=P(M̄)=1/2`，联合表 `a=1/8, b=3/8, c=3/8, d=1/8`；观测 `D1` 后 `P(M|D1)=a/(a+b)=1/4`、`P(M̄|D1)=b/(a+b)=3/4`，单模型 `S(D1;M)=log₂(1/4 ÷ 1/2)=−1.00 wow`、`S(D1;M̄)=log₂(3/4 ÷ 1/2)=0.58 wow`，按后验加权总意外 `≈0.19 wow`；**同一观测再来一次只剩 0.07 wow**（“nearly three times less”）。这条「重复观测意外递减」正是我 `REPEAT_PENALTY`/硬冷却想手工模拟、但没做对的效应。
- **我的推断（非原文）**：把 (app, title 词、type) 作为符号，belief 用 Dirichlet–multinomial；单步 `S = KL( Dir(α+δ_obs) ‖ Dir(α) )`，这是标准 KL 闭式（含 digamma）。原文只给了 Eq. 4 的积分定义与 2×2 算例，未给 Dirichlet 版本的显式式子——**该式属标准结果，未在 Itti 原文逐字见到**。

---

### 卡片 B — Bayesian Online Change-Point Detection（BOCPD）

**出处**
- Ryan Prescott Adams, David J.C. MacKay, *Bayesian Online Changepoint Detection*, arXiv:0710.3742 (2007). <https://arxiv.org/abs/0710.3742>　**【已读原文（ar5iv 正文）】**

**算法形式（原文 Algorithm 1，逐字）**
目标是 run-length 后验 `P(r_t | x_{1:t})`，`r_t` = 距上次变点的时长。递推（原文 Algorithm 1，步骤 1–10）：

```
1. Initialize:  P(r_0) = S̃(r)  or  P(r_0 = 0) = 1
                ν_1^(0) = ν_prior ,  χ_1^(0) = χ_prior
2. Observe new datum x_t
3. Evaluate predictive probability:
                π_t^(r) = P(x_t | ν_t^(r), χ_t^(r))
4. Growth probabilities:
                P(r_t = r_{t-1}+1, x_{1:t}) = P(r_{t-1}, x_{1:t-1}) · π_t^(r) · (1 − H(r_{t-1}))
5. Changepoint probabilities:
                P(r_t = 0, x_{1:t}) = Σ_{r_{t-1}} P(r_{t-1}, x_{1:t-1}) · π_t^(r) · H(r_{t-1})
6. Evidence:    P(x_{1:t}) = Σ_{r_t} P(r_t, x_{1:t})
7. Run-length posterior:  P(r_t | x_{1:t}) = P(r_t, x_{1:t}) / P(x_{1:t})
8. Update sufficient statistics:
                ν_{t+1}^(0) = ν_prior ,  χ_{t+1}^(0) = χ_prior
                ν_{t+1}^(r+1) = ν_t^(r) + 1 ,  χ_{t+1}^(r+1) = χ_t^(r) + u(x_t)
9. Prediction:  P(x_{t+1} | x_{1:t}) = Σ_{r_t} P(x_{t+1} | x_t^(r), r_t) P(r_t | x_{1:t})
10. Return to 2
```

**changepoint 先验（原文，逐字）**：`P(r_t | r_{t-1})` 只有两个非零结果——要么 `r_t = r_{t-1}+1`（跑下去，概率 `1−H(r_{t-1}+1)`），要么 `r_t = 0`（变点，概率 `H(r_{t-1}+1)`）；其余为 0。

**hazard 函数（原文 Eq. 7，逐字）**

```
H(τ) = P_gap(g = τ) / Σ_{t=τ}^{∞} P_gap(g = t)
```

原文：若间隔先验是**离散指数（几何）**分布、时间尺度 `λ`，则过程无记忆、**hazard 恒为 `H(τ) = 1/λ`**。这就是「constant hazard」。

**关于「Student-t 还是 Gaussian 先验」**
原文没有规定必须用 Student-t 或 Gaussian：它把**预测分布**抽象成 `P(x_t | r_t, x_t^(r))`，并用**共轭指数族**统一处理（§2.3），充分统计量 `(ν, χ)` 增量累积。原文三个实验分别用：**高斯均值**（well-log，µ=1.15×10⁵，σ=1×10⁴，λ_gap=250）、**零均值高斯+逆方差 Gamma 先验**（道指收益，a=1，b=10⁻⁴，λ_gap=250）、**Poisson 过程 + Gamma 先验**（煤矿事故，a=b=1，λ_gap=1000）。—— **Student-t 预测是「高斯均值 + 逆 Gamma 方差」边缘化后的自然结果**，原文未逐字点名 Student-t，**此关联属我的推断**。

**零训练是否成立**
原文全篇是纯贝叶斯递推，**没有任何梯度/EM 训练步骤**：你只需事先指定 (a) hazard/间隔先验（常数 hazard 时就是 1 个 `λ`）、(b) 预测模型的先验超参（categorical 情形即 Dirichlet 浓度）。所以「零训练」**成立**——代价是「先验要人给」，不是「无参数」。

**在线复杂度（原文 §2.4，逐字结论）**
“The space- and time-complexity per time-step are linear in the number of data points so far observed.” 截断策略：丢弃尾部质量小于阈值（原文举例 `10⁻⁴`）的 run-length 估计后，“yields a constant average complexity per iteration on the order of the expected run length `E[r]`”（最坏仍线性）。

- **免训练：是**（纯贝叶斯）；**超参数：2**（几何 hazard 的 `λ` + 符号流 Dirichlet 浓度 `α`）。

**我的推断（工程落法，非原文）**：把 operations 流的 `(app, type)` 当作符号 `x_t` 喂进去，则 `P(r_t = 0 | x_{1:t})` 直接就是「此刻是活动边界」的概率；单一 `λ` 取代 `THETA_HI / THETA_TRANS / WINDOW_S / SMOOTH`。

---

### 卡片 C — 事件分割理论（EST）与其计算模型

**出处**
- Jeffrey M. Zacks, Nicole K. Speer, K. M. Swallow, T. S. Braver, J. R. Reynolds, *Event perception: A mind–brain perspective*, Psychological Bulletin 133(2):273–293, 2007，DOI `10.1037/0033-2909.133.2.273`　**【仅核书目】**
- Jeffrey M. Zacks, K. M. Swallow, *Event Segmentation*, Current Directions in Psychological Science 16(2):80–84, 2007，DOI `10.1111/j.1467-8721.2007.00480.x`　**【仅核书目】**
- **计算模型（关键）**：J. R. Reynolds, J. M. Zacks, T. S. Braver, *A Computational Model of Event Segmentation From Perceptual Prediction*, Cognitive Science 31(4), 2007，DOI `10.1080/15326900701399913`　**【已读原文（官方摘要正文）】**

**机制（摘要逐字，可直接落地的那一句）**
> “These simulations demonstrate that experience with recurring patterns enables a system to accurately predict upcoming stimuli within an event, **to identify boundaries between such events based on transient increases in prediction error**, and to use such boundaries to improve prediction about subsequent activities.”

即：维护一个**事件模型**去预测下一个刺激；当**预测误差出现瞬态上升**时，标记为**边界**，并用该边界去更新事件模型。这与卡片 B 的 run-length 变点是同一件事的两种语言（贝叶斯版 vs. 预测误差版），与我现在的 `s_t` **形态最像**——差别在于：原文的边界判据是「误差**相对事件模型**的瞬态上升」，而我的 `s_t` 是「**全局** unigram/bigram 的罕见度」，没有「当前这一段的事件模型」这个概念。
- **未核实**：该模型的具体学习规则/更新方程（我只读到摘要，正文未获取）。落地细节需另行核原文。
- **超参数**：≥3（事件模型参数 + 更新规则 + 预测误差阈值）。**是否免训练**：原文称 “self-organizing”，**倾向于无需外部标注**；但不能断言「零超参」。

**HMM / HSMM 做时间分割**【仅核书目】
- 事件类流分割实例：J. P. Gozali, M.-Y. Kan, H. Sundaram, *Hidden Markov Model for Event Photo Stream Segmentation*, IEEE ICMEW 2012，DOI `10.1109/icmew.2012.12`。
- HSMM 通用形式：S. Yu, *Hidden Semi-Markov Models*, 2016，DOI `10.1016/b0-12-802767-7.00002-4` → 实为 `10.1016/B978-0-12-802767-7.00002-4`（**注意：此 DOI 我来自 Crossref 命中，未逐字复核**）。
- 在线 HMM 的粒子滤波推断：P. Fearnhead, P. Clifford, *On-line inference for hidden Markov models via particle filters*, JRSS-B 65(4):887–899, 2003（出现在 BOCPD 参考文献表，**【仅核书目】**）。
- **要点/我的推断**：HMM 用转移矩阵隐式编码时长（几何 dwell time），HSMM 用**显式时长分布**，因此 HSMM 更适合「活动段有典型长度」的行为流。但两者参数拟合通常靠 **Baum–Welch/EM**，**属于迭代训练，与本项目「免梯度训练」的定位冲突**；若坚持免训练，只能取「固定参数 + 在线 Viterbi/前向滤波」的退化用法（单步 O(K²)，K=状态数）。
- 视频侧的实现：L. Itti, P. F. Baldi, *A Principled Approach to Detecting Surprising Events in Video*, CVPR 2005, pp. 631–637；及 R. C. Voorhies, L. Elazary, L. Itti, *Application of a Bottom-Up Visual Surprise Model for Event Detection in Dynamic Natural Scenes*, VSS 2010　**【仅核书目，来自作者官方出版物列表 <https://ilab.usc.edu/publications/su.html>】**。

**可穿戴/传感器侧的「event boundary detection」**
- Crossref 检索到一篇题为 *Event boundary detection using autonomous agents in a sensor network*（Jaffer, 2021, DOI `10.32920/ryerson.14665710`）**【仅核书目】**。除此之外，本次未检索到与我场景同构（2–3 秒符号流水）的可穿戴事件分割实现——**不要把它当作「已有成熟对照」**。

---

### 卡片 D — Wald 的 SPRT（序贯概率比检验）作为「证据够了就开口」的停止规则

**出处**
- Abraham Wald, *Sequential Tests of Statistical Hypotheses*, The Annals of Mathematical Statistics 16(2):117–186, 1945，DOI `10.1214/aoms/1177731118`（Crossref 命中）　**【仅核书目】**
- 最优性：A. Wald, J. Wolfowitz, *Optimum Character of the Sequential Probability Ratio Test*, AMS 19(3):326–339, 1948，DOI `10.1214/aoms/1177730197`　**【仅核书目】**
- 公式转述来源：Wikipedia *Sequential probability ratio test*（正文我读了，下述公式为该条目的正文陈述）**【已读原文（Wikipedia 正文）】**

**算法形式（逐字转述）**
```
S_0 = 0
S_i = S_{i-1} + log Λ_i        （Λ_i 为第 i 个样本的似然比）

停止/判定规则：
  a < S_i < b  → 继续观测（critical inequality）
  S_i ≥ b      → 接受 H1
  S_i ≤ a      → 接受 H0

阈值由目标错误率给定：
  a ≈ log( β / (1 − α) )
  b ≈ log( (1 − β) / α )
```
- 原文（Wikipedia）注明：因离散情形可能「在样本间跨过阈值」，上式**只是近似**；连续情形下为精确边界。
- 指数分布 × 单参数的例子中，停止边界是两条斜率 `log(θ₁/θ₀)` 的平行线，维基原文：“Sampling should stop when the sum of the samples makes an excursion outside the continue-sampling region.”

**作为「够了就开口」的适配**
- **优点**：O(1)/事件、**免训练**、阈值有**明确的 α/β 语义**（这正是我现在的 `THETA_HI=9.0` 完全缺失的东西）；能**累积**微弱但持续的证据，而我现在是单样本越阈就触发。
- **代价**：要写出 `H0/H1` 与 `log Λ_i`。对我的符号流，可令 `H1`=“进入了新情境/该开口”，`H0`=“维持常态”，用当前事件在「当前段模型 vs 背景模型」下的似然比作 `Λ_i`。
- **超参数：2**（`α`, `β`；等价地直接给 `a`,`b`）。

---

### 卡片 E — 最优停止 / 秘书问题一族

**出处（已读正文）**：Wikipedia *Secretary problem*　**【已读原文（Wikipedia 正文）】**；主源论文（如 Ferguson 的史述）本次**因 Crossref 429 未核到**。

**算法形式（逐字转述）**
> “the interviewer rejects the first `r − 1` applicants (let applicant M be the best applicant among these `r − 1` applicants), and then selects the first subsequent applicant that is better than applicant M.”

成功概率：

```
P(r) = (r − 1)/n · Σ_{i=r}^{n} 1/(i − 1)          （r = 1 时 P(1) = 1/n）
```

最优 `r` 附近 `r ≈ n/e`，成功率 ≈ `1/e ≈ 0.37`，俗称 **37% 规则**；维基还有 **1/e-law of best choice** 处理 `n` 未知的情形（此时最优胜率一般**低于** 1/e）。

**适配度：低（1–2）**。原因（我的推断）：该类问题要求 (i) 候选**随机顺序到达**、(ii) 只能做**相对排名**、(iii) `n` 已知或分布已知；而行为流水既非 i.i.d. 随机序，也没有「要挑一个最优时刻」的单一终局目标。**可以借用它的思想（先探索一段再开始出手），但不能直接当算法用。**

---

### 卡片 F — CUSUM（Page）

**出处**
- E. S. Page, *Continuous Inspection Schemes*, Biometrika 41(1/2):100–115, 1954，DOI `10.1093/biomet/41.1-2.100`（Crossref 命中两版：`10.2307/2333009` / `10.1093/biomet/41.1-2.100`）　**【仅核书目】**
- 公式转述：Wikipedia *CUSUM*　**【已读原文（Wikipedia 正文）】**

**算法形式（逐字转述，单侧）**
```
S_0 = 0
S_{n+1} = max( 0 , S_n + x_{n+1} − ω_n )
```
> “When the value of S exceeds a certain threshold value, a change in value has been found. The above formula only detects changes in the positive direction.”（负向另有对称式）
- 超参数：参考值/权重 `ω`（漂移量）+ 阈值 `h`（+ 参考均值）= **2–3**。
- **免训练：是**；**O(1)/事件**。
- 与 SPRT 同族：SPRT 是「似然比累积」，CUSUM 是「偏差累积+重置」，都比我的单点阈值更抗噪。CUSUM 也是 BOCPD 的经典对照组（BOCPD 原文把自己定位在 Page 1954/1955、Lorden 1971 之后）。

---

### 卡片 G — ADWIN（自适应窗口漂移检测）

**出处**：A. Bifet, R. Gavaldà, *Learning from Time-Changing Data with Adaptive Windowing*, SIAM SDM 2007，DOI `10.1137/1.9781611972771.42`　**【仅核书目】**

**机制（我的推断，基于该文的通行描述）**：维护一个可变长窗口 `W`；不断检查把 `W` 切成两半 `W0, W1` 后均值差是否超出由 **Hoeffding 界**给出的 `ε_cut`；超出则丢弃旧的一半。超参数 **1 个**（置信度 `δ`）。
- **未核实**：`ε_cut` 的**精确常数与对数项**（`ε_cut = sqrt( (1/2m)·ln(2/δ') )` 之类的写法）我**没有读到原文**，落地前必须核原文。Wikipedia 无 *ADWIN* 条目（404）。
- **免训练：是**；数值流的在线复杂度通常写作 O(log W) 摊还。用在符号流上需先向量化（如 one-hot / 计数向量）。

---

### 卡片 H — Conformal prediction（无训练新颖性检测）

**出处**
- R. Laxhammar, G. Falkman, *Inductive conformal anomaly detection for sequential detection of anomalous sub-trajectories*, Annals of Mathematics and Artificial Intelligence, 2013，DOI `10.1007/s10472-013-9381-7`　**【仅核书目】**
- 同作者早版：*Conformal prediction for distribution-independent anomaly detection in streaming vessel data*, 2010，DOI `10.1145/1833280.1833287`　**【仅核书目】**
- 机制转述：Wikipedia *Conformal prediction*　**【已读原文（Wikipedia 正文）】**

**机制（逐字转述要点）**：在**校准集**上算非一致性分数（α-value），对测试点排序自己的 α 值得到 **p-value**；“the p-value together with a threshold (referred to as significance level) is used to determine whether the label should be in the prediction set”；`p ≤ ε` 即判为异常/排除。核心假设是数据的 **exchangeability（可交换性）**——Wikipedia 明确把它列为前提，并指出**概念漂移时新数据拿到低 p-value**。
- **免训练：接近是**（不需要拟合模型，但要一个**校准集**；非一致性度量要人选）。
- **超参数：1–2**（显著性 `ε` + 非一致性度量）。
- **对我场景的坑**：可交换性假设与「用户行为在漂移」直接冲突，裸用 conformal 会把「正常的状态切换」全判成异常；要用就要用 **sequential/adaptive conformal**（Laxhammar 的论文名里就有 sequential），**具体算法我没读到正文**。

---

### 卡片 I — 密度比估计（density-ratio）

**出处**：M. Sugiyama, M. Kawanabe, *Machine Learning in Non-Stationary Environments: Introduction to Covariate Shift Adaptation*, MIT Press, 2012（Crossref 命中「Importance Estimation」等章节，DOI `10.7551/mitpress/9780262017091.003.0004` 等）　**【仅核书目】**

**机制（我的推断）**：直接估计 `w(x) = p_test(x) / p_train(x)`，用 `w` 的大小当异常/新颖度；uLSIF/KLIEP 等把目标写成正则化最小二乘/最小化 KL 的**凸问题**（可用闭式线性系统解，不需梯度下降），但仍有**正则化系数 `λ` + 核宽 `σ`** 等超参。
- **免训练**：**不完全**（是「拟合权重」，属「少训练/闭式优化」，不是纯免训练）→ 与项目定位不完全契合，**优先级低**。

---

### 卡片 J — SNIP / information-theoretic attention allocation

**SNIP（`Snip ratio`，`Shannon-Nyquist-inspired attention allocation`）：【未核实】**
- Crossref 书目检索 `SNIP Shannon Nyquist attention allocation ratio` → 命中全部无关（Nyquist–Shannon 定理的工程书、3D 重建等）；
- arXiv API `ti:"SNIP"` → 命中的是 **Scopus 的 SNIP 期刊指标、SNIP 目标检测（Scale Invariance in Object Detection）、SNIP 网络剪枝、SNIP++ 符号回归**，与注意力分配无关；
- arXiv `all:"SNIP" AND all:"attention allocation"` → **0 条**；
- Bing（已被证明不可靠）→ 返回 Windows 截图工具。
- **结论：没有找到任何可核实的「SNIP / Snip ratio」注意力分配论文。** 请把此条目当作**误记或幻觉**，**不要写进技术方案**。若你能提供原始出处（URL/DOI），我再补核。

**可替代的、已核书目的「信息论注意力分配」**：
- Christopher A. Sims, *Implications of rational inattention*, Journal of Monetary Economics 50(3):665–690, 2003，DOI `10.1016/s0304-3932(03)00029-1`　**【仅核书目】**。把注意力建模为**有限 Shannon 信道容量**下的最优信息获取（closed-form 的二次型/高斯情形），是「Shannon–Nyquist 式注意力分配」在文献里真正可核的近亲；但它是**经济学决策论**框架，落到我场景需要自行定义信道与代价函数——**不是即插即用的算法**。

---

## 2. 汇总表

「与 timing.py 的增量」列写的是**相对现状的替换/新增动作**；「适配度」是我按本项目约束（在线、闭式、免梯度、2–3s 节奏、符号流）打的判断（1–5，**属我的评估，非文献结论**）。

| 算法 | 输入 | 免训练？ | 在线复杂度 | 超参数量 | 与 timing.py 的增量 | 适配度 |
|---|---|---|---|---|---|---|
| **贝叶斯意外**（Itti & Baldi 2009） | 符号流 + 模型空间定义 | 是（共轭先验即可） | O(K)/步（K=符号数，KL 含 digamma） | 1–2 | **替换 `surprises()` 的 `s_t`**：`−log₂P` → `KL(posterior‖prior)`，解掉白雪悖论 | **4** |
| **BOCPD**（Adams & MacKay 2007） | 符号流（categorical 预测 + 几何 hazard） | 是（纯贝叶斯） | 最坏 O(t)/步；尾截断后平均 O(E[r]) | 2（`λ` + `α`） | **替换 `THETA_HI/THETA_TRANS` 整套阈值逻辑**：输出 `P(r_t=0∣x_{1:t})` 作为边界概率；取代 `WINDOW_S/SMOOTH` | **5** |
| **EST / 预测误差分割**（Reynolds, Zacks, Braver 2007） | 事件模型预测 + 误差 | 倾向是（self-organizing） | 取决于事件模型 | ≥3 | 给「边界」一个认知学定义；需自建事件模型，细节未核 | **3** |
| **HMM / HSMM 分割**（Gozali 2012；Yu 2016） | 观测序列 | **否**（需 EM/Baum–Welch） | O(K²)/步（在线滤波/Viterbi） | K² + 发射参 + 时长分布 | 提供「分段」能力，但引入离线训练，与定位冲突 | **3** |
| **SPRT**（Wald 1945/48） | 单步对数似然比 | 是 | O(1)/步 | 2（`α`,`β`） | **新增「累积证据」层**：单点越阈 → 证据累积越阈，阈值有 Type-I/II 语义 | **4** |
| **CUSUM**（Page 1954） | 标量偏移量 | 是 | O(1)/步 | 2–3 | 同 SPRT 的极简替代，抗噪、可重置 | **4** |
| **最优停止 / 秘书问题** | 随机序、相对排名、已知 `n` | 是 | O(1)/步 | 0–1 | 仅可借「先探索后出手」的思想 | **1–2** |
| **ADWIN**（Bifet & Gavaldà 2007） | 数值流（需向量化符号流） | 是 | O(log W) 摊还 | 1（`δ`） | 新增漂移/遗忘；`ε_cut` 精确式**未核** | **3** |
| **Conformal 异常检测**（Laxhammar & Falkman） | 校准集 + 测试点 | 接近是（需校准集） | O(n)/次或排序 O(n log n) | 1–2 | 有校准 p-value；**exchangeability 与漂移冲突**，需 sequential 变体 | **3** |
| **密度比估计**（Sugiyama & Kawanabe 2012） | 训练/测试分布样本 | **否**（拟合权重） | 依赖核/样本量 | 2–3 | 增加拟合与超参，收益不明 | **2** |
| **SNIP / Snip ratio** | — | — | — | — | **未核实，不可用** | **0（不可评）** |
| **rational inattention**（Sims 2003） | 信道容量 + 代价 | 概念层 | — | — | 只提供注意力分配的**理论框架**，非算法 | **2** |

---

## 3. 我现在这套，它的学名是什么、缺什么

### 3.1 学名（对着 `timing.py` 逐项对号）

| 我现在的东西 | 学名 |
|---|---|
| `s_t = −log₂ P(app_t\|app_{t−1}) − log₂ P(type_t)` | **一阶马尔可夫 n-gram 的自信息 / surprisal（Shannon 意外）**，两项独立相乘即**伪似然**（app 与 type 未联合建模） |
| `(num + smooth)/(n_from + smooth·k_app)`，`SMOOTH = 0.5` | **加性平滑（add-α / Laplace 型）的最大似然估计**，`α = 0.5` |
| `THETA_HI = 9.0`、`THETA_TRANS = 7.0` 单点越阈触发 | **静态阈值异常检测（surprisal 上的 hard threshold detector）**；无 Type-I/II 语义、不累积证据 |
| `relatedness × recency × reversibility − disturbance − repeat_pen` | **手写（heuristic）价值函数**，系数全为人工常数；这在文献里没有对应的「算法」，只有「手工打分」 |
| `WINDOW_S = 90`、`SETTLE_S`、`BUSY_S/N`、`REPEAT_*` | **启发式状态机 / 冷却计时器**（完全工程化，无理论对应） |

一句话：**我现在的做法是「加性平滑的一阶马尔可夫 surprisal + 手调阈值 + 手写价值函数」**，可以概括为 *surprisal-based prediction-error salience with hand-tuned static thresholds*。它不是 Bayesian surprise，不是变点检测，也不是序贯检验。

### 3.2 缺什么（逐条对应上面的卡片）

1. **语义错位（卡片 A）**：`−log₂P` 度量的是「这件事本身多罕见」，不是「这件事改变了我的信念多少」。原文实测的白雪悖论（雪 Shannon 信息 ≈ 20×、surprise ≈ 1/17×）说明这两者会**系统性背离**；对一个 app 集合很杂的前台，`s_t` 会长期偏高却毫无信息量。
2. **没有「当前这一段」的状态（卡片 B/C）**：我没有 run-length、没有活动段模型、没有时长分布，因此**没有边界语义**——只有「这一刻意外」。
3. **阈值无标定（卡片 D/F）**：`9.0 / 7.0 bits` 是人类拍的数，说不出对应的误报率；且是**单样本**越阈，无法把「持续但微弱」的证据累积成判定。
4. **无遗忘 / 无漂移处理（卡片 G/H）**：计数在固定 90s 窗口内累计、`SMOOTH=0.5` 的概率地板随窗口内事件数变化；没有自适应窗口、没有漂移检测。
5. **冷启动与首步（我的推断，读码得出）**：`prev is None` 时对所有 app 用 `total_app` 归一（`timing.py:125–126`），第一个事件几乎不产生意外；新 app 靠 0.5 平滑被压制——**「从没见过」与「很少见」被平滑糊成了一档**。
6. **伪似然（我的推断）**：`P(app_t|app_{t−1})` 只用上一步，`P(type_t)` 用全局 unigram，二者独立相乘；真实流里 type 强烈依赖 app（在 IDE 里 file_save 常见，在播放器里不是），这个条件结构被丢掉了。
7. **决策层完全手写（卡片 D 的反面）**：`V(开口) − V(沉默)` 的每一项系数都是常数，没有校准、没有学习、没有理论依据——这是比「意外度」更该被质疑的部分，但它不在本次文献分区的解法范围内，只能指出。

### 3.3 最该替换掉的那一个手调常数

**`THETA_HI` / `THETA_TRANS`（两个 surprisal 阈值）**——因为 `9.0` 和 `7.0` 这两根线是**唯一一个既无单位语义、又承担全部触发责任**的常数。替换它的机制是 **BOCPD 的 run-length 后验**：把 `(app, type)` 符号流喂进去，用 `P(r_t = 0 | x_{1:t}) > c` 判边界；好处是阈值 `c` 变成**可解释的概率/误报率目标**，而时间尺度由 hazard `λ`（一个「平均每段多长」的可解释量）承担，`WINDOW_S`、`SMOOTH`、`THETA_*` 一起被吸收。若只想做最小改动：保留现有 `s_t` 作证据，**在其上叠一层 SPRT/CUSUM 累积 + 由 `α/β` 定的阈值**（卡片 D/F）。

---

## 4. 这份调研证明不了什么

诚实边界，避免被后续读者当成结论使用：

1. **没有任何实测数字。** 本文件没有跑过 `timing.py` 在真实 `operations.jsonl` 上的离线重放（`python -m sprite.proactive.timing --ops ...`），没有基线、没有胜率、没有延迟测量。**「适配度 1–5」是我的机制层面判断，不是评估结果。**
2. **大部分引用只核了书目。** 逐条卡片已标「【仅核书目】/【未核实】」；HMM/HSMM 的 EM 在线化、ADWIN 的 `ε_cut` 精确式、Reynolds 计算模型的更新方程、conformal 的 sequential 变体、BOCPD 与 Student-t 预测的对应关系，**都没有读原文正文**。凡我标注「我的推断」的，不得当作原文献结论引用。
3. **「免训练」不等于「无参数」。** Bayesian surprise、BOCPD、ADWIN、SPRT 都需要先验/阈值/参考值。本文件只证明它们**不需要梯度下降或 EM**，没有证明它们**免人工设定**。
4. **复杂度是论文自述或通行量级**，未在 Python 上实测；BOCPD 的 O(E[r]) 明确**依赖尾截断阈值（原文举例 10⁻⁴）**，截断策略会显著改变实际开销。
5. **SNIP 未核实。** 本文件不能支持任何以「SNIP / Snip ratio」为名的方案；若上游文档已引用它，应视为**待证伪条目**。
6. **认知科学结论不能直接外推。** 原文的 “72% of all human gaze shifts…” 是**视频注视实验**的结论，与「每 2–3 秒读一次行为流水」在数据类型、时间尺度、任务上都不是同一问题。
7. **未覆盖的分区**：强化学习类 proactive agent、深度学习 novelty detection、LLM 时代的 proactive agent 综述——**不在本文件范围**，本文件也不与它们做比较。
8. **本文件不构成选型决定。** 它只给出「有哪些可核的闭式/在线机制、它们相对现有 `timing.py` 的增量是什么、哪些说法站不住」。选型还缺一个必要的实证环节：**对同一段 `operations.jsonl` 做离线重放对照**（这需要另开任务，且会改动项目代码，超出本次「只读项目 + 只写本文件」的硬边界）。

---

*调研范围：在线/免训练的意外度、变点、边界、停止算法。核实手段：Crossref API、arXiv API、arXiv/作者主页/期刊官方 PDF 与 Wikipedia 正文直取（本轮环境无可用 web_search）。*
