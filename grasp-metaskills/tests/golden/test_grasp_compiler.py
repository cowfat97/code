"""Golden: skill-dag/skill-dag/test/verify.js [1], [5], [6]."""

import pytest

from grasp_metaskills.compiler import GraphCompiler
from grasp_metaskills.contracts import Skill, SkillContract
from grasp_metaskills.retrieval import retrieve

TASK = "clean an apple and put it on the countertop"
GOAL = ["clean(apple)", "on(apple,countertop)"]
ROWS = [
    ("find", "Find object", ["object"], [], ["knows_loc(object)"]),
    ("open", "Open receptacle", [], [], ["open(fridge)"]),
    ("pick", "Pick object", ["object"], ["knows_loc(object)", "open(fridge)"], ["holding(object)"]),
    ("goto", "Go to location", ["loc"], [], ["at(agent,loc)"]),
    ("clean", "Clean object", ["object"], ["holding(object)", "at(agent,sink)"], ["clean(object)"]),
    (
        "put",
        "Put object",
        ["object", "loc"],
        ["holding(object)", "at(agent,loc)"],
        ["on(object,loc)"],
    ),
    ("heat", "Heat object", ["object"], ["holding(object)"], ["hot(object)"]),
    ("slice", "Slice object", ["object"], ["holding(object)"], ["sliced(object)"]),
]
SKILLS = [
    Skill(id=i, name=n, contract=SkillContract(params=p, preconditions=pre, effects=eff))
    for i, n, p, pre, eff in ROWS
]
PROPOSAL = [
    {"skill": i, "args": args}
    for i, args in [
        ("find", ["apple"]),
        ("open", []),
        ("pick", ["apple"]),
        ("clean", ["apple"]),
        ("put", ["apple", "countertop"]),
        ("heat", ["apple"]),
        ("slice", ["apple"]),
    ]
]


class Registry:
    def list(self):
        return SKILLS


@pytest.mark.asyncio
async def test_verify_js_1_apple_compile():
    graph = await GraphCompiler(Registry(), strict_preconditions=False).compile(
        goal=GOAL, task=TASK, proposal=PROPOSAL, initial_conditions=["at(agent,fridge)"]
    )
    assert [i for i in graph.topological_order() if i not in ("src", "snk")] == [
        "find:1",
        "open:1",
        "pick:1",
        "clean:1",
        "put:1",
    ]
    assert sorted(f"{e.source}→{e.target}" for e in graph.edges if e.type == "state") == [
        "find:1→pick:1",
        "open:1→pick:1",
        "pick:1→clean:1",
        "pick:1→put:1",
    ]
    assert sorted(f"{e.source}→{e.target}" for e in graph.edges if e.type == "data") == [
        "find:1→pick:1",
        "pick:1→clean:1",
        "pick:1→put:1",
    ]
    assert graph.metadata["missing_preconditions"] == {
        "clean:1": ["at(agent,sink)"],
        "put:1": ["at(agent,countertop)"],
    }


@pytest.mark.asyncio
async def test_verify_js_5_hallucination_guard():
    proposal = [
        {"skill": "nonexistent", "args": []},
        {"skill": "find", "args": ["apple", "extra"]},
        *PROPOSAL[1:5],
    ]
    graph = await GraphCompiler(Registry(), strict_preconditions=False).compile(
        goal=GOAL, proposal=proposal
    )
    assert graph.metadata["rejected"] == [
        {"skill": "nonexistent", "reason": "unknown skill"},
        {"skill": "find", "reason": "arity 2 != 1"},
    ]


def test_verify_js_6_confidence():
    empty = retrieve(skills=SKILLS, goal=GOAL, task=TASK)
    assert f"{empty['confidence']:.4f}" == "0.4831"
    episodes = [
        {
            "task": TASK,
            "trajectory": ["find", "open", "pick", "goto", "clean", "put"],
            "success": True,
        }
    ]
    learned = retrieve(skills=SKILLS, goal=GOAL, task=TASK, episodes=episodes)
    assert f"{learned['confidence']:.4f}" == "0.9009"
    assert learned["mode"] == "full-dag"
    unrelated = retrieve(
        skills=SKILLS, goal=GOAL, task="unrelated cooking recipe", episodes=episodes
    )
    assert unrelated["mode"] == "react-fallback"
