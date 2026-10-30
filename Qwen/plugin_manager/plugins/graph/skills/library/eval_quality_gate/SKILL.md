---
name: eval_quality_gate
description: 金融 法律 模型 评测 质量 闸门 证据 答案 覆盖 格式
---

# 评测题包质量闸门

实际执行 source、reasoning、answer、coverage、format 五类检查，每类恰好一份通过证据。检查题量、能力覆盖、域一致、时点、题答对应、引用存在、推理连通和无环、评分规则以及专家约束。任何检查失败必须拒绝并给失败依据；输出 Schema 不能替代这些语义校验。

输入：requirements, evidence_packet, verified_reasoning, questions, answers。输出：quality_report。完整字段约束见 contract.json。

前置条件：answers_ready(d), evidence_ready(d), reasoning_verified(d)。成功效果：quality_passed(d)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
