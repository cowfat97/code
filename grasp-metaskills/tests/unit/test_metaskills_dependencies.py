import pytest

from grasp_metaskills.contracts import Skill
from grasp_metaskills.metaskills_dependencies import capability_edges, resolve_dependencies


def s(id, requires=(), provides=()):
    return Skill(id=id, name=id, metadata={"requires": list(requires), "provides": list(provides)})


def test_all_providers_and_reverse_kahn_tie_order():
    skills = [s("root", ["cap"]), s("a", provides=["cap"]), s("b", provides=["cap"])]
    assert [(e.source, e.target) for e in capability_edges(skills)] == [
        ("root", "a"),
        ("root", "b"),
    ]
    assert [x.skill_id for x in resolve_dependencies(skills, "root").ordered] == ["b", "a", "root"]


def test_self_provider_satisfies_without_self_cycle():
    plan = resolve_dependencies([s("a", ["cap"], ["cap"])], "a")
    assert plan.is_ok()
    assert capability_edges([s("a", ["cap"], ["cap"])]) == []


def test_depth_limit_silently_truncates_like_source():
    skills = [s("a", ["b"]), s("b", ["missing"], ["b"])]
    plan = resolve_dependencies(skills, "a", max_depth=1)
    assert plan.is_ok()
    assert [x.skill_id for x in plan.ordered] == ["b", "a"]
    assert resolve_dependencies(skills, "a", max_depth=2).has_issues()


def test_duplicate_capabilities_preserve_duplicate_edges():
    edges = capability_edges([s("a", ["b", "b"]), s("b", provides=["b", "b"])])
    assert len(edges) == 4


@pytest.mark.parametrize(
    "mode,expected", [("auto", "overview"), ("full", "full"), ("overview", "overview")]
)
def test_disclosure(mode, expected):
    plan = resolve_dependencies([s("a", ["b"]), s("b", provides=["b"])], "a", "complete", mode)
    assert [x.disclosure for x in plan.ordered] == [expected, "complete"]


def test_no_version_constraint_in_upstream_capability_graph():
    skill = s("a").model_copy(update={"version": "arbitrary-upstream-string"})
    assert resolve_dependencies([skill], "a").is_ok()


def test_reject_malformed_capability_metadata():
    with pytest.raises(ValueError, match="list of strings"):
        resolve_dependencies([Skill(id="a", name="A", metadata={"requires": "b"})], "a")
