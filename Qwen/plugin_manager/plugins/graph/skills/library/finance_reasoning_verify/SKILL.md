---
name: finance_reasoning_verify
description: 金融 模型 评测 校验 公式 计算 口径 概念 推理
---

# 金融推理校验闸门

对 quantitative 分支独立重算公式、结果、单位、舍入和期间；对 conceptual 分支核对定义与推断。两者都验证 domain=finance、来源、节点引用、无环、结论可达性和专家约束。checks 必须给实际依据；任一失败拒绝，不输出成功效果。

输入：requirements, evidence_packet, finance_context, reasoning_bundle。输出：verified_reasoning。完整字段约束见 contract.json。

前置条件：reasoning_ready(finance)。成功效果：reasoning_verified(finance)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
