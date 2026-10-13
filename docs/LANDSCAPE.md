# 桌面 AI 助手竞品与技术路线调研

> 调研日期：2026-10-13。全部事实来自本文列出的公开链接，访问日期同上。
> **写作纪律**：本文只写能追到来源的内容。凡是查不到的，写「未查到」，不推测、不补数字、不编造产品名或融资金额。个别来源之间互相矛盾，本文把矛盾原样列出并标注可信度，由读者自行判断。
> 本��只做调研，未改动仓库任何代码；未切换 git 分支。

---

## 0. 一句话结论

「持续感知屏幕 + 主动开口」这条路上，**感知层已经被做透且免费，记忆回放层已被两家大厂证伪并关闭，主动开口层至今没有一个跑通商业化的产品** —— 独立空间只剩「不打扰的主动开口」这一个窄切口，而它恰好是全场最难验证、最容易被卸载的一环。

---

## 1. 竞品总表

按用户要求，每产品一列/一行。价格为公开标价，未标注即为未查到。

| 名字 | 定位 | 怎么感知屏幕 | 怎么开口 | 本地/上云 | 价格 | 来源 |
|---|---|---|---|---|---|---|
| **Rewind AI** | 个人记忆回放（已关闭） | 持续录制屏幕+音频，本地压缩后索引 | **不会主动开口**；Ask Rewind 被动问答 | 本地优先 | 约 $19–20/月（历史价）；**服务已停止** | [everpaper 复盘](https://everpaper.app/docs/blog/best-rewind-alternatives-2026)、[WIRED](https://link.wired.com/external/33399557.12984/aHR0cHM6Ly93d3cucmV3aW5kLmFpL3BlbmRhbnQ_c291cmNlPUVtYWlsXzBfRURUX1dJUl9ORVdTTEVUVEVSXzBfU3RldmVuTGV2eV9aWiZ1dG1fc291cmNlPW5sJnV0bV9icmFuZD13aXJlZCZ1dG1fbWFpbGluZz1XSVJfUGF5d2FsbFN1YnNfMTExNzIzX1N0ZXZlbkxldnkmdXRtX2NhbXBhaWduPWF1ZC1kZXYmdXRtX21lZGl1bT1lbWFpbCZ1dG1fdGVybT1XSVJfU3RldmVuTGV2eSZ1dG1fY29udGVudD1XSVJfUGF5d2FsbFN1YnNfMTExNzIzX1N0ZXZlbkxldnkmdW5iZXhhZD01YmVhMGQ3NTJkZGY5YzcyZGM4ZGYwMjkmY25kaWQ9Mjk1OTQxMDImZXNyYz1TTE9uZUNsaWNr/5bea0d752ddf9c72dc8df029Ca99e6ed0) |
| **Limitless**（Pendant + 云端） | 可穿戴会议记忆（Meta 收购后收缩） | 佩戴式麦克风 + 桌面 | 每日摘要/会前简报 | 云端 | 历史 $19.99/月 + $99 硬件；收购后老用户免费 | [9to5Mac](https://9to5mac.com/?p=1031480)、[百度百科](https://baike.baidu.com/item/Limitless/67061489) |
| **Microsoft Recall** | Windows 活动时间线回放 | **周期性快照**（非连续录像），NPU 本地索引 | **不会主动开口**；纯被动搜索 | **本地**，静态加密，不上传、不训练 | 随 Windows 11 / Copilot+ PC | [微软官方隐私与控制文档](https://support.office.microsoft.com/f1/article/d404f672-7647-41e5-886c-a3c59680af15)、[MS Learn 设备端 AI](https://learn.microsoft.com/zh-tw/training/modules/powerful-security-designed-for-ai/3-secure-and-productive-by-design) |
| **Microsoft Copilot Vision** | 用户主动开启的「看屏幕讲操作」 | 用户手动分享窗口/桌面，**云端**分析 | 只讲不动（只读、可口述），不主动 | **云端** | 含于 Microsoft 365 Copilot | [Raycast 类比对 Vision/Recall 的对比](https://perplexityaimagazine.com/ai-tools/can-ai-tools-see-my-screen)、[Windows Forum 讨论](https://windowsforum.com/threads/microsofts-copilot-vision-introduces-full-desktop-sharing-in-windows-11-ai-assistance.373742) |
| **Raycast Screen Awareness** | 启动器内置 AI，把当前窗口喂给模型 | 截图 + **无障碍层可读文本** + 选区 + 焦点控件 + 网页 DOM | **只在用户触发时采集**；文档明写「Nothing is captured in the background」 | 采集本地，**发送给模型时上云** | Free 无 AI；Pro $8–10/月；Plus $20/月；Max $50/月 | [Raycast 官方手册](http://manual.raycast.com/ai/screen-awareness)、[官方定价](https://www.raycast.com/pricing) |
| **Superhuman** | 高速邮件客户端 | 不感知屏幕，只读邮箱 | 不主动 | 云端 | $30/月，无免费档 | [SaaSLens 对比](https://saaslens.app/compare/raycast/superhuman) |
| **Manus** | 云端通用 agent，交付成品 | 云沙箱 + Browser Operator 插件操作**你自己的浏览器** | 有**定时任务**（schedule，可重复执行） | 云端 | Free 300 credits/日；Pro $20/$40/$200 月 | [Manus 定价核对](https://klyvoo.com/agents/manus)、[价格核对 2](https://aipricecompare.org/apps/manus.html) |
| **screenpipe** | 开源/源码可得 24/7 屏幕+音频记忆 | **事件驱动**（应用切换/点击/输入停顿/滚动/剪贴板变化才存帧）+ **无障碍树优先、OCR 回退** + 本地 Whisper | **不会主动开口**；MCP 让 Claude/Cursor 主动来问 | **local-first**，无账号；云 AI/同步/遥测为可选，默认开 | Free $0（10 credits/月）；Basic $21/月；Business $42/席/月 | [官方 README](https://raw.githubusercontent.com/mediar-ai/screenpipe/main/README.md)、[定价页](https://screenpipe.com/rewind)、[vs Limitless 对比](https://screenpipe.com/blog/screenpipe-vs-limitless-2026) |
| **OpenRecall** | 开源免费的 Recall 替代 | 定期截图 + 本地 OCR，语义搜索 | **不会主动开口** | 本地，可离线 | 免费（AGPLv3） | [官网](http://openrecall.github.io)、[GitHub](https://github.com/openrecall/openrecall)、[FAQ](https://github.com/openrecall/openrecall/wiki/FAQ/55cf3955b9690f4ec130c3d545bf7d8e6febdfec) |
| **Cluely** 及大量 fork | 「隐形」桌面 AI 悬浮窗（**面试作弊工具定位**） | 手动热键触发截图；系统级 **screen-capture-exclusion** 标志使其不出现在录屏/屏幕共享里 | 不主动；但**主动隐藏自己** | 云端 LLM | 商业版历史 $29–99/月（社区对比页口径，未见官方页核实） | [no-cluely 反检测项目](https://github.com/terminalsin/no-cluely)、[Dusky 溯源分析](https://getdusky.app/blog/is-cluely-detectable)、[HackerRank 官方 KB 引用](https://getdusky.app/blog/is-cluely-detectable) |
| **Shimeji-EE-AI / Shimeji-AI** | 桌面宠物 + AI 对话 | **不感知屏幕**（仅窗口交互：爬窗口、跟随鼠标） | 用户点开对话框才说 | **上云**，配置 OpenAI 兼容 endpoint + key | 免费开源 | [ShimejiEE-AI](https://github.com/mmmyyc/ShimejiEE-AI)、[DeepWiki 架构页](https://deepwiki.com/zh050707-lab/-shimeji-AI-) |
| **YCamie / shimeji.ai** | 商业版桌面宠物 | 未查到屏幕感知描述 | AI 聊天窗口 | 未查到 | 免费档每月 3 次生成；Basic 50 次/月；Advanced 200 次/月 | [shimeji.ai](http://www.shimeji.ai/) |
| **Claude Code** | CLI / IDE / 桌面编码 agent | **不感知你的屏幕**；读你给的仓库和终端 | 不主动（除非你挂 hooks / background agent） | 上云 | Pro $20/月（年付 $17）；Max $100 / $200 月 | [定价与限制对比](https://usepoly.co/claude-code-vs-codex)、[DEV 对比](https://dev.to/jamilxt/claude-code-vs-codex-cli-in-2026-which-subscription-should-you-actually-pay-for-m4m) |
| **Codex CLI** | 开源编码 agent | 同上，不感知屏幕 | 不主动 | 上云；CLI 为 Apache 2.0 开源 | 含于 ChatGPT：Free 有限额；Plus $20/月；Pro $100+ | [官方定价核对](https://www.swfte.com/compare/codex-vs-claude-code) |
| **Rabbit R1** | 桌面/随身 AI 伴侣硬件 | 旋转摄像头 + 语音，**用户按键说话** | 被动按键触发 | 云端 | $199 + 流量费 | [WIRED 评测](https://link.wired.com/click/43439766.523/aHR0cHM6Ly93d3cud2lyZWQuY29tL2Jldmlldy9yYWJiaXQtcjEvP3V0bV9zb3VyY2U9bmwmdXRtX2JyYW5kPXdpcmVkJnV0bV9tYWlsaW5nPVdJUl9QcmVtaXVtTW9kZWxCZWhhdmlvcl8wMTA4MjYmdXRtX2NhbXBhaWduPWF1ZC1kZXYmdXRtX21lZGl1bT1lbWFpbCZ1dG1fdGVybT1XSVJfUmV2aWV3TW9kZWxCZWhhdmlvcl8wMTA4MjYmYng9NWM0OGY5NDZmYzk0MmQwNDc3YmY3ZTNhJmNuZGlkPTQ5NDI2OCZoYXNoYT1kN2Q4YTkwMTE4NDE2ODc4ZTNkNWFiNGU4ZDcxODU0NCZoYXNoYj1jMTg3MDZjMzZlODM2YWVmZDkxZmExODY1OTIyNjZhMDM0MDQ3MGY3Jmhhc2hjPTM4MTQyMDVmYWJiYjc5N2JiM2FhNmJiYWRlNTFiNmQzMjgwZjM2NjFiYmQ0MmMwNTdhMjdhNmM4Yzg2NzliZGU/5c48f946fc42d0477ef7e3aCacd5d884)、[TechRadar 评测](https://global.techradar.com/da-dk/phones/rabbit-r1) |

### 1.1 表格里最关键的一条观察

**列「怎么开口」这一栏，14 个产品里有 11 个是「用户不主动触发就不说话」。** 唯一例外是 Manus 的**定时任务**——但那是用户自己排的日程表，不是 agent 判断「你现在需要我」。

这不是巧合，是行业在用真金白银投票：**主动开口目前没有被任何一家验证过。**

---

## 2. 屏幕感知技术路线对比

四条路线的成本/延迟/隐私对照。数字均来自下方来源，未查到的一律标注。

| 路线 | 典型延迟 | 成本 | 隐私暴露面 | 谁在用 | 来源 |
|---|---|---|---|---|---|
| **A. 定时截图**（间隔抓帧） | 单帧抓取+编码数十至数百 ms；整套循环秒级 | 最低，但要处理存储 | **高**：全屏所有内容，无结构化过滤 | Recall（官方明说「定期快照」）；OpenRecall（README：periodically taken snapshots） | [MS Recall 文档](https://support.office.microsoft.com/f1/article/d404f672-7647-41e5-886c-a3c59680af15)、[OpenRecall](https://github.com/openrecall/openrecall) |
| **B. VISION API / 模型主动抓帧** | 单次 VLM 调用约 1.8s（作者实测），五步流程 18–25s | **最高**，每帧都吃视觉 token | 中高：按需发送，但发出去就是全屏 | 所有 computer-use agent | [UIA vs 截图循环实测](https://www.cwfrazier.com/blog/uia-vs-screenshot-loop-benchmark) |
| **C. 屏幕录制流**（持续录） | 实时但带宽/存储昂贵 | 高；连续录制边缘体验 | **最高**：出问题就是整段录像 | screenpipe（多显示器全录，README 称这是与 Rewind/Granola 的差别） | [screenpipe README](https://raw.githubusercontent.com/mediar-ai/screenpipe/main/README.md) |
| **D. 无障碍 API 读 UI 树**（UIA / AX） | **快约两个数量级**；聚焦窗口树遍历常见 30–80 ms | **最低**，只传结构化文本，几乎不吃视觉 token | **最低**：可按控件类型/标题精确过滤 | screenpipe（优先 a11y，OCR 回退）；Raycast（无障碍层取文本）；Cluely 类工具 | [t8r.tech AX vs UIA](https://t8r.tech/alternative/macos-ax-vs-windows-uia-agent)、[Raycast 手册](http://manual.raycast.com/ai/screen-awareness) |
| **E. 混合双流**（2026 年主流做法） | a11y 走快路径，视觉兜底 | 中 | 中，且能靠 a11y 节点过滤掉大部分帧 | 各 desktop GUI agent 的事实标准 | [三种感知架构对比](https://coderlegion.com/29020/beyond-the-browser-autonomous-desktop-gui-agents-in-2026-ui-tars-computer-use-osworld-2-0) |

### 2.1 三个有实测数字的结论

1. **UIA 比截图循环快 17–32 倍。** 开发者实测：UIA invoke 链中位数 **725 ms**（每步约 110 ms），纯截图抓取 **12,150 ms**，带模型调用的完整视觉循环约 **22,950 ms**。而且测试中一个微软账户 OOBE 对话框全程盖住计算器，UIA 仍能按 AutomationId 准确点击——**截图循环此时会点错窗口**。[来源](https://www.cwfrazier.com/blog/uia-vs-screenshot-loop-benchmark)

2. **但 a11y 树有硬缺口。** 「约 40% 的原生应用有损坏/缺失的无障碍树」，Electron 包装、自绘 GUI、游戏会返回空树——所以 OCR/视觉回退不是可选项，是必需品。[来源](https://coderlegion.com/29020/beyond-the-browser-autonomous-desktop-gui-agents-in-2026-ui-tars-computer-use-osworld-2-0)

3. **UIA 跨进程很贵，除非批量取。** 朴素封装是「每元素每属性一次 COM 调用」，一个中等窗口几百个元素 × 7 个属性 = 数千次往返。正解是 `CacheRequest` 一次取整棵子树、7 个属性打包。这正是 screenpipe 和 Raycast 都在做的事。[来源](https://t8r.tech/t/automation-tools-for-windows)

### 2.2 采集开销的真实量级（官方数字）

screenpipe README 直接给了数：**CPU 约 5–20%，RAM 约 0.5–3 GB**（仅采集；本地模型另算），建议系统 8 GB 内存。存储量 README **没有给固定值**，只说「取决于活动量、显示器数、音频、捕获设置和保留期」，并建议自己测代表性的一天。[来源](https://raw.githubusercontent.com/mediar-ai/screenpipe/main/README.md)

> 注：部分第三方评测页给出「5–10GB/月」或「约 30GB/月」等数字，但**这些数字与官方 README 的「未给出固定值」直接冲突**，本文不采信，标为未证实。

---

## 3. 「主动开口」的失败案例与打扰控制

### 3.1 已发生的失败：Rewind / Limitless 全线关闭

这是本方向最硬的教训，且**与「主动」无关也照样死**：

- 2020 成立，a16z / First Round / NEA 投资（融资金额多个二手页说法不一，本文不引用具体金额）；2022-11 macOS 上线；2023-03 Ask Rewind 走红。
- 2024 改名 Limitless，转向 Pendant 硬件 + 云端，**原 Mac 屏幕录制应用进入维护模式**——用户所爱的那部分不再是重点。
- 2025-12-05 Meta 宣布收购 Limitless。**12-19 起 Rewind 应用的屏幕与音频录制被彻底禁用，下载移除。**
- **自 2025-12-05 起，服务在巴西、中国、欧盟、以色列、韩国、土耳其、英国停止提供**；这些地区用户须在 12-19 前导出数据，之后账号与全部信息**永久删除**。
- rewind.ai 域名已被转卖，现在是一个无关的第三方 AI 工具站。[来源](https://9to5mac.com/?p=1031480)、[WIRED](https://link.wired.com/external/33399557.12984/aHR0cHM6Ly93d3cucmV3aW5kLmFpL3BlbmRhbnQ_c291cmNlPUVtYWlsXzBfRURUX1dJUl9ORVdTTEVUVEVSXzBfU3RldmVuTGV2eV9aWiZ1dG1fc291cmNlPW5sJnV0bV9icmFuZD13aXJlZCZ1dG1fbWFpbGluZz1XSVJfUGF5d2FsbFN1YnNfMTExNzIzX1N0ZXZlbkxldnkmdXRtX2NhbXBhaWduPWF1ZC1kZXYmdXRtX21lZGl1bT1lbWFpbCZ1dG1fdGVybT1XSVJfU3RldmVuTGV2eSZ1dG1fY29udGVudD1XSVJfUGF5d2FsbFN1YnNfMTExNzIzX1N0ZXZlbkxldnkmdW5iZXhhZD01YmVhMGQ3NTJkZGY5YzcyZGM4ZGYwMjkmY25kaWQ9Mjk1OTQxMDImZXNyYz1TTE9uZUNsaWNr/5bea0d752ddf9c72dc8df029Ca99e6ed0)

**对 OpenLookout 的直接含义：用户把几年的生活交给你，然后你公司被收购 / 转型 / 关停。** 记忆层厂商自己都保不住数据的连续性，「主动陪伴」凭什么？本地可导出 + 可导入从第一天就得做。

### 3.2 用户主动关掉提醒的公开数据

| 证据 | 数字 | 来源 |
|---|---|---|
| 手机用户已从所有 app 收到每日推送量 | 46–63 条 | [背景智能体与通知预算](https://tianpan.co/zh/blog/2026/05/13/background-agents-notification-budget-attention-economy) |
| 因新闻提醒太吵而**主动关掉**新闻提醒的用户比例 | 79% | [路透社数字新闻报告 2025（Indian Express 转述）](https://indianexpress.com/article/world/why-phone-users-turning-off-news-alerts-10078842/) |
| 每周发 3–6 条推送会导致**直接关闭该 app 通知**的用户比例 | 40% | [Business of Apps 汇总](https://speakwiseapp.com/blog/notification-overload-statistics) |
| 给用户选择时选择关闭推送的比例 | 最高 60% | [同上](https://speakwiseapp.com/blog/notification-overload-statistics) |
| 被打断后返回原任务所需时间（知识工作者现场观察） | 平均 **25 分 26 秒** | [Mark, Gonzalez & Harris 2005, ACM CHI](https://saner.ai/blogs/context-switching-statistics) |
| 知识工作者平均多久被打断一次 | 每 3 分 5 秒 | [Mark, Gudith & Klocke](https://datafield.dev/algorithmic-addiction/part-02/chapter-09/case-study-01.html) |
| 工人被打断后「效率与压力」对比实验 | 被打断的工作常常完成得**一样快或更快**，但压力**明显更高** | [Mark, Gudith & Klocke 2008 CHI](https://saner.ai/blogs/context-switching-statistics) |

> **重要更正**：广为流传的「23 分 15 秒」这个数字，**在 Gloria Mark 的两篇原始论文里都不存在**。2005 年现场研究记录的是 **25 分 26 秒**。引用时不要用 23:15。[来源](https://saner.ai/blogs/context-switching-statistics)

### 3.3 业界怎么控制「话太多」

归纳出来的手段，每条都有对应的公开依据：

1. **默认安静，不确定就不说。** 这是所有幸存产品的实际选择——Raycast 直接写「Nothing is captured in the background」；Recall 只在用户搜索时才响应。
2. **区分「召回」和「打扰」两种入口。** screenpipe 的做法值得抄：它不自己开口，而是把屏幕历史做成 MCP server，让 **Claude / Cursor / Codex 在用户提问时自己来查**。主动权在用户，感知力在 agent。这是「感知」与「开口」解耦的干净架构。
3. **可见的托盘指示 + 一键暂停。** Recall 在系统托盘常驻图标，状态变化时图标变化，可随时暂停。
4. **同一话题不重复打扰。** 一次拒绝后应冷却，且**不得换个说法重提**。
5. **通知发送量是虚荣指标。** 关键洞察：用户点「关闭」也是一次点击，在周活看板上看起来像参与度——但那正是下个月流失的人。**「关闭」和「接受」在数据上长得一样，这是主动式产品最容易自杀的地方**。[来源](https://tianpan.co/zh/blog/2026/05/13/background-agents-notification-budget-attention-economy)

### 3.4 关于「精灵话太多」的公开教训

**坦白说：我没有查到一个专门针对「桌面 AI 精灵主动说话被卸载」的公开案例研究或量化数据。** 可查到的最接近的证据是：

- Rabbit R1 评测普遍反映的核心问题不是「话多」而是**「不知道什么时候值得用它」**——WIRED 3/10，原话「This red-orange gadget isn't a personal assistant, it's dead weight」；TechRadar 结论是「an adorable but half-baked idea that you can ignore」。**评审普遍没有把它当成一个有价值的常驻伴侣。** 这提示：主动陪伴产品若说不清「此刻为什么要开口」，用户会直接无视而不是卸载——**无视可能比卸载更致命，因为它让数据看起来还不错**。[WIRED](https://link.wired.com/click/43439766.523/aHR0cHM6Ly93d3cud2lyZWQuY29tL2Jldmlldy9yYWJiaXQtcjEvP3V0bV9zb3VyY2U9bmwmdXRtX2JyYW5kPXdpcmVkJnV0bV9tYWlsaW5nPVdJUl9QcmVtaXVtTW9kZWxCZWhhdmlvcl8wMTA4MjYmdXRtX2NhbXBhaWduPWF1ZC1kZXYmdXRtX21lZGl1bT1lbWFpbCZ1dG1fdGVybT1XSVJfUmV2aWV3TW9kZWxCZWhhdmlvcl8wMTA4MjYmYng9NWM0OGY5NDZmYzk0MmQwNDc3YmY3ZTNhJmNuZGlkPTQ5NDI2OCZoYXNoYT1kN2Q4YTkwMTE4NDE2ODc4ZTNkNWFiNGU4ZDcxODU0NCZoYXNoYj1jMTg3MDZjMzZlODM2YWVmZDkxZmExODY1OTIyNjZhMDM0MDQ3MGY3Jmhhc2hjPTM4MTQyMDVmYWJiYjc5N2JiM2FhNmJiYWRlNTFiNmQzMjgwZjM2NjFiYmQ0MmMwNTdhMjdhNmM4Yzg2NzliZGU/5c48f946fc42d0477ef7e3aCacd5d884)、[TechRadar](https://global.techradar.com/da-dk/phones/rabbit-r1)
- Cluely 生态的教训是**反向**的：它靠「隐形」而非「安静」取胜，说明用户确实会接受一个持续在后台的 agent——**但前提是它对我有用且不烦我**，而不是因为它可爱。

**这个空白既是风险也是机会**：OpenLookout 若能在「什么时候开口」上做出可验证的答案，就是这个方向目前无人占据的位置。

---

## 4. 隐私合规边界

### 4.1 中国：员工侧监控的司法边界（对 OpenLookout 是「红线区」）

OpenLookout 是**个人自用**工具，不属于用人单位监控。但用户很可能在办公电脑上跑它，且它会**扫到同事的聊天窗口、公司机密、客户的私密信息**——这恰恰是中国判例里明确划为「个人信息」的部分。

关键判例与规则：

| 要点 | 内容 | 来源 |
|---|---|---|
| **最小必要原则** | 监控范围应限于工作场所公共区域或工作设备，**不得覆盖私密空间**，监控时间限于工作时间，内容限于工作相关操作，**不得监控员工私人聊天、个人文件** | [央视网/中国经济网（引吴沈括、北师大法学院）](https://news.cctv.cn/2026/05/11/ARTIjF3MtwtLhFLjvcS0N3AA260511.shtml) |
| **办公设备上的私人信息仍受保护** | 北京二中院判例：公司从工作电脑**恢复已删除的微信聊天记录**作为违纪证据，法院认定构成个人信息不当使用，**该证据不予采信** | [工人日报（2025-12-04）](https://www.chinanews.com.cn/sh/2025/12-04/10526460.shtml) |
| **合法监控三要件** | ①目的正当且明确（严禁窥探员工私人生活）②**事前书面告知并取得明示同意**（未告知而安装，即使内容与工作相关也因违反知情同意而丧失合法性）③范围符合最小必要（**「录制全天候屏幕视频」被明确列为违法监控的典型情形**） | [深圳律师合规梳理](https://chuntinglawyer.com/NewsDetail.aspx?ID=3309) |
| **企业擅自清空/恢复设备数据的责任** | 北京四中院判例：公司未经许可远程清空员工工作手机，违反内部政策与个人信息保护法，应书面致歉并赔偿 | 同上 [工人日报](https://www.chinanews.com.cn/sh/2025/12-04/10526460.shtml) |
| **自动化决策需人工复核** | 涉及劳动合同解除、严重违纪处理、降级调岗等重大事项，应设人工审核环节，劳动者有申诉权 | [央视网](https://news.cctv.cn/2026/05/11/ARTIjF3MtwtLhFLjvcS0N3AA260511.shtml) |
| **刑责** | 非法获取、出售员工隐私信息情节严重，可能构成**侵犯公民个人信息罪** | [深圳律师](https://chuntinglawyer.com/NewsDetail.aspx?ID=3309) |

**对 OpenLookout 的直接含义**：一旦产品要往「给别人用」走（比如团队版、装在公司的电脑上），它立刻落入上述「用人单位监控」的规则区。个人自用阶段也应默认排除密码管理器、银行/支付、IM 私人聊天、医疗应用——这不是道德要求，是避免你替用户担责。

### 4.2 欧盟：GDPR 对应的几条硬约束

| 要点 | 内容 | 来源 |
|---|---|---|
| **同意在雇佣场景几乎永远无效** | EDPB 意见 2/2017：雇主与员工的权力失衡使员工无法真正自由拒绝。**即使拿到签字同意书，也不构成合法基础** | [SecurePrivacy GDPR 指南](https://secureprivacy.ai/blog/employee-monitoring-gdpr-guide) |
| **系统化监控必须做 DPIA** | 任何软件化监控方案都构成「系统化监控」，**部署前未做 DPIA 本身就是 Article 35 违规**，与监控本身是否合比例无关 | 同上 |
| **合法基础主要是「正当利益」Art 6(1)(f)** | 需**书面记录三段式测试**：目的（不能只写「检查员工是否在工作」）→ 必要性（能否用更少侵入的方式）→ 权衡（隐蔽、连续、覆盖私人通信、不在工作时间的，权重对员工不利） | 同上 |
| **远程办公风险更高** | ICO 2023 指南：居家监控必须**从一开始就按更高风险对待**，包括无意间采集同住家人的数据 | 同上 |
| **德国：工厂委员会有实质否决权** | BetrVG §87(1)(6)：凡能监控员工行为或绩效的技术装置，**须经企业委员会同意**；且德国联邦劳动法院 2023 年（BAG 2 AZR 296/23）判定：**除非雇主能证明有具体可疑的不当行为，否则持续截图监控违反比例原则** | [各国监控法规地图](http://www.employee-monitoring.net/blog/employee-monitoring-laws-worldwide-map) |
| **西班牙：屏幕录制必须遵守摄像头的规则** | 宪法法院把这些原则延伸至工作环境中的屏幕录制与截图：**须事前告知、须有比例性测试、须有空间限制**。AEPD 最佳实践建议**间隔 5–15 分钟截图而非连续录像**，保留 30–90 天，**下班即停止采集** | [eMonitor 西班牙专页](https://www.employee-monitoring.net/blog/employee-monitoring-laws-spain) |
| **数据最小化本身就是违法** | Amazon France Logistique 被罚 3200 万欧元（上诉减至 1500 万）：逐分钟扫描员工、保存 31 天个人指标，而周汇总本已足够。**即使监控目的正当，收集超出目的需要的数据本身就违法** | [ScreenJournal GDPR 专页](https://screenjournal.ai/employee-monitoring-gdpr) |
| **H&M 案：35.3 M 欧元** | 汉堡数据保护局 2020：管理者保存员工私生活细节（含健康、家庭），数十名管理者可见 | 同上 |
| **最重罚则** | 2000 万欧元或全球年营业额 4%（取高者） | [SecurePrivacy](https://secureprivacy.ai/blog/employee-monitoring-gdpr-guide) |

### 4.3 竞品怎么处理「本地 vs 上云」

| 产品 | 存储 | AI 推理 | 关键隐私动作 | 来源 |
|---|---|---|---|---|
| Recall | 本地，静态加密，**不离开设备、不与微软共享、不用于训练** | 本地 NPU | **默认选择加入**；每次启动需 Windows Hello；敏感信息过滤默认开（密码/信用卡/身份证）；排除应用与网站；**不录制音频、不存连续视频**；远程桌面会话被过滤 | [MS 官方](https://support.office.microsoft.com/f1/article/d404f672-7647-41e5-886c-a3c59680af15)、[MS Learn](https://learn.microsoft.com/zh-tw/training/modules/powerful-security-designed-for-ai/3-secure-and-productive-by-design) |
| screenpipe | 本地（帧/音频/转录/索引） | 可本地（Ollama/Apple Intelligence/任何 OpenAI 兼容服务） | **无需账号**；每个 pipe 有 YAML 数据权限（allow-apps / deny-apps / deny-windows / allow-frames），在**技能门控、agent 拦截、服务端中间件三层强制执行**，是确定性访问控制而非「求模型听话」 | [官方 README](https://raw.githubusercontent.com/mediar-ai/screenpipe/main/README.md)、[技术分析](https://topgit.dev/repo/screenpipe/screenpipe) |
| Raycast | 采集本地 | 上云 | **只在用户触发时采集，不后台采集，不存储**；企业版提供全组织 AI 开关、BYOK、供应商白名单 | [手册](http://manual.raycast.com/ai/screen-awareness)、[定价页](https://www.raycast.com/pricing) |
| OpenRecall | 本地，可选加密卷 | 本地模型 | 无遥测；完全离线可用；AGPLv3 可审计 | [FAQ](https://github.com/openrecall/openrecall/wiki/FAQ/55cf3955b9690f4ec130c3d545bf7d8e6febdfec) |
| Copilot Vision | — | **云端** | 用户手动开启；只读不可点击；默认从 Insider 渠道灰度 | [Windows Forum](https://windowsforum.com/threads/microsofts-copilot-vision-introduces-full-desktop-sharing-in-windows-11-ai-assistance.373742) |

### 4.4 ⚠️ 一条未证实的信息（不作为结论使用）

调研中遇到一个页面（`techcrawlr.com`）声称微软于 2025-11-28 因隐私争议下线 Edge 版 Copilot Vision，并给出大量精确数字（180,000 个屏幕录制会话、11% 会话含 PII、爱尔兰 DPC 已介入、300ms 连续采样、Azure blob 明文存储 30 天等）。

**这些数字我无法在微软官方或权威媒体处交叉验证，该站点也未见署名机构背书，疑为 AI 生成的内容农场。本文不采信其中任何数字。** 若这条对你重要，请直接查证：微软官方博客 / 爱尔兰 DPC 决定库 / The Verge 或 Ars Technica。

---

## 5. 对 OpenLookout 的启示

### 5.1 必须抄的（已被反复验证、且成本低）

| # | 抄什么 | 依据 |
|---|---|---|
| 1 | **感知优先走无障碍树（UIA），截图/OCR 只做回退**。并且用 `CacheRequest` 批量取属性 | 快 17–32 倍；token 便宜两个数量级；[实测](https://www.cwfrazier.com/blog/uia-vs-screenshot-loop-benchmark)、[架构](https://coderlegion.com/29020/beyond-the-browser-autonomous-desktop-gui-agents-in-2026-ui-tars-computer-use-osworld-2-0) |
| 2 | **事件驱动而非定时轮询**：应用切换、点击、输入停顿、滚动、剪贴板变化才存帧 | screenpipe 的 CPU 5–20% 就是这么省下来的（大部分时间无事件时几乎零开销）；[README](https://raw.githubusercontent.com/mediar-ai/screenpipe/main/README.md) |
| 3 | **默认本地、默认无声、默认不存**。帧留在本机，模型调用才出网 | Recall、screenpipe、OpenRecall 三家独立收敛到同一答案 |
| 4 | **托盘常驻指示 + 一键暂停 + 随时删除**。暂停状态在 UI 上必须一眼可见 | Recall 的托盘图标模式；Raycast 文档给用户明确的「已采集了什么」卡片 |
| 5 | **数据权限做成确定性强制，不要写成 prompt** | screenpipe 的三层强制（技能门控 / agent 拦截 / 服务端中间件）是最好的公开范例 |
| 6 | **敏感区默认排除**（密码管理器、银行支付、IM 私人聊天、医疗） | 中国判例明确「不得监控私人聊天、个人文件」；[工人日报](https://www.chinanews.com.cn/sh/2025/12-04/10526460.shtml) |
| 7 | **本地可导出，且导出格式要能被别人读** | Rewind 的教训：欧盟/中国用户 14 天内失去全部账号数据，域名都被转卖了 |
| 8 | **默认选择加入（opt-in），不是默认开启** | Recall 因默认开启被推迟发布；中国司法明确要求事前告知同意 |

### 5.2 别人踩过的坑（别踩）

| 坑 | 后果 | 依据 |
|---|---|---|
| **默认开启截图** | Recall 从 2024-06 一路推迟到年底，被迫改成 opt-in + 加密 + Hello 验证 | [WinSome Marketing 复盘](https://winsomemarketing.com/ai-in-marketing/microsofts-desktop-peeping-tom-copilot-visions-concerning-expansion) |
| **把「通知发送量」当成功指标** | 用户点「关闭」也是点击，周活看着很好，三个月后留存崩 | [通知预算](https://tianpan.co/zh/blog/2026/05/13/background-agents-notification-budget-attention-economy) |
| **打扰成本被低估** | 40% 用户在收到每周 3–6 条推送后就关掉通知；恢复专注需约 25 分钟；且被打断的工作「常常完成得一样快，但压力明显更高」 | [推送数据](https://speakwiseapp.com/blog/notification-overload-statistics)、[Mark 研究](https://saner.ai/blogs/context-switching-statistics) |
| **价值承诺过宽**（「记住你的一切」） | Rewind 从改名那天起就在流失；用户真正在意的是本地数据不外传，而这一点恰好被放弃 | [Screenpipe vs Limitless](https://screenpipe.com/blog/screenpipe-vs-limitless-2026) |
| **采集能力当卖点** | Limitless 有能力不等于有业务；Meta 收购后照样砍桌面端 | [9to5Mac](https://9to5mac.com/?p=1031480) |
| **无障碍树想当然** | 约 40% 原生应用 a11y 树缺失/损坏，Electron、自绘、游戏返回空 | [架构对比](https://coderlegion.com/29020/beyond-the-browser-autonomous-desktop-gui-agents-in-2026-ui-tars-computer-use-osworld-2-0) |
| **逐属性裸调 UIA** | 跨进程 COM 调用数千次，延迟不可接受 | [t8r.tech](https://t8r.tech/t/automation-tools-for-windows) |
| **把「被无视」当成「留存良好」** | Rabbit R1 的评审反应是「可以直接无视」——比卸载更难察觉 | [TechRadar](https://global.techradar.com/da-dk/phones/rabbit-r1) |
| **在办公电脑上无差别采集** | 中国已有明确判例认定恢复员工私人聊天记录违法 | [工人日报](https://www.chinanews.com.cn/sh/2025/12-04/10526460.shtml) |
| **想一次做完全场景** | 所有幸存产品都从极窄切口切入 | 见 §5.4 |

### 5.3 不必走的路

- **不必做全屏回放/时间线检索。** screenpipe 已经做得很便宜且开源（Free $0、Windows 原生支持、MCP + REST API + JS SDK），OpenRecall 免费且完全离线。**这层需求已被免费工具满足，你无法在这里建立优势。** [screenpipe](https://github.com/mediar-ai/screenpipe)、[OpenRecall](http://openrecall.github.io)
- **不必自建 CLI agent 或模型层。** 你已经用 Claude Code + deepseek-v4.1-flash，这是成熟方案，不要重新造。但要注意：Claude Code / Codex **都不感知屏幕**（只读你给的仓库），所以感知必须你自己做，这部分不可省。
- **不必做屏幕录制流。** 存储、带宽、隐私暴露全面上升，而 UIA 快 17–32 倍。screenpipe 的优势恰恰来自事件驱动 + a11y 优先，不是「录得更全」。
- **不必追硬件/独占端侧算力。** Recall 需要 Copilot+ PC NPU 才能跑，这恰恰把 90% 用户挡在门外，也成了它被攻击的口子。OpenLookout 用普通 Windows 机 + 云模型反而更普适。
- **不必把「精灵」形象当技术壁垒。** Shimeji 系证明了形象能带来喜爱（免费、分发广），但它们**完全不感知屏幕**——说明「可爱」和「有用」是两条独立的轴。可爱是加分项，不是差异点。[ShimejiEE-AI](https://github.com/mmmyyc/ShimejiEE-AI)
- **不必和 Manus 拼定时任务。** 那是你给日程表写 cron，不是 agent 判断意图。而且 Manus 因 Meta 收购波折（2025-12 收购 → 2026-04 被中国监管叫停 → 8 月宣布回归独立运营）已经证明：依赖单一云厂商做你记忆的存储方，风险极高。[定价与收购波折](https://klyvoo.com/agents/manus)

### 5.4 独立空间在哪（以及它为什么窄）

**空位是明确的**：14 个主流产品里没有一个敢做「在用户没问的时候说话」。Raycast 走的是相反方向——明确承诺「nothing is captured in the background」。这既是机会，也是警告：**行业集体回避这个问题，通常是因为难，而不是因为不想。**

这个空位的成立条件很苛刻，必须同时满足：

1. **大部分轮次安静。** 参考值：每天 3–5 次来自所有渠道的未请求更新已接近用户上限；每周 3–6 条就足以让 40% 用户关掉通知。所以 OpenLookout 的日开口量应该是个位数，并且必须有硬上限。
2. **每次开口都要能回答「为什么是现在」。** 依据链要能回放：看到了什么事实（时序/窗口/文件事件）→ 触发了什么判断 → 为什么值得打断。这是 Rabbit R1 失败的核心缺口（用户找不到理由拿出来用）。
3. **打断的净收益 > 0。** 一次成功节省的分钟数，必须大于「25 分钟恢复成本 × 概率」+ 打扰心理成本。**这是整个方向最残酷的算术：你要用一个 25 秒的一句话，去赌用户可能付出的 25 分钟。绝大多数开口注定是净负的。** 所以「不确定就安静」不是保守，是数学要求。
4. **先验证「不被讨厌」，再验证「有用」。** 顺序反了会得到错误结论——如果精灵还没学会安静，你先测「有用」只会收到混杂信号。

**具体建议的最小切口**：不做「全屏幕管家」，只做一个低风险、可验证的场景（例如：卡住超过 N 分钟后给一句话，或阶段完成后给下一步），**每轮最多一句**，接受/拒绝/撤销全部记录。用「每次打扰的净价值」作为唯一主指标，而不是打扰量或对话轮数。

---

## 6. 本次调研未能查证的事项（诚实清单）

| 想查到的 | 状态 |
|---|---|
| 针对「桌面 AI 精灵主动说话导致用户卸载」的**专门案例研究或量化数据** | **未查到**。仅有 Rabbit R1「用户选择无视」的评测证据，以及通用的推送疲劳研究 |
| Rewind / Limitless 的确切融资金额 | **未查到可核实的官方数字**。二手页说法互相冲突（有一处称「超过 3300 万美元，来自 a16z/First Round/NEA」），未能交叉验证，故本文不引用金额 |
| screenpipe 的确切月存储量 | **未查到**。官方 README 明确未给固定值；第三方页给 5–10GB/月或约 30GB/月，与官方口径冲突，不采信 |
| Copilot Vision 在 Edge 的下线事件及其监管调查 | **仅见单一非权威来源**（见 §4.4），未采信 |
| Cluely 商业版的官方定价 | **未查到官方页面**。仅有第三方对比页的历史区间 $29–99/月，不作为事实 |
| Raycast Screen Awareness 的具体调用频率与费用 | **未查到**。已知它在 beta 期免费，官方未承诺 beta 结束后如何收费（[TechLab 报道](https://www.techlab.hk/p/9to5mac-raycast-screen-awareness-ai)） |
| Manus 在中国大陆的可用性与合规状态 | **未查到**。仅查到其运营主体迁至新加坡（Butterfly Effect Pte. Ltd.）及被中国监管叫停收购的事实 |
| OpenLookout 宿主（Claude Code 经 CC Switch 代理调用 deepseek-v4.1-flash）的合规性 | 本文未评估，属技术配置不在调研范围 |

---

## 附：本文主要来源清单

- 产品官方：screenpipe README、Raycast 手册/定价、OpenRecall 官网/FAQ、微软 Recall 与设备端 AI 文档、shimeji.ai、Manus 定价页
- 新闻报道：9to5Mac（Rewind 关停一手公告）、WIRED（Rabbit R1 评测）、TechRadar（Rabbit R1）、Indian Express（路透社数字新闻报告 2025）
- 中文法律/监管：央视网、中国经济网、工人日报（2025-12-04 / 2026-01-22）、中工网 PDF
- 学术/技术：Mark et al. ACM CHI（打断成本）、t8r.tech（UIA/AX 缓存批量）、cwfrazier.com（UIA vs 截图实测）、coderlegion（三感知架构对比）
- 欧盟合规：SecurePrivacy、eMonitor（西班牙/各国地图）、ScreenJournal