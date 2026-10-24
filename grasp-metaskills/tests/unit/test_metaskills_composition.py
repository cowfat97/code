from copy import deepcopy

import pytest

from grasp_metaskills.metaskills_composition import (
    detect_full_cycle,
    get_inheritance_chain,
    resolve_extends,
    resolve_full,
)


def spec(id, blocks=(), **fields):
    return {
        "metadata": {"id": id, "name": id},
        "sections": [
            {
                "id": "rules",
                "title": "Rules",
                "blocks": [
                    {"id": str(i), "block_type": kind, "content": text}
                    for i, (kind, text) in enumerate(blocks)
                ],
            }
        ],
        **fields,
    }


def contents(result):
    return [b["content"] for b in result.spec["sections"][0]["blocks"]]


def test_source_replace_flag_retains_only_last_child_block():
    p = spec("p", [("rule", "parent")])
    c = spec("c", [("rule", "first"), ("rule", "last")], extends="p", replace_rules=True)
    assert contents(resolve_extends(c, {"p": p, "c": c})) == ["last"]


def test_block_type_order_and_no_mutation():
    p = spec("p", [("code", "code"), ("text", "text"), ("rule", "rule")])
    c = spec("c", [("command", "command")], extends="p")
    original = deepcopy([p, c])
    assert contents(resolve_extends(c, {"p": p, "c": c})) == ["text", "rule", "code", "command"]
    assert [p, c] == original


def test_parent_includes_not_inherited_by_child():
    p = spec("p", includes=[{"skill": "missing", "into": "rules"}])
    c = spec("c", extends="p")
    assert resolve_full(c, {"p": p, "c": c}).warnings == []


def test_missing_parent_is_error_but_missing_include_warns():
    c = spec("c", extends="missing")
    with pytest.raises(ValueError, match="parent skill not found"):
        resolve_extends(c, {"c": c})
    c = spec("c", includes=[{"skill": "missing", "into": "rules"}])
    assert resolve_full(c, {"c": c}).warnings == [
        {"type": "IncludedSkillNotFound", "skill_id": "missing", "included_by": "c"}
    ]


def test_include_sections_filter_matches_title_and_blocks_by_type():
    source = spec("s", [("rule", "rule"), ("code", "code")])
    child = spec("c", includes=[{"skill": "s", "into": "rules", "sections": ["Rules"]}])
    assert contents(resolve_full(child, {"s": source, "c": child})) == ["rule"]
    child["includes"][0]["sections"] = []
    assert contents(resolve_full(child, {"s": source, "c": child})) == []


def test_many_includes_warns_strictly_above_three():
    source = spec("s", [("rule", "rule")])
    c = spec("c", includes=[{"skill": "s", "into": "rules"}] * 4)
    result = resolve_full(c, {"s": source, "c": c})
    assert result.warnings == [
        {"type": "ManyIncludes", "target": "rules", "count": 4, "sources": ["s"] * 4}
    ]
    assert result.included_from == ["s"] * 4


def test_deep_inheritance_warning_order_and_chain():
    repo = {str(i): spec(str(i), **({"extends": str(i - 1)} if i else {})) for i in range(7)}
    result = resolve_extends(repo["6"], repo)
    assert [w["depth"] for w in result.warnings] == [7, 6]
    assert get_inheritance_chain("6", repo) == [str(i) for i in range(7)]


def test_full_cycle_checks_parent_before_includes():
    a = spec("a", extends="b", includes=[{"skill": "a", "into": "rules"}])
    b = spec("b", extends="a")
    assert detect_full_cycle("a", {"a": a, "b": b}) == ["a", "b", "a"]


def test_missing_chain_endpoint_retained():
    assert get_inheritance_chain("c", {"c": spec("c", extends="missing")}) == ["missing", "c"]
