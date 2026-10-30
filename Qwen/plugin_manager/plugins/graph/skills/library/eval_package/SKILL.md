---
name: eval_package
description: 金融 法律 模型 评测 题包 汇总 交付
---

# 评测题包汇总

仅汇总已经通过闸门的需求、证据、题目、答案评分和推理图；保留来源、synthetic 标志和质量报告。确认质量报告覆盖全部题目和五类闸门，输入领域与参数 d 一致；不得在打包时偷偷改题或补答案。输出是数据题包，不假设已写文件。

输入：requirements, evidence_packet, verified_reasoning, questions, answers, quality_report。输出：evaluation_package。完整字段约束见 contract.json。

前置条件：quality_passed(d), answers_ready(d), reasoning_verified(d)。成功效果：package_ready(d)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
