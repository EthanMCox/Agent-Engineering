import asyncio
import json
import sys
from pathlib import Path

import yaml
from openai import AsyncOpenAI

from run_agent import run_agent
from tools import ToolBox
from usage import print_usage

toolbox = ToolBox()


def _repair_unescaped_quotes(s: str) -> str:
    out = []
    in_string = False
    escape = False
    i = 0
    while i < len(s):
        ch = s[i]
        if escape:
            out.append(ch)
            escape = False
            i += 1
            continue
        if ch == "\\":
            out.append(ch)
            escape = True
            i += 1
            continue
        if ch == '"':
            if not in_string:
                in_string = True
                out.append(ch)
                i += 1
                continue
            # in string: decide if this is closing or an embedded quote
            j = i + 1
            while j < len(s) and s[j].isspace():
                j += 1
            if j >= len(s) or s[j] in {",", "}", "]", ":"}:
                in_string = False
                out.append(ch)
            else:
                # likely an unescaped embedded quote
                out.append('\\"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_json(label: str, text: str) -> dict:
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        # Simple recovery: extract the first JSON object in the text.
        start = text.find("{")
        end = text.rfind("}")
        candidate = text
        if start != -1 and end != -1 and end > start:
            candidate = text[start:end + 1]

        # Try repair for unescaped embedded quotes.
        repaired = _repair_unescaped_quotes(candidate)
        try:
            data = json.loads(repaired)
        except json.JSONDecodeError:
            print(f"ERROR: {label} did not return valid JSON.", file=sys.stderr)
            print(f"Raw output:\n{text}\n", file=sys.stderr)
            raise e
    if not isinstance(data, dict):
        raise ValueError(f"{label} JSON must be an object.")
    return data


async def main(agent_config: Path):
    client = AsyncOpenAI()
    config = yaml.safe_load(agent_config.read_text())
    agents = {agent['name']: agent for agent in config['agents']}

    usage = []
    chat_history = []

    # 1) Chat agent asks for topic
    opener = await run_agent(
        client, toolbox, agents['chat'],
        "Start by asking the user what topic they would like to research. "
        "Return only the question.",
        chat_history, usage
    )
    print(opener)
    topic = input(">>> ").strip()
    if not topic:
        return

    # 2) Topic expansion agent generates clarifying questions
    print("\n-------<planning clarifying questions>-------")
    expander_input = json.dumps({"topic": topic})
    expander_raw = await run_agent(
        client, toolbox, agents['topic_expander'],
        expander_input, [], usage
    )
    expander = _parse_json("topic_expander", expander_raw)
    topic_summary = expander.get("topic_summary", "").strip()
    questions = expander.get("clarifying_questions", []) or []

    # 3) Chat agent asks clarifying questions and collects answers
    clarifications = []
    for q in questions[:5]:
        q_text = await run_agent(
            client, toolbox, agents['chat'],
            f"Ask the user this clarifying question: {q} "
            f"Return only the question.",
            chat_history, usage
        )
        print(q_text)
        answer = input(">>> ").strip()
        clarifications.append({"question": q, "answer": answer})

    # 4) Search planning agent creates search tasks
    print("\n-------<planning search strategy>-------")
    planner_input = json.dumps({
        "topic": topic,
        "topic_summary": topic_summary,
        "clarifications": clarifications
    })
    planner_raw = await run_agent(
        client, toolbox, agents['search_planner'],
        planner_input, [], usage
    )
    planner = _parse_json("search_planner", planner_raw)
    search_tasks = planner.get("search_tasks", []) or []
    if not search_tasks:
        print("No search tasks returned.", file=sys.stderr)
        return

    # 5) Search agent runs once per task
    print(f"\n-------<executing search tasks: {search_tasks}>-------")
    async def _run_search_task(task):
        task_json = json.dumps(task)
        search_raw = await run_agent(
            client, toolbox, agents['searcher'],
            task_json, [], usage
        )
        return _parse_json("searcher", search_raw)

    search_summaries = await asyncio.gather(
        *[_run_search_task(task) for task in search_tasks]
    )

    # 6) Synthesizer agent produces final report
    print("\n-------<generating report>-------")
    synth_input = json.dumps({
        "topic": topic,
        "topic_summary": topic_summary,
        "clarifications": clarifications,
        "search_summaries": search_summaries
    })
    report = await run_agent(
        client, toolbox, agents['synthesizer'],
        synth_input, [], usage
    )

    print("\n" + report + "\n")
    print_usage(agents['chat']['model'], usage)


if __name__ == '__main__':
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'deep_research.yaml'
    asyncio.run(main(Path(config_file)))
