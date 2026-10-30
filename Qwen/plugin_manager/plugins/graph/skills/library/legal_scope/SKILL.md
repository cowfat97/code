---
name: legal_scope
description: 法律 模型 评测 法域 时点 效力 规则 例外
---

# 法律适用范围核定

依据明确法域和任务时点核对规则适用范围、效力期间、构成要件与例外，输出排除规则及理由。legal_context.as_of 必须与需求一致。资料没有效力依据或法域不符时停止；禁止补写真实法条、判例或将虚构规则描述为现行法律。

输入：requirements, evidence_packet, legal_context。输出：legal_scope。完整字段约束见 contract.json。

前置条件：requirements_ready(legal), evidence_ready(legal)。成功效果：legal_scope_ready(legal)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
