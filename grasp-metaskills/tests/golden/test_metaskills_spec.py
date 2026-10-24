"""Source: MIT dcd3fb55 storage/git.rs sample_spec/render_skill_markdown."""

from grasp_metaskills import SkillContract
from grasp_metaskills.metaskills_spec import (
    normalize_spec,
    render_skill_markdown,
    skill_from_spec,
    spec_from_skill,
)


def sample_spec():
    return {
        "metadata": {
            "id": "test-skill",
            "name": "Sample Skill",
            "version": "1.0.0",
            "description": "Sample description",
            "requires": ["parse"],
            "provides": ["format"],
            "tags": ["text"],
        },
        "sections": [
            {
                "id": "intro",
                "title": "Introduction",
                "blocks": [{"id": "block-1", "block_type": "text", "content": "Hello"}],
            }
        ],
    }


def test_source_git_markdown_and_explicit_contract_mapping():
    spec = sample_spec()
    assert (
        render_skill_markdown(spec)
        == "# Sample Skill\n\nSample description\n\n## Introduction\n\nHello\n\n"
    )
    skill = skill_from_spec(spec, contract=SkillContract(effects=["ready(x)"]))
    assert skill.metadata["requires"] == ["parse"]
    assert skill.metadata["provides"] == ["format"]
    assert skill.contract.effects == ["ready(x)"]
    assert "format" not in skill.contract.effects
    exported = spec_from_skill(skill)
    assert exported["sections"] == spec["sections"]
    assert exported["metadata"]["requires"] == ["parse"]
    assert skill_from_spec(exported).contract == skill.contract


def test_markdown_code_fencing_matches_source():
    spec = sample_spec()
    spec["sections"][0]["blocks"] = [
        {"id": "code", "block_type": "code", "content": "x = 1  \n"},
        {"id": "fenced", "block_type": "code", "content": "```py\nx=2\n```\n"},
    ]
    out = render_skill_markdown(spec)
    assert "```\nx = 1\n```\n\n```py\nx=2\n```\n\n" in out


def test_unknown_fields_preserved_and_metadata_has_one_live_authority():
    spec = sample_spec()
    spec["custom"] = {"source_extension": True}
    skill = skill_from_spec(spec)
    skill.metadata["requires"] = ["updated-capability"]
    out = spec_from_skill(skill)
    assert out["metadata"]["requires"] == ["updated-capability"]
    assert out["custom"] == spec["custom"]
    assert normalize_spec(out)["format_version"] == "1.0"
