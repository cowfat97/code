"""Injected capabilities: no implicit model requests or process execution."""

from typing import Any, Protocol

from ..contracts import ExecutionContext, NodeResult, Skill, SkillNode, VerificationResult


class LLMProvider(Protocol):
    async def complete(self, prompt: str) -> str: ...


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


class SkillProposer(Protocol):
    async def propose(
        self, *, task: str, skills: list[Skill], goal: list[str]
    ) -> list[dict[str, Any]]: ...


class SkillExecutor(Protocol):
    async def execute(
        self, node: SkillNode, inputs: dict[str, Any], context: ExecutionContext
    ) -> NodeResult: ...


class SkillVerifier(Protocol):
    async def verify(
        self, node: SkillNode, inputs: dict[str, Any], result: NodeResult, context: ExecutionContext
    ) -> VerificationResult: ...
