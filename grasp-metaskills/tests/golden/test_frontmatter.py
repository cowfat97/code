"""Port of verify.js [7], including commas inside multi-argument predicates."""

from grasp_metaskills.adapters import frontmatter_skills, manifest_skills


def test_frontmatter_comma_predicate_and_skipped():
    skills, skipped = frontmatter_skills(
        [
            {
                "name": "clean-object",
                "content": "---\nname: clean-object\ndescription: Clean an object\ngrasp:\n"
                '  params: [object]\n  precondition: ["holding(object)", "at(agent,sink)"]\n'
                '  effect: ["clean(object)"]\n---\nbody',
            },
            {"name": "no-grasp", "content": "---\nname: no-grasp\n---\nbody"},
        ]
    )
    assert skills[0].id == "clean_object"
    assert skills[0].contract.preconditions == ["holding(object)", "at(agent,sink)"]
    assert skipped == [{"name": "no-grasp", "reason": "no grasp: block"}]


def test_explicit_contract_preserves_unknown_metadata():
    skills = manifest_skills(
        {
            "skills": [
                {
                    "id": "a",
                    "name": "A",
                    "precondition": [],
                    "effect": ["ready(x)"],
                    "verifier": {"external": "instruction"},
                    "extra": "retained",
                }
            ]
        }
    )
    assert skills[0].contract.effects == ["ready(x)"]
    assert skills[0].metadata["upstream"]["extra"] == "retained"
    assert skills[0].metadata["upstream"]["verifier"] == {"external": "instruction"}
