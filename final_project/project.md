# Canvas Study Coach Project Plan

## Overall Project Outline

### 1. Project Goal
Build a Canvas Study Coach application that connects to Canvas LMS to summarize grades and assignments, create study plans, and generate targeted quizzes.

### 2. Core Capabilities
- Canvas-aware dashboard (courses, assignments, deadlines, grade signals)
- Study planning (daily/weekly prioritized recommendations)
- Targeted tutoring and quiz generation from weak topics
- Source-grounded responses with citations

### 3. Required Technical Principles
- Tool calling / MCP (Canvas integration)
- Context management / RAG (course materials and history)
- Multiple agents (planner, tutor, quiz, safety/critic)
- Optional stretch: multimodal input support

### 4. High-Level Architecture
- Web UI for student interaction
- Orchestrator that routes requests to specialist agents
- Retrieval layer combining Canvas MCP context + local RAG index
- Safety/critic checks for hallucinations, missing citations, and jailbreak-like prompts
- Response layer returning grounded answers with references

### 5. Success Criteria
- The app can answer “What should I study today?” using deadlines + weak areas
- The app can generate adaptive quizzes tied to course context
- The app can explain outputs with references/citations
- The app demonstrates MCP tool calling + context management + multi-agent flow

---

## Six Broad Substeps (2-3 Hours Each)

### 1) Scope and Requirements Lock (2-3 hours)
- Define MVP features vs stretch goals
- Finalize user flows (dashboard, planning, quiz, tutoring)
- Write acceptance criteria for each core feature
- **Output:** finalized one-page product spec + feature checklist

### 2) Canvas MCP Integration Foundation (2-3 hours)
- Configure Canvas MCP authentication and connectivity
- Verify core tool calls (courses, assignments, calendar/events, grade-related data)
- Document required data fields and tool responses
- **Output:** working Canvas tool integration notes + tested tool matrix

### 3) Context/RAG Strategy and Data Design (2-3 hours)
- Define context sources (Canvas data, notes/slides, quiz history)
- Create retrieval policy (course-first, deadline-aware, weak-topic-aware)
- Define citation format and “insufficient evidence” fallback behavior
- **Output:** context architecture + retrieval policy document

### 4) Multi-Agent Orchestration Setup (2-3 hours)
- Implement and connect planner, tutor, quiz, and safety/critic roles
- Define structured handoff schema between agents
- Run 2-3 representative manual end-to-end scenarios
- **Output:** agent orchestration flow + initial scenario results

### 5) Core Feature Wiring in UI (2-3 hours)
- Implement minimal UI paths for dashboard, plan generation, and quiz mode
- Connect each flow to tools/agents
- Ensure responses display citations clearly
- **Output:** usable MVP demo flow from UI

### 6) Evaluation, Hardening, and Demo Prep (2-3 hours)
- Evaluate hallucination/jailbreak resistance and citation reliability
- Test ambiguous and missing-context prompts
- Prepare final demo script and report mapping to course principles
- **Output:** evaluation summary + polished demo/report-ready narrative

---

## Frontend Implementation Status

The frontend is implemented in `final_project/` using vanilla HTML, CSS, and TypeScript with Vite.

### What Is Implemented
- Single-page app shell with final-project status messaging
- Navigation tabs for `Dashboard` and `Chat` (hash-based section switching)
- Dashboard feature cards:
  - Grade Summary
  - Study Plan
  - Quiz Generator
  - Course Context / Sources
- Chat panel connected to a basic FastAPI backend
- Per-session chat memory (session ID stored in browser `localStorage`)
- Reset chat control wired to backend memory reset endpoint
- Basic responsive styling for desktop/mobile
- Initial TypeScript interfaces:
  - `DashboardFeature`
  - `ChatMessage`

### What Is In Progress
- Dashboard cards currently present roadmap areas and are not yet interactive
- RAG/context retrieval beyond current Canvas grounding is still being expanded
- Multi-agent orchestration is planned but not yet wired into runtime chat flows
- Additional hardening and guardrail depth are still in progress

### Local Run Commands
- Frontend: `npm run dev`
- Backend setup: `python -m pip install -r backend/requirements.txt`
- Backend run: `python -m uvicorn backend.app:app --reload --port 8000`

---

## Canvas MCP Sidecar Runbook

### Sidecar Package Location
- Canvas MCP dependencies are isolated in `final_project/mcp-canvas/`.
- Frontend dependencies remain in `final_project/package.json`.

### One-Time Setup
1. Install frontend deps (already used by Vite):
   - `npm install`
2. Install Canvas MCP sidecar deps:
   - `npm --prefix .\mcp-canvas install`
3. Install backend deps:
   - `python -m pip install -r backend/requirements.txt`

### Environment Variables
- In `.env`, configure:
  - `CANVAS_MCP_ENABLED=true`
  - `CANVAS_API_TOKEN=<canvas token>`
  - `CANVAS_DOMAIN=<school>.instructure.com`
- Precedence rule:
  - Backend loads `.env` first; OS environment is used as fallback for missing keys.
- Optional overrides:
  - `CANVAS_MCP_COMMAND` (defaults to `npx canvas-mcp-server`)
  - `CANVAS_MCP_WORKDIR` (defaults to `.\mcp-canvas`)
  - `CANVAS_MCP_STARTUP_TIMEOUT_SECONDS` (defaults to `15`)
  - `CANVAS_MCP_CALL_TIMEOUT_SECONDS` (defaults to `10`)
  - `CANVAS_MCP_COURSE_LIMIT` (defaults to `3`)
  - `CANVAS_MCP_ASSIGNMENTS_LIMIT` (defaults to `8`)

### Startup Model
- Preferred: backend manages MCP sidecar lifecycle automatically on startup.
- Diagnostics only: run sidecar manually with
  - `npm --prefix .\mcp-canvas run start`

### Chat Tool-Calling Behavior
- Backend chat now uses a local tool-calling loop for Canvas grounding.
- When MCP is healthy, the backend dynamically registers all tools exposed by the `mcp-canvas` sidecar (`canvas-mcp-server`) and makes them callable during each chat turn.
- When MCP is unavailable, tools are not registered and the assistant explicitly falls back with uncertainty language.

### Health Verification
- `GET /health` returns:
  - `mcp_canvas_enabled` (feature toggle),
  - `mcp_canvas_ok` (active session),
  - `mcp_canvas_status` (`disabled`, `starting`, `ready`, `degraded`, `error`),
  - `mcp_canvas_error` (latest actionable failure message).

### Troubleshooting
- `mcp_canvas_status=error` with `Python package 'mcp' not installed`:
  - Use the Python interpreter where `mcp` is installed, then reinstall backend deps.
- `mcp_canvas_status=error` with missing token/domain:
  - Set `CANVAS_API_TOKEN` and `CANVAS_DOMAIN`.
- `mcp_canvas_status=error` with command/workdir failures:
  - Verify `CANVAS_MCP_COMMAND` and `CANVAS_MCP_WORKDIR`.
- `mcp_canvas_status=degraded`:
  - MCP started but tool probing/calls failed; verify Canvas credentials/connectivity.
