# Multi-Agent Regression Tester

A Python multi-agent framework that analyzes a web app, explores it via Playwright,
generates manual test cases + Playwright POM automation, runs the tests, and
auto-heals selector/timing failures.

```
Analyst Agent    →   UI Explorer Agent   →   Code Generator Agent   →   Executor Agent
(static analysis)    (live Playwright)       (manual + POM)             (run + self-heal)
```

## Install

```bash
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
cp .env.example .env          # fill in API keys
```

## Run against the bundled SauceDemo app

```bash
python main.py run \
  --repo  "E:/GitProjects/AIAutomation/MultiAgent_Playwright/sample-app-web" \
  --url   "https://www.saucedemo.com/" \
  --guide "E:/GitProjects/AIAutomation/MultiAgent_Playwright/userGuide.txt" \
  --username standard_user \
  --password secret_sauce \
  --workers 2
```

Or point it at any other app. Everything lands under `./output/runs/<run-id>/`:

```
output/runs/20260422-143012/
├── state.json                  # pipeline state (resumable)
├── run.log                     # structured JSON log
├── manual_tests/
│   ├── regression_tests.md
│   └── regression_tests.xlsx
├── automation/
│   ├── pages/        base_page.py + one file per discovered page
│   ├── tests/        test_<workflow>.py for each workflow
│   ├── utils/        commands.py (safe_click, fill_form_safely), data_generator.py
│   ├── conftest.py   fixtures: base_url, credentials, browser, context, page + screenshot-on-fail hook
│   └── pytest.ini
└── test_results/
    ├── junit.xml
    ├── execution_report.html
    ├── execution_report.md
    ├── traces/
    └── screenshots/
```

## Swap LLM providers per agent

Each agent reads its own env vars, so the Analyst can use Claude while the Executor
uses Groq, etc.

```
ANALYST_LLM_PROVIDER=anthropic        # claude-opus-4-7
UI_EXPLORER_LLM_PROVIDER=anthropic
CODEGEN_LLM_PROVIDER=openai           # gpt-4o
EXECUTOR_LLM_PROVIDER=groq            # llama-3.3-70b-versatile

# Model overrides (optional)
ANALYST_LLM_MODEL=claude-opus-4-7
```

Providers supported: `anthropic`, `openai`, `google`, `groq`.

## Architecture notes

- **LangChain `create_tool_calling_agent`** for every agent — works identically across
  all four providers.
- **Single shared `PlaywrightToolbox`** per agent that needs a browser (UI Explorer,
  Executor). All Playwright operations are exposed as `StructuredTool`s bound to the
  same live `Page`.
- **`SessionState`** (`state.py`) is the single source of truth and is persisted to
  `state.json` after every stage, so a crash or interrupt mid-run doesn't lose work.
- **Deterministic skills** (`skills/route_extractors.py`, `skills/locator_strategies.py`)
  do the heavy factual work. The LLM synthesizes and decides — it doesn't re-derive
  regex matches or locator rules.
- **Self-healing is bounded**: only `selector` and `timing` failure categories are
  auto-fixed, max 3 retries per test. Assertion failures and app bugs are reported
  for human review.
- **Locator priority** matches Playwright best practice:
  `data-test[id]` → `getByRole+name` → `getByLabel` → `getByPlaceholder` → `#id` →
  `getByText` → CSS fallback.

## Extending with more agents

Each agent is a ~100-line file that subclasses `BaseAgent` with a system prompt and
a list of tools. Adding a PerformanceAgent or AccessibilityAgent is a matter of
dropping a new file in `multi_agent_tester/agents/` and invoking it from
`orchestrator.py`.
python main.py --repo "E:\GitProjects\AIAutomation\MultiAgent_Playwright\sample-app-web" --url "http://localhost:3000" --guide "E:\GitProjects\AIAutomation\MultiAgent_Playwright\userGuide.txt" --username standard_user --password secret_sauce --workers 1