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

## Frontend Starter Status

The initial frontend scaffold is now set up in `final_project/` using vanilla HTML, CSS, and TypeScript with Vite.

### What Is Implemented
- Single-page app shell with header and "Template Mode" status badge
- Navigation tabs for `Dashboard` and `Chat` (hash-based section switching)
- Dashboard feature cards:
  - Grade Summary
  - Study Plan
  - Quiz Generator
  - Course Context / Sources
- Chat placeholder panel with local echo behavior for UI validation
- Basic responsive styling for desktop/mobile
- Initial TypeScript interfaces:
  - `DashboardFeature`
  - `ChatMessage`

### What Is Not Implemented Yet
- Canvas API or MCP integration
- RAG/context retrieval pipeline
- Multi-agent orchestration
- Real LLM-backed chat responses
