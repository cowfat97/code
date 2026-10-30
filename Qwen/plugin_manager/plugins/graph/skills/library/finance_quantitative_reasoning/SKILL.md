---
name: finance_quantitative_reasoning
description: 金融 定量 计算 模型 评测 公式 财务 推理 DAG
---

# 金融计算推理图构建

仅处理显式选择的定量任务，kind=quantitative。将数据事实、公式、代入和计算结论拆成推理节点；input_refs 引用证据或上游节点，edges 明确依赖。每个非源节点必须有输入，结论节点可追溯到证据，图必须无环。不得把这张题目推理图混同插件执行 DAG。

输入：requirements, evidence_packet, finance_context。输出：reasoning_bundle。完整字段约束见 contract.json。

前置条件：finance_context_ready(finance), quantitative_selected(finance)。成功效果：reasoning_ready(finance)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
