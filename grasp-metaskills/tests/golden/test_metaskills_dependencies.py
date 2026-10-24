"""Cases from MIT core/dependencies.rs tests at dcd3fb55."""

from grasp_metaskills.contracts import Skill
from grasp_metaskills.metaskills_dependencies import resolve_dependencies


def skill(id, requires=(), provides=()):
    return Skill(id=id, name=id, metadata={"requires": list(requires), "provides": list(provides)})


def test_source_transitive_deps():
    plan = resolve_dependencies(
        [skill("a", ["cap-b"]), skill("b", ["cap-c"], ["cap-b"]), skill("c", provides=["cap-c"])],
        "a",
        root_disclosure="full",
    )
    assert [x.skill_id for x in plan.ordered] == ["c", "b", "a"]
    assert [x.disclosure for x in plan.ordered] == ["overview", "overview", "full"]
    assert plan.is_ok()


def test_source_missing_capability():
    plan = resolve_dependencies([skill("a", ["missing-cap"])], "a")
    assert [(x.required_by, x.capability) for x in plan.missing] == [("a", "missing-cap")]
    assert plan.has_issues()


def test_source_detect_cycle():
    plan = resolve_dependencies(
        [skill("a", ["cap-b"], ["cap-a"]), skill("b", ["cap-a"], ["cap-b"])], "a"
    )
    assert plan.cycles
    assert [x.skill_id for x in plan.ordered] == ["a", "b"]


def test_source_off_unknown_root():
    plan = resolve_dependencies([], "root", mode="off")
    assert [x.skill_id for x in plan.ordered] == ["root"]
    assert plan.is_ok()
