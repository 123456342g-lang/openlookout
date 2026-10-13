# 合成隐私验收

本目录只存合成材料，不接入 live，不读取用户历史、截图、.env 或 key。

运行：`python docs/experiments/privacy_trial/validate_cases.py`。

案例数值复用 outcome 的采购差额 75、体积单位 1000 倍；实体关联补例的导出行顺序故意不同。`cases.json` 的 instruction/oracle 用于人读与本地算术断言，不是模型盲测提示。模型盲测应使用 `replay_openworld.prepare_blind_fixture` 的 workflow/reference/release，不能把 oracle 送给模型。

脚本按合成标注构造三个视图，没有凭据识别器。凭据视图保持所有数值、单位、实体关联和依赖；粗暴视图把两个不同收件人均改成同一个 [PERSON]，独立关联 oracle 返回未知，证明单一替换会丢失关系。正确金额对照须为零差异。字节账本只输出字段名和编码字节等元数据，不保存正文。

这些是未来接线的离线契约。没有网络请求、生产覆盖、OCR 检测或供应商政策核验；通过不能证明 brain/session 已受保护、零泄漏或真实模型仍有帮助能力。
