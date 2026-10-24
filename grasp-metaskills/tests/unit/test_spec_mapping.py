from grasp_metaskills import Skill, SkillContract, SkillDependency
from grasp_metaskills.metaskills_spec import skill_from_spec, spec_from_skill


def test_generic_skill_roundtrip_keeps_explicit_fields_without_recursive_provenance():
    original = Skill(
        id="work",
        name="Work",
        version="2.0",
        content="Arbitrary body",
        source="file:///skills/work",
        metadata={"custom": {"x": 1}},
        dependencies=[SkillDependency(id="base", version=">=1")],
        contract=SkillContract(effects=["done(x)"]),
    )
    document = spec_from_skill(original)
    restored = skill_from_spec(document)
    assert restored.content == original.content
    assert restored.source == original.source
    assert restored.dependencies == original.dependencies
    assert restored.contract == original.contract
    assert restored.metadata["custom"] == {"x": 1}
    assert spec_from_skill(restored) == document
    assert "metaskills_spec" not in document.get("grasp_metadata", {})
