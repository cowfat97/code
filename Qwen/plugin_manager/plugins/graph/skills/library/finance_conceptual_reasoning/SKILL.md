---
name: finance_conceptual_reasoning
description: 金融 概念 分析 模型 评测 定义 比较 推理 DAG
---

# 金融概念推理图构建

仅处理显式选择的概念任务，kind=conceptual。将定义、事实比较、适用条件和结论拆成可追溯推理节点。禁止为了出题虚造金融计算步骤；结论只能来自当前资料。检查节点引用、无环和证据覆盖，保留假设。

输入：requirements, evidence_packet, finance_context。输出：reasoning_bundle。完整字段约束见 contract.json。

前置条件：finance_context_ready(finance), conceptual_selected(finance)。成功效果：reasoning_ready(finance)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
