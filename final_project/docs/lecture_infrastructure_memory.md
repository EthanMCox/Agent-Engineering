# Lecture Infrastructure Memory (1a-3g)

This document is a reusable memory store of agent infrastructure patterns across lecture folders `1a` through `3g`.
For machine-readable lookup, use `docs/lecture_infrastructure_index.json`.

## Pattern: Completion + Prompt Engineering Baseline
- Pattern ID: `completion_prompt_baseline`
- What it is for: quick single-shot tasks, prompt experiments, basic classification/formatting.
- Typical wiring:
  - send one prompt (or prompt + file input) to a small model,
  - minimal orchestration,
  - compare prompt variants for output quality.
- Common pitfalls:
  - prompt brittleness with underspecified constraints,
  - no memory/history for multi-turn tasks,
  - weak safety boundaries when used as a full chatbot.
- Lectures implementing it:
  - `lecture1a-intro-to-completion`
    - key files: `completion_app.py`, `basic_response.py`, `text_processor.py`
  - `lecture1b-prompt-engineering`
    - key files: `completion_app.py`, `malicious_classifier.py`, `language_analysis.py`

## Pattern: Stateful Chat Agent
- Pattern ID: `stateful_chat_agent`
- What it is for: multi-turn conversations with system prompts and interaction history.
- Typical wiring:
  - initialize history with optional system message,
  - append user turns, call model, append assistant/tool outputs,
  - support console and/or web chat loop.
- Common pitfalls:
  - unbounded history/token growth,
  - role contamination when system prompt is weak,
  - no explicit tool boundaries.
- Lectures implementing it:
  - `lecture1c-chat`
    - key files: `chatbot.py`, `our_chat.py`, `template_persona.md`
  - `lecture1d-jailbreaking`
    - key files: `jailbot.py`, `agent_chats.py`

## Pattern: Jailbreak Testing + Prompt Guardrails
- Pattern ID: `jailbreak_guardrails`
- What it is for: adversarial prompt testing and hardening assistant behavior.
- Typical wiring:
  - define constrained system behavior,
  - run adversarial prompts/chats against it,
  - iterate prompt, boundaries, and escalation language.
- Common pitfalls:
  - overfitting to known attacks only,
  - relying on prompt text without evaluation harness,
  - silent policy regressions after refactors.
- Lectures implementing it:
  - `lecture1d-jailbreaking`
    - key files: `jailbot.py`, `jail_prompt.md`, `hack-other-chats.md`
  - `lecture3g-evaluation-and-security`
    - key files: `run_agent.py`, `agents.py`, `resume_job_description_helpers.py`

## Pattern: Reasoning Workflow Prompts
- Pattern ID: `reasoning_workflow_prompts`
- What it is for: explicit decomposition and multi-step reasoning in constrained prompts.
- Typical wiring:
  - apply structured reasoning prompt templates,
  - evaluate consistency across similar scenarios,
  - keep prompts deterministic and scoped.
- Common pitfalls:
  - over-long reasoning prompts with low signal,
  - conflating explanation quality with correctness,
  - no downstream verification.
- Lectures implementing it:
  - `lecture1e-reasoning`
    - key files: `chatbot.py`, `simple-reasoning.md`, `three-hats.md`

## Pattern: RAG Ingestion + Retrieval + Grounded Answering
- Pattern ID: `rag_pipeline`
- What it is for: answer questions using retrieved source corpus instead of parametric memory alone.
- Typical wiring:
  - ingest text into vector store with chunking + metadata,
  - retrieve top chunks/docs for query,
  - inject context into response prompt with grounding instructions.
- Common pitfalls:
  - low-quality chunking and metadata,
  - retrieval misses due to weak query phrasing,
  - failing to distinguish retrieved context from user-provided text.
- Lectures implementing it:
  - `lecture2a-rag`
    - key files: `Scripture-Embeddings.ipynb`, `Phrase-Embeddings.ipynb`, `Live Embedding Demo.ipynb`
  - `lecture2b-rag-solutions`
    - key files: `chroma_demo.py`, `doctrinal_chatbot.py`, `system_prompt.md`

## Pattern: Function Tool Calling (Local Tools)
- Pattern ID: `function_tool_calling`
- What it is for: model-directed invocation of deterministic Python tools/functions.
- Typical wiring:
  - register typed tools with JSON schema,
  - run response loop until no function calls remain,
  - append `function_call_output` messages and continue.
- Common pitfalls:
  - weak parameter typing/validation,
  - tools with side effects and no sandboxing,
  - runaway loops without call/time limits.
