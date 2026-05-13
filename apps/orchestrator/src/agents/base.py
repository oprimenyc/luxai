"""Base agent class with retry, telemetry, and structured output."""

import time
from abc import ABC, abstractmethod
from typing import Any

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.config import settings

log = structlog.get_logger(__name__)


class BaseAgent(ABC):
    """Abstract base for all LuxAI agents."""

    name: str
    description: str
    system_prompt: str

    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
    ) -> None:
        self.model_name = model or settings.default_model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self._llm = self._build_llm()

    def _build_llm(self) -> BaseChatModel:
        if self.model_name.startswith("gpt") or self.model_name.startswith("o"):
            return ChatOpenAI(
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                api_key=settings.openai_api_key,
            )
        if self.model_name.startswith("claude"):
            return ChatAnthropic(  # type: ignore[return-value]
                model=self.model_name,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                api_key=settings.anthropic_api_key,
            )
        raise ValueError(f"Unsupported model: {self.model_name}")

    @retry(
        retry=retry_if_exception_type(Exception),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def invoke(
        self,
        task: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        start = time.perf_counter()
        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=self._build_prompt(task, context or {})),
        ]

        response: AIMessage = await self._llm.ainvoke(messages)  # type: ignore[assignment]
        duration_ms = (time.perf_counter() - start) * 1000

        log.info(
            "agent_invoked",
            agent=self.name,
            model=self.model_name,
            duration_ms=round(duration_ms, 2),
            input_tokens=response.usage_metadata.get("input_tokens") if response.usage_metadata else None,
            output_tokens=response.usage_metadata.get("output_tokens") if response.usage_metadata else None,
        )

        return str(response.content)

    def _build_prompt(self, task: str, context: dict[str, Any]) -> str:
        parts = [f"Task: {task}"]
        if context:
            context_str = "\n".join(f"  {k}: {v}" for k, v in context.items())
            parts.append(f"\nContext:\n{context_str}")
        return "\n".join(parts)

    @abstractmethod
    async def run(self, state: dict[str, Any]) -> dict[str, Any]:
        """Execute the agent and return updated state."""
        ...
