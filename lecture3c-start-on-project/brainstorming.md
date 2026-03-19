Three of the following principles required:
- Prompt engineering (driving a specific behavior or format that doesn't happen out-of-the-box)
- Hallucination control and/or protection against jailbreaking
- Context management (including RAG)
- Tool calling (including MCP and code-as-tool)
- Multiple agents (including agent-as-tool)
- Multimodal inputs (i.e. audio or image inputs)


Things that would be useful for  me to get more experience in
- Multimodal inputs
- Multiple agents
- MCP
    - Stack Overflow (https://api.stackexchange.com/docs/mcp-server)
    - Figma (https://help.figma.com/hc/en-us/articles/32132100833559-Guide-to-the-Figma-MCP-server)
    - Github (https://github.com/github/github-mcp-server)

Project ideas:
- Canvas study coach
    - Either custom MCP server or use an unofficial one available elsewhere
    - Summarize grades, class information
    - Upcoming calendar and assignments
    - Make practice quizzes
    - Find lecture screenshots, course images, or specific powerpoint slides that explain a topic
    - Simple Web UI

AI Project Overview (Canvas Study Coach)
- Goal
    - Build a study assistant that helps prioritize what to study, explains course material, and generates targeted practice.
- Architecture (external MCP-first)
    - Web UI (chat + image upload) for student interaction.
    - Orchestrator agent routes requests to specialist agents.
    - Retrieval layer combines:
        - Canvas context from an external/unofficial Canvas MCP server.
        - Local RAG index for notes, slides, and past quiz history.
    - LLM response layer returns grounded answers with source references.
- Agent roles
    - Planner agent: builds study plans based on deadlines and available time.
    - Tutor agent: explains concepts and gives examples from course context.
    - Quiz agent: creates adaptive quizzes from weak topics.
    - Critic/safety agent: checks for hallucinations, missing citations, and jailbreak-like prompts.
- Key MCP/API usage
    - Use external Canvas MCP tools for courses, assignments, modules, announcements, and calendar events.
    - Optional extra APIs/tools:
        - OCR/vision tool for uploaded lecture screenshots.
        - Calendar sync tool for reminders and schedule planning.
- Core features
    - Dashboard summary: current grade signals, upcoming assignments, and urgent tasks.
    - Smart planning: daily/weekly study plan with priority ranking.
    - Adaptive tutoring: explanations tied to specific course materials.
    - Practice mode: quiz generation + feedback + mastery tracking.
    - Multimodal support: podcast content summaries using NotebookLM?
- Context + memory strategy
    - Session memory: current goals, active class, recent mistakes.
    - Long-term memory: topic mastery history and study patterns.
    - RAG retrieval prioritizes current course + upcoming deadlines + weak topics.
- Hallucination/jailbreak controls
    - Require citations for course facts.
    - If evidence is missing, respond with uncertainty and request clarifying context.
    - Restrict sensitive actions to approved MCP tools only.
- Why this project is strong
    - Directly demonstrates: tool calling/MCP, multiple agents, multimodal input, and context management.
    - Uses real student workflows (planning, studying, reviewing), making outcomes measurable.
    
Extra idea if time: incorporate into Notebook lm to give ability to provide review summaries via podcast