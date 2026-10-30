---
name: finance_normalize
description: 金融 评测 币种 单位 报表期间 指标口径 统一
---

# 金融指标口径统一

核对证据中的币种、单位、期间和指标定义，输出统一口径及来源。财务概念题同样需要明确适用定义。缺失换算依据、口径冲突或期间不明时停止，不自行猜测汇率、公式或指标。

输入：requirements, evidence_packet, financial_conventions。输出：finance_context。完整字段约束见 contract.json。

前置条件：requirements_ready(finance), evidence_ready(finance)。成功效果：finance_context_ready(finance)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
