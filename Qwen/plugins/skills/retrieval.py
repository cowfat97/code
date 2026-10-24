"""Memory-conditioned retrieval, ported from skill-dag/index.js (MIT)."""

from __future__ import annotations

import math
import re
from typing import Any

from ..contracts import Skill

STOP = set(
    (
        "a an the and it to for of with is are was were be been this that these those "
        "we you he she they do does did have has had but or not can could will would should shall"
    ).split()
)


def tokenize(text: str) -> set[str]:
    return {t for t in re.split("[^a-z0-9_]+", text.lower()) if t and t not in STOP}


def token_sim(a: str, b: str) -> float:
    left, right = tokenize(a), tokenize(b)
    return len(left & right) / len(left | right) if left and right else 0.0


def route(confidence: float | None, tau_low: float = 0.40, tau_high: float = 0.65) -> str:
    if confidence is None:
        return "full-dag-boosted-repair"
    if confidence < tau_low:
        return "react-fallback"
    if confidence > tau_high:
        return "full-dag"
    return "full-dag-boosted-repair"


def jsd_score(p: list[float], q: list[float]) -> float:
    middle = [(a + b) / 2 for a, b in zip(p, q, strict=True)]

    def kl(values: list[float]) -> float:
        return sum(a * math.log(a / b) for a, b in zip(values, middle, strict=True) if a > 0)

    return 0.5 * kl(p) + 0.5 * kl(q)


def retrieve(
    *,
    skills: list[Skill],
    goal: list[str],
    task: str,
    episodes: list[dict[str, Any]] | None = None,
    k: int = 5,
    m: int = 5,
    mixing: float = 0.5,
    eta: float = 0.7,
) -> dict[str, Any]:
    if not skills:
        return {
            "skills": [],
            "p": [],
            "p_dir": [],
            "p_mem": [],
            "features": {},
            "confidence": 0.0,
            "mode": "react-fallback",
            "memory": [],
        }
    episodes = episodes or []

    def normalize(values: list[float]) -> list[float]:
        total = sum(values)
        return [v / total for v in values]

    p_dir = normalize(
        [
            token_sim(task, " ".join([s.id, s.name, s.description, " ".join(s.contract.effects)]))
            + 0.001
            for s in skills
        ]
    )
    related = sorted(
        [(i, token_sim(task, e["task"])) for i, e in enumerate(episodes)], key=lambda pair: -pair[1]
    )[:k]
    related = [(i, rho) for i, rho in related if rho > 0]
    rho_bar = sum(rho for _, rho in related) / len(related) if related else 0.0
    p_mem = normalize(
        [
            sum(rho * episodes[i].get("trajectory", []).count(s.id) for i, rho in related) + 0.001
            for s in skills
        ]
    )
    p = normalize([mixing * a + (1 - mixing) * b for a, b in zip(p_dir, p_mem, strict=True)])
    ranked = sorted(range(len(skills)), key=lambda i: -p[i])
    selected = ranked[:m]
    sorted_p = sorted(p, reverse=True)
    margin = sorted_p[0] - (sorted_p[1] if len(sorted_p) > 1 else 0)
    agreement = 1 - jsd_score(p_dir, p_mem) if related else 0.0

    def name(predicate: str) -> str:
        match = re.match(r"^([a-z_]+)\(", predicate)
        return match[1] if match else predicate

    names = {name(effect) for i in selected for effect in skills[i].contract.effects}
    coverage = sum(name(g) in names for g in goal) / len(goal) if goal else 1.0
    z = 1.2 * rho_bar + agreement + 0.8 * margin + 1.8 * coverage - 2.0
    learned = 1 / (1 + math.exp(-z))
    historical = sum(episodes[i]["success"] for i, _ in related) / len(related) if related else 0.5
    confidence = eta * learned + (1 - eta) * historical
    return {
        "skills": [skills[i].id for i in selected],
        "p": p,
        "p_dir": p_dir,
        "p_mem": p_mem,
        "features": {
            "rhoBar": rho_bar,
            "agreement": agreement,
            "margin": margin,
            "coverage": coverage,
        },
        "confidence": confidence,
        "mode": route(confidence),
        "memory": [
            {"task": episodes[i]["task"], "rho": rho, "success": episodes[i]["success"]}
            for i, rho in related
        ],
    }
