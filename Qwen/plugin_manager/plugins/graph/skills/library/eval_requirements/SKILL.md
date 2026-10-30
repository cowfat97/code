---
name: eval_requirements
description: 金融 法律 模型 评测 出题 需求 能力 难度 约束，生成统一需求规格
---

# 评测需求约束整理

整理任务目标、能力、题量、难度、截止时间和专家约束，补充可检查的验收标准。request.domain 必须与参数 d 相同。不得自行补齐缺失的法域、币种或资料；缺失关键信息必须拒绝。保留 synthetic 标记，不声称已出题。

输入：request。输出：requirements。完整字段约束见 contract.json。

前置条件：task_requested(d)。成功效果：requirements_ready(d)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。

## 编译验证入口

examples/ 下 finance_quantitative.json、finance_conceptual.json 和 legal.json 可直接作为 Plugin.prepare 的请求。未提供手工节点 proposal，编译器依据契约选择步骤和绑定数据。每个示例只处理一个领域；金融必须明确且仅选择一种模式。initial_conditions 是宿主提供的可信事实，不能从用户原话直接照抄。

边界：编译器检查图结构、前置事实和字段 Schema，不交叉核对 request.domain 与参数 d，也不拒绝同时声明两种金融模式的初始事实。调用方应保持这些值一致；执行器必须再次校验领域、模式及全部业务规则。示例仅证明多节点编译和数据绑定，不证明真实出题质量。
