---
name: eval_answer_rubric
description: 金融 法律 模型 评测 答案 评分 标准 rubric
---

# 评测参考答案与评分规则

逐题生成可由核验推理推出的参考答案、推理依据及可执行评分点。question_id 一一对应题目；评分点分数为正且规则明确，避免主观空泛标准。所有引用必须存在。若题干不足、答案多解或推理不支持答案则停止，不补造前提。

输入：requirements, questions, verified_reasoning。输出：answers。完整字段约束见 contract.json。

前置条件：questions_ready(d), reasoning_verified(d)。成功效果：answers_ready(d)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
