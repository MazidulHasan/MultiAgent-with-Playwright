"""Shared scaffolding for tool-calling agents."""
from __future__ import annotations

from typing import Any

from langchain.agents import AgentExecutor, create_tool_calling_agent
from langchain_core.messages import SystemMessage
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.tools import BaseTool

from ..config import AgentLLMConfig
from ..llm_factory import build_llm
from ..utils.logger import get_logger, log_event


class BaseAgent:
    name: str = "base"
    system_prompt: str = "You are a helpful AI agent."

    def __init__(self, llm_cfg: AgentLLMConfig, tools: list[BaseTool], verbose: bool = False):
        self.cfg = llm_cfg
        self.tools = tools
        self.log = get_logger(f"agent.{self.name}")
        self.llm = build_llm(llm_cfg)

        # Use SystemMessage object (not a tuple) so LangChain never tries to
        # parse the system prompt as an f-string — our prompts contain JSON
        # examples with { } which would otherwise cause a ValueError.
        prompt = ChatPromptTemplate.from_messages([
            SystemMessage(content=self.system_prompt),
            MessagesPlaceholder("chat_history", optional=True),
            ("human", "{input}"),
            MessagesPlaceholder("agent_scratchpad"),
        ])
        agent = create_tool_calling_agent(self.llm, tools, prompt)
        self.executor = AgentExecutor(
            agent=agent,
            tools=tools,
            verbose=verbose,
            max_iterations=40,
            handle_parsing_errors=True,
            return_intermediate_steps=False,
        )

    def run(self, instruction: str, **kwargs: Any) -> str:
        log_event(self.log, "agent.start", agent=self.name, provider=self.cfg.provider, model=self.cfg.model)
        result = self.executor.invoke({"input": instruction, **kwargs})
        log_event(self.log, "agent.done", agent=self.name)
        return result.get("output", "")
