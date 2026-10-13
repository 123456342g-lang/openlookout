# 富上下文与出站权限：最小合成试验设计

2026-10-12；仅设计和离线合成验收，当前不接入生产采集或模型链路。

## 边界

观察、本地保留、配置模型处理、公共发布是不同权限。允许配置模型处理任务上下文不等于允许把屏幕正文、身份、私有路径或原始文档放进公共搜索。任务所需姓名、数值、单位、实体关联和依赖关系可在已有模型授权内保留，不靠一个敏感正则一律抹掉。凭据和会话 token 不能作为推理正文出站；模型认证 header 由 provider 单独管理。

既有配置模型授权继续适用，不自动换供应商、暂停 sprite 或删除历史。供应商保留、训练、区域和日志政策未核实时标为 `unknown`，不能标 `allow`。图片中凭据的检测能力同样是 `unknown`；沿既有图像授权路径处理，不能擅自改变模型授权语义，也不能声称图片已受保护。

## 单一逻辑边界

最终形态为 `prepare_outbound(payload, destination, authority, provenance)`，在最后序列化/发送前形成出站副本，不改 VISTA 本地原始观察。目的地至少区分 `configured_model`、`public_search`、`public_web`；未知目的地不默认归入模型。

边界必须覆盖：最新 CURRENT、反馈、历史小页、GUIDE/WORKING、agenda、工具结果和 shell 输出、history/inspect/read_pixels 图片、重试/流式请求、旧 Claude 容器入口，以及 `basic_web_search`/`basic_web_read`。公共搜索只发送公共 query；purpose/enough_when 留在本机，模型填写 purpose 不是发布授权证据。URL、重定向、请求头、DNS/HTTP 目的地也可能披露信息，private/unknown URL 不当作公共网页授权。未测试入口写 `uncovered`，不能声称全覆盖。

当前审计（不读真实历史、截图、`.env` 或 key）：session 整屏采集；直连 body 带图和工具结果；historyfacts activity 的 URL 未复用 `backfill.clean_url`；read_local 的文件名拒绝不保护所有工具输出；artifact 未见现行 TTL；旧 perceive 清理不在活动 children。

## 默认策略

`configured_model` 保留已有授权范围内的语义，凭据正文替换成稳定局部占位符，并记录检测种类/位置和能力 `unknown`。结构化认证字段、URL userinfo/敏感参数、常见 cookie/header 和已知格式应确定性处理；未知长字符串不能全部删掉。必须保持编号、数值、单位、公式和依赖边。实体脱敏若确需使用，采用一次任务内稳定、可区分映射，映射只在本机保留。

`public_search/public_web` 只接受公共来源证据或明确发布授权的投影；private/unknown 不因模型授权放行。可将缺口概括为公共概念后继续查询，但不能复制身份、私有正文或路径。混合字段须逐字段投影，未知策略不标 allow。

## 出站账本与本地保留

账本只记录随机 request ID、目的地类别、授权来源版本、来源类别/本地 provenance ID、字段路径、内容类型、编码字节数、decision、规则版本和覆盖状态；图片记录编码字节/宽高/保护能力状态，不记录像素。不得记录原文、真实 URL/path、查询词、token、原文散列或身份证/邮箱。JSON/base64 与正文编码字节分开。账本描述计划发送哪些类别和字节，不能证明供应商如何处理。

保留期限、模型处理权和公共发布权独立配置。手动删除先预览会话/来源、数量、笔记/快照引用和不可逆部分，再写操作日志；不可撤回部分不得声称可撤回。撤回模型权只阻止后续出站，不自动抹掉本地历史或远端副本。TTL、删除界面和远端删除尚未实现。

## 合成验收

与 outcome 回放复用采购差额 `75`、测量单位 `1000` 倍材料，并加入实体关联。对每例构造 rich、credentials_only、coarse 三个视图；独立算术/关联 oracle 验证 rich 与 credentials_only 保留相同问题证据，coarse 因粗暴替换失去实体关系。这只是数据保持验证，不是 AI 发现率或模型能力对照。验证数值、单位、公式/依赖未改变；凭据只使用合成标注，不能推导现实识别率。

后续待实现的 fake transport 验收顺序：凭据不在捕获正文；授权任务 PII/实体关系仍到达配置模型；public_search private/unknown 不出站；工具嵌套、历史图片、重试和流式都过同一边界；账本字节与抓包一致；本地原始材料未改变。本次没有 transport 接线，也没有发送真实请求。

本次已完成：`python docs/experiments/privacy_trial/validate_cases.py` 返回三例通过；采购差额75、单位1000倍和正确对照的算术与关联断言通过；credentials_only 未改变源记录与公式，合成凭据标注被移除；coarse 的收件人关联为未知；账本仅含字段和字节元数据。模型 rich/credentials_only 对照、真实凭据检测、抓包和生产覆盖都未实施。

图像能力另测合成截图（可见 secret 命中/漏检、误删文字、问题发现率；压缩、旋转、小字号、截断 token），未做前不能承诺 credential-free。现实 OCR、未知凭据、供应商政策、未接线入口和真人有用问题发现均未证实。
