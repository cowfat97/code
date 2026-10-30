---
name: eval_questions
description: 金融 法律 模型 评测 出题 题干 题型 能力
---

# 评测题目生成

仅以已核验推理和证据生成题干，保持领域一致、题量和难度目标，覆盖指定能力。题目引用真实存在的 source_ids 与 reasoning_node_ids，问题必须可回答且条件充分；不泄露标准答案，不添加证据外事实，不自行修改推理结论。

输入：requirements, evidence_packet, verified_reasoning。输出：questions。完整字段约束见 contract.json。

前置条件：reasoning_verified(d)。成功效果：questions_ready(d)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
