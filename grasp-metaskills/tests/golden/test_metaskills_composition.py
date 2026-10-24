"""Source resolution.rs test scenarios; native spec dictionaries."""

import pytest

from grasp_metaskills.metaskills_composition import resolve_extends, resolve_full


def spec(id, rules=(), **fields):
    return dict(
        metadata={"id": id, "name": id},
        format_version="1",
        sections=[
            {
                "id": "rules",
                "title": "Rules",
                "blocks": [
                    {"id": f"rule-{i}", "block_type": "rule", "content": text}
                    for i, text in enumerate(rules)
                ],
            }
        ],
        **fields,
    )


def test_source_section_merging():
    parent = spec("parent", ["Parent rule"])
    child = spec("child", ["Child rule"], extends="parent")
    result = resolve_extends(child, {"parent": parent, "child": child})
    assert result.inheritance_chain == ["parent", "child"]
    assert [b["content"] for b in result.spec["sections"][0]["blocks"]] == [
        "Parent rule",
        "Child rule",
    ]
    assert result.spec["extends"] is None


def test_source_include_with_prefix_and_prepend():
    source = spec("errors", ["Handle errors"])
    main = spec(
        "main",
        ["Main rule"],
        includes=[
            {"skill": "errors", "into": "rules", "prefix": "[Error] ", "position": "prepend"}
        ],
    )
    result = resolve_full(main, {"main": main, "errors": source})
    assert [b["content"] for b in result.spec["sections"][0]["blocks"]] == [
        "[Error] Handle errors",
        "Main rule",
    ]
    assert result.included_from == ["errors"]
    assert result.spec["includes"] == []


def test_source_include_cycle_detection():
    a = spec("a", includes=[{"skill": "b", "into": "rules"}])
    b = spec("b", includes=[{"skill": "a", "into": "rules"}])
    with pytest.raises(ValueError, match="cyclic inheritance"):
        resolve_full(a, {"a": a, "b": b})
