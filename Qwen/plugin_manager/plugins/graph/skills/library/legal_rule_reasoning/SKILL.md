---
name: legal_rule_reasoning
description: 法律 模型 评测 事实 要件 规则 例外 结论 推理 DAG
---

# 法律规则适用推理图构建

domain=legal，kind=rule_application。按事实认定、要件匹配、例外检查和结论拆分节点。引用 legal_scope 的规则及证据，不跳过不利事实、例外或冲突。推理图无环且结论有可追溯证据；无法排除多解时明确记录并停止单一答案生成。

输入：requirements, evidence_packet, legal_scope。输出：reasoning_bundle。完整字段约束见 contract.json。

前置条件：legal_scope_ready(legal)。成功效果：reasoning_ready(legal)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
