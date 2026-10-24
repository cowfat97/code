"""Strict fact verification port plus explicit JSON Schema validation."""

from typing import Any

from jsonschema import Draft202012Validator

from ..contracts import NodeResult, SkillNode, VerificationResult


def verify_input(node: SkillNode, inputs: dict[str, Any], facts: list[str]) -> VerificationResult:
    missing = sorted(set(node.preconditions) - set(facts))
    if missing:
        return VerificationResult(
            passed=False, category="precondition", message="missing: " + ", ".join(missing)
        )
    if node.skill:
        errors = list(Draft202012Validator(node.skill.contract.input_schema).iter_errors(inputs))
        if errors:
            return VerificationResult(
                passed=False, category="input_schema", message=errors[0].message
            )
    return VerificationResult(passed=True)


def verify_result(node: SkillNode, result: NodeResult) -> VerificationResult:
    if node.skill:
        errors = list(
            Draft202012Validator(node.skill.contract.output_schema).iter_errors(result.output)
        )
        if errors:
            return VerificationResult(
                passed=False, category="output_schema", message=errors[0].message
            )
    missing = sorted(set(node.effects) - set(result.observed_effects))
    if missing:
        return VerificationResult(
            passed=False,
            category="postcondition",
            message="effect not observed: " + ", ".join(missing),
        )
    return VerificationResult(passed=True)
