---
name: eval_evidence
description: 金融 法律 模型 评测 资料 来源 证据 引用 提取
---

# 评测来源证据提取

从 source_documents 提取与能力目标有关的可追溯事实和规则，逐条保留 source_id、locator 和适用时间。不得依靠模型记忆编造来源，虚构资料必须保持 synthetic=true。列明排除资料和证据局限。金融时点、法律效力的业务判断由后续领域 Skill 完成。

输入：requirements, source_documents。输出：evidence_packet。完整字段约束见 contract.json。

前置条件：requirements_ready(d)。成功效果：evidence_ready(d)。

这是可编排的原子能力契约，仅用于规划和编译验证，未绑定执行工具。Skills 描述和 Schema 不会自动执行以上业务规则；实际执行必须绑定真实工具及验证器，只有实际完成并验证后才能报告效果。不得凭初始条件伪造中间完成或闸门通过。
