"""Runtime configuration loaded from env vars / .env."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

Provider = Literal["anthropic", "openai", "google", "groq"]

_DEFAULT_MODELS: dict[Provider, str] = {
    "anthropic": "claude-opus-4-7",
    "openai": "gpt-4o",
    "google": "gemini-2.0-flash",
    "groq": "llama-3.3-70b-versatile",
}


class AgentLLMConfig(BaseModel):
    provider: Provider
    model: str
    temperature: float = 0.0


def _agent_llm(name: str, default_provider: Provider = "anthropic") -> AgentLLMConfig:
    provider = os.getenv(f"{name}_LLM_PROVIDER", default_provider).lower()
    if provider not in ("anthropic", "openai", "google", "groq"):
        raise ValueError(f"Unsupported provider for {name}: {provider}")
    model = os.getenv(
        f"{name}_LLM_MODEL",
        os.getenv(f"{provider.upper()}_MODEL", _DEFAULT_MODELS[provider]),
    )
    return AgentLLMConfig(provider=provider, model=model)  # type: ignore[arg-type]


class Settings(BaseModel):
    output_dir: Path = Field(default_factory=lambda: Path(os.getenv("OUTPUT_DIR", "./output")))
    log_level: str = Field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO"))

    analyst: AgentLLMConfig = Field(default_factory=lambda: _agent_llm("ANALYST"))
    ui_explorer: AgentLLMConfig = Field(default_factory=lambda: _agent_llm("UI_EXPLORER"))
    codegen: AgentLLMConfig = Field(default_factory=lambda: _agent_llm("CODEGEN"))
    executor: AgentLLMConfig = Field(default_factory=lambda: _agent_llm("EXECUTOR"))
    orchestrator: AgentLLMConfig = Field(default_factory=lambda: _agent_llm("ORCHESTRATOR"))


settings = Settings()
