# LangGraph Study Flow Demo (CLI)

This demo application shows key LangGraph capabilities in a compact CLI app:

- Conditional routing (`plan`, `quiz`, `clarify`)
- Tool usage (deterministic mock context)
- Human review loop (`approved` vs `needs_edits`)
- SQLite checkpoint persistence by `thread_id`
- Streaming node updates

## Project Files

- `state.py` typed graph state
- `nodes.py` graph node functions
- `tools.py` mock tool layer
- `graph.py` graph wiring (`START` -> `END`)
- `checkpointer.py` SQLite checkpointer
- `app.py` graph invocation/stream/inspect helpers
- `cli.py` command-line entrypoint
- `tests/` route + persistence tests

## Setup

```powershell
cd .\lecture3f-cookbook-and-advanced-structure\langgraph-experimentation
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Optionally copy `.env.example` to `.env` and edit values.

## Run

```powershell
python .\cli.py --thread-id demo1 --message "Help me study calculus"
python .\cli.py --thread-id demo1 --message "Generate a quiz for derivatives" --approve no --review-note "make it shorter"
python .\cli.py --thread-id demo1 --inspect
```

Or use:

```powershell
.\run.ps1
```

## Configuration

- `OPENAI_API_KEY` optional. If absent, the app uses deterministic mock drafting.
- `OPENAI_MODEL` defaults to `gpt-5-nano`.
- `CHECKPOINT_DB_PATH` defaults to `./data/checkpoints.sqlite`.
- `USE_MOCK_LLM=true` keeps outputs deterministic for experiments/tests.

## Tests

```powershell
python -m pytest -q
```
