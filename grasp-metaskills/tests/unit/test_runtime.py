from grasp_metaskills.contracts import NodeResult, Skill, SkillContract, SkillNode
from grasp_metaskills.verification import verify_input, verify_result


def test_missing_precondition():
    node = SkillNode(id="a", preconditions=["ready"])
    assert verify_input(node, {}, []).category == "precondition"


def test_effect_requires_observation():
    node = SkillNode(id="a", effects=["done"])
    assert not verify_result(node, NodeResult()).passed
    assert verify_result(node, NodeResult(observed_effects=["done"])).passed


def test_schema_rejects_invalid_output():
    skill = Skill(
        id="a",
        name="A",
        contract=SkillContract(output_schema={"type": "object", "required": ["value"]}),
    )
    result = verify_result(SkillNode(id="a", skill=skill), NodeResult())
    assert result.category == "output_schema"