- Lectures implementing it:
  - `lecture2d-tool-calling`
    - key files: `toolbot.py`, `tools.py`, `conference_tools.py`
  - `lecture2e-tool-calling-real-world-impact`
    - key files: `toolbot.py`, `sandbox_tools.py`, `docker_code.py`

## Pattern: MCP Server Integration
- Pattern ID: `mcp_integration`
- What it is for: integrating external capability servers through MCP endpoints/protocol.
- Typical wiring:
  - define MCP server config (label + URL/transport),
  - include MCP tool entries in model tool list,
  - route model calls through MCP tools and merge results into response flow.
- Common pitfalls:
  - server availability and transport mismatch,
  - missing auth or endpoint config,
  - weak observability of MCP failure states.
- Lectures implementing it:
  - `lecture2f-mcp-and-alternatives`
    - key files: `mcpbot.py`, `fastmcp_server/mcp_server_stock.py`, `fastmcp_server/call_stock_mcp.py`
  - `lecture2f-mcp-and-alternatives`
    - key files: `aws_mcp_server/app.py`, `aws_mcp_server/README.md`

## Pattern: Multi-Agent YAML Orchestration
- Pattern ID: `multi_agent_orchestration`
- What it is for: composing specialized agents with declarative configs and tool handoffs.
- Typical wiring:
  - declare multiple agents in YAML,
  - run a main router/manager agent,
  - expose sub-agents as callable tools and aggregate usage.
- Common pitfalls:
  - unclear delegation boundaries,
  - recursive handoff loops,
  - poor logging for per-agent outputs and cost.
- Lectures implementing it:
  - `lecture3a-agents-and-multi-agent-workflows`
    - key files: `run_agent.py`, `two_step.py`, `deep_research.yaml`
  - `lecture3b-agents-as-tools`
    - key files: `agents.py`, `run_agent.py`, `quotes.yaml`

## Pattern: Agent Memory (Episodic + MemGPT-Style)
- Pattern ID: `agent_memory_systems`
- What it is for: persisting durable context across sessions and managing memory pressure.
- Typical wiring:
  - register memory read/write/search tools,
  - persist session/core/archival state to disk,
  - inject memory summaries into prompts and flush old context.
- Common pitfalls:
  - stale or contradictory memory accumulation,
  - leaking low-quality transcript noise into durable memory,
  - missing controls for token budgets and compaction.
- Lectures implementing it:
  - `lecture3f-cookbook-and-advanced-structure/episodic`
    - key files: `agents.py`, `interview_memory.py`, `run_agent.py`
  - `lecture3f-cookbook-and-advanced-structure/memgpt`
    - key files: `agents.py`, `memory.py`, `chat_memory.yaml`

## Pattern: LangGraph State Machine Orchestration
- Pattern ID: `langgraph_state_workflow`
- What it is for: explicit graph-based control flow with conditional routing and checkpointed state.
- Typical wiring:
  - define typed state object,
  - compose nodes + conditional edges + loopbacks,
  - persist checkpoints by thread/session for resumable runs.
- Common pitfalls:
  - unclear state contracts between nodes,
  - branch explosions from weak intent routing,
  - missing replay/debug visibility.
- Lectures implementing it:
  - `lecture3f-cookbook-and-advanced-structure/langgraph-experimentation`
    - key files: `graph.py`, `nodes.py`, `checkpointer.py`

## Pattern: Evaluation + Security Harnesses
- Pattern ID: `evaluation_security_harness`
- What it is for: score quality, detect regressions, and stress-test safety-critical behavior.
- Typical wiring:
  - codify objective checks/rubrics,
  - compare generated outputs against structural requirements,
  - embed evaluator or helper tools into the workflow.
- Common pitfalls:
  - subjective-only evaluation without measurable criteria,
  - no adversarial test set,
  - offline checks that never run in CI/manual workflow.
- Lectures implementing it:
  - `lecture3g-evaluation-and-security`
    - key files: `resume_job_description_helpers.py`, `resume_job_description_app.py`, `resume_extract_helpers.py`
  - `lecture2g-ethics-and-human-factors-of-tool-calling`
    - key files: `report.md`

## Pattern: Governance and Human Factors Checkpoints
- Pattern ID: `governance_human_factors`
- What it is for: embedding ethics, representation, and human-impact framing in system design choices.
- Typical wiring:
  - include governance constraints in product requirements,
  - review outputs for fairness, representation, and harm vectors,
  - pair technical controls with human-in-the-loop oversight.
- Common pitfalls:
  - treating ethics as post-hoc documentation only,
  - no explicit review step before deployment,
  - unclear ownership for safety sign-off.
- Lectures implementing it:
  - `lecture2c-ethics-of-content-representation`
    - key files: `report.md`
  - `lecture2g-ethics-and-human-factors-of-tool-calling`
    - key files: `report.md`

