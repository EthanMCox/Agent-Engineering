import json
from pathlib import Path
from typing import Any, Callable

import gradio as gr
import yaml
from openai import APIConnectionError, APIStatusError, APITimeoutError, AuthenticationError

from run_agent import Agent, as_tool, conclude, run_agent
from tools import ToolBox


BASE_DIR = Path(__file__).resolve().parent
RESUMES_DIR = BASE_DIR / "resumes"
TRUTH_PATH = RESUMES_DIR / "truth.json"

OPENAI_MODEL_CHOICES = [
    "gpt-4o-mini",
    "gpt-5-mini",
    "gpt-5",
    "gpt-5-nano",
    "gpt-4.1-mini",
    "gpt-4.1",
]


def load_truth() -> dict[str, dict[str, Any]]:
    with TRUTH_PATH.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise ValueError("truth.json must be a dictionary keyed by filename.")
    return data


def list_resume_files() -> list[str]:
    return sorted(load_truth().keys())


def parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}

    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return {}
        try:
            data = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return {}
        return data if isinstance(data, dict) else {}


def load_agents(config_path: Path, model_name: str) -> tuple[list[Agent], Agent]:
    agents: list[Agent] = list(yaml.safe_load_all(config_path.read_text()))
    for agent in agents:
        agent["model"] = model_name
    main_agent = next(agent for agent in agents if agent["name"] == "main")
    return agents, main_agent


def build_toolbox(client, agents: list[Agent], extra_tools: list[Callable] | None = None) -> ToolBox:
    toolbox = ToolBox()
    toolbox.tool(conclude)

    for tool in extra_tools or []:
        toolbox.tool(tool)

    for agent in agents:
        if agent["name"] == "main":
            continue
        toolbox.tool(as_tool(client, toolbox, agent))

    return toolbox


def format_json_output(value) -> str:
    if isinstance(value, str):
        parsed = parse_json_object(value)
        return json.dumps(parsed, indent=2, ensure_ascii=False) if parsed else value.strip()

    if value is None:
        return ""

    return json.dumps(value, indent=2, ensure_ascii=False)


async def run_agent_with_gradio_error(*args, **kwargs):
    try:
        return await run_agent(*args, **kwargs)
    except AuthenticationError as exc:
        raise gr.Error("OpenAI authentication failed. Check that OPENAI_API_KEY is set correctly.") from exc
    except (APIConnectionError, APITimeoutError) as exc:
        raise gr.Error("OpenAI request failed due to a connection problem. Check internet access and try again.") from exc
    except APIStatusError as exc:
        raise gr.Error(f"OpenAI request failed with status {exc.status_code}.") from exc
