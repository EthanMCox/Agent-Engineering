import json
import logging

from pathlib import Path

import gradio as gr
from openai import AsyncOpenAI

from app_helpers import (
    OPENAI_MODEL_CHOICES,
    build_toolbox,
    format_json_output,
    load_agents,
    load_truth,
    parse_json_object,
    run_agent_with_gradio_error,
)
from resume_copilot_helpers import (
    build_candidate_choices,
    build_candidate_context,
)


BASE_DIR = Path(__file__).resolve().parent
AGENT_CONFIG_PATH = BASE_DIR / "resume-copilot.yaml"

DEFAULT_MODEL = "gpt-5-nano"

TRUTH = load_truth()
CANDIDATE_LABELS, LABEL_TO_KEY = build_candidate_choices(TRUTH)


def load_candidate_context(candidate_label: str, recruiter_notes: str) -> str:
    """
    Return structured candidate context and gold talking points as JSON.
    """
    return build_candidate_context(candidate_label, recruiter_notes, TRUTH, LABEL_TO_KEY)


def make_toolbox(client: AsyncOpenAI, agents):
    return build_toolbox(client, agents, extra_tools=[load_candidate_context])


async def run_copilot_workflow(
    model_choice: str,
    candidate_label: str,
    notes_text: str,
) -> tuple[str, str]:
    if candidate_label not in LABEL_TO_KEY:
        raise gr.Error("Invalid candidate selection.")

    client = AsyncOpenAI()
    agents, main_agent = load_agents(AGENT_CONFIG_PATH, model_choice)
    toolbox = make_toolbox(client, agents)

    request_payload = {
        "candidate_label": candidate_label,
        "recruiter_notes": notes_text or "",
    }
    raw_response = await run_agent_with_gradio_error(
        client,
        toolbox,
        main_agent,
        json.dumps(request_payload, ensure_ascii=False),
    )

    response_data = parse_json_object(raw_response or "")
    summary = (response_data.get("summary") or "").strip()
    judge_text = response_data.get("judge_json")
    formatted_judge = format_json_output(judge_text)

    if not summary:
        raise gr.Error("The agent run did not return a summary.")
    if not formatted_judge:
        raise gr.Error("The agent run did not return judge output.")

    return formatted_judge, summary


with gr.Blocks(title="Recruiter Co-Pilot — Framework Version") as demo:
    gr.Markdown("## Recruiter Co-Pilot — YAML Agent Framework Version")

    with gr.Row():
        with gr.Column(scale=1):
            model = gr.Dropdown(
                OPENAI_MODEL_CHOICES,
                value=DEFAULT_MODEL,
                label="Model",
            )
            candidate = gr.Dropdown(
                choices=CANDIDATE_LABELS,
                value=CANDIDATE_LABELS[0] if CANDIDATE_LABELS else None,
                label="Candidate",
            )
            notes_box = gr.Textbox(
                label="Recruiter Phone Screening Notes",
                lines=4,
                value=(
                    "Candidate is interested in a role that will provide an opportunity "
                    "to learn new skills and contribute meaningfully to product development."
                ),
            )
            run_button = gr.Button("Generate & Grade Summary", variant="primary")

        with gr.Column(scale=2):
            judge_box = gr.Textbox(
                label="LLM-as-Judge — JSON",
                lines=12,
            )
            summary_box = gr.Markdown(label="Generated Candidate Summary")

    run_button.click(
        run_copilot_workflow,
        inputs=[model, candidate, notes_box],
        outputs=[judge_box, summary_box],
    )

def _configure_logging(debug: bool) -> None:
    import os
    import sys

    LOG_FORMAT = '%(filename)-10.10s %(levelname)-4.4s %(asctime)s %(message)s'

    local_level = logging.DEBUG if debug else logging.INFO
    use_dark_gray = (
            sys.stderr.isatty()
            and os.getenv('NO_COLOR') is None
            and os.getenv('TERM', '').lower() != 'dumb'
    )
    format_string = f'\x1b[90m{LOG_FORMAT}\x1b[0m' if use_dark_gray else LOG_FORMAT
    logging.basicConfig(
        level=logging.WARNING,
        format=format_string,
        datefmt='%H:%M:%S',
        force=True,
    )
    for logger_name in ('__main__', 'agents', 'run_agent', 'tools', 'usage'):
        logging.getLogger(logger_name).setLevel(local_level)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    _configure_logging(args.debug)

    demo.launch()
