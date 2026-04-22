"""Provider-agnostic LLM builder."""
from __future__ import annotations

from langchain_core.language_models import BaseChatModel

from .config import AgentLLMConfig


def build_llm(cfg: AgentLLMConfig) -> BaseChatModel:
    """Return a LangChain chat model for the given provider/model."""
    if cfg.provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic
        except ImportError:
            raise ImportError("Run: pip install langchain-anthropic")
        return ChatAnthropic(model=cfg.model, temperature=cfg.temperature, max_tokens=8192)
    if cfg.provider == "openai":
        try:
            from langchain_openai import ChatOpenAI
        except ImportError:
            raise ImportError("Run: pip install langchain-openai")
        return ChatOpenAI(model=cfg.model, temperature=cfg.temperature)
    if cfg.provider == "google":
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI
        except ImportError:
            raise ImportError("Run: pip install langchain-google-genai")
        return ChatGoogleGenerativeAI(model=cfg.model, temperature=cfg.temperature)
    if cfg.provider == "groq":
        try:
            from langchain_groq import ChatGroq
        except ImportError:
            raise ImportError("Run: pip install langchain-groq")
        return ChatGroq(model=cfg.model, temperature=cfg.temperature)
    raise ValueError(f"Unknown provider: {cfg.provider}")
