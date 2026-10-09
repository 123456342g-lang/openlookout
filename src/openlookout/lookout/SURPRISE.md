# 惊喜门控计分（V1）

实现：`lookout/surprise.py`。由 `python3 -m lookout.v1` 在求解之后、出卡之前调用。

## 目标

只让「用户说不出、也没察觉」的需求变成卡片；提醒、意料中的杂务、纯观察、新闻/机会一律不出。

## 硬拒绝（直接出局）

| 条件 | 例子 |
|---|---|
| 类型 ∈ site_rhythm / last_minute / duplicate_copies | 每周去某网页、最后一刻提交、多处同名副本 |
| 类型 ∈ world_signal / opportunity / switch_tax / agent_ledger | 非 V1 产品路径 |
| 求解状态 ∈ reminder_only / omit / failed | 只有日历提醒、无法交付 |
| verify_deid.mode == observation_only | 无成品 |
| 无 artifacts | 空交付 |

## 必须同时成立

1. **行为可量化**：`facts` 中至少 2 个数值字段 → `evidence_strength > 0`
2. **潜在不一致信号** `latent_signals` 非空：
   - `manual_summary`：手填汇总与明细不一致（`cells_differ > 0`）
   - `version_sprawl`：名叫最终/final 的不是最新
   - `numbered_series`：≥2 期有多文件 **且** ≥2 种命名写法（流程税）
   - `report_mismatch` / `numeric_drift` / `duplicate_charge` / `price_change`
   - `periodic_assembly`：平均 ≥25 分钟的周期性手工拼装
   - `copy_paste_friction`：有 pending 文档且粘贴次数高
   - `repeated_download`：磁盘上仍堆着 ≥3 份相同大小副本
3. **惊喜分** ≥ 0.35：
   ```
   surprise = evidence_strength × latent_gap × (1 − expectedness)
   ```
4. **主指标** `metric` 可写出（卡片上展示的那个数字）

## 意料中的杂务（高 expectedness）

`recurring_files` / 无堆积的 `repeated_download` / `deadline` 等：即使用户有明显节律，也不算「没察觉的需求」。

## 每日上限

通过门控后按惊喜分降序，最多 **3** 张。

## 反馈降权

`lookout/feedback_rules.json`：匹配 kind + 路径正则后乘因子。考勤 `manual_summary` 默认 ×0.05（视为不出卡）。

## 趋势加成

求解结果若附带 `trends`（catalog 内已 verified 的 url+date），排序分 `ranking = surprise × feedback × 1.4`。
无行为、无成品的趋势不会单独成卡。
