---
name: legal_application_verify
description: 法律 模型 评测 校验 法域 时效 条文 要件 例外 推理
---

# 法律适用校验闸门

独立核对法域、适用时点、规则效力、事实与要件、例外和结论。验证 domain=legal、kind=rule_application、引用有效、图无环、结论可达、假设与专家约束。存在歧义或来源缺失时拒绝；checks 必须记录实际核验依据，不伪造通过。

输入：requirements, evidence_packet, legal_scope, reasoning_bundle。输出：verified_reasoning。完整字段约束见 contract.json。

前置条件：reasoning_ready(legal)。成功效果：reasoning_verified(legal)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
