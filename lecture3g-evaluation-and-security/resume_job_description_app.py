import json
from pathlib import Path

import gradio as gr
from openai import AsyncOpenAI

from app_helpers import (
    OPENAI_MODEL_CHOICES,
    build_toolbox,
    format_json_output,
    load_agents,
    parse_json_object,
    run_agent_with_gradio_error,
)
from resume_job_description_helpers import (
    DEFAULT_GEN_PROMPT,
    JOB_TITLES,
    format_objective_report,
    objective_eval,
)


BASE_DIR = Path(__file__).resolve().parent
AGENT_CONFIG_PATH = BASE_DIR / "resume-job-description.yaml"
MODEL_CHOICES = OPENAI_MODEL_CHOICES
DEFAULT_MODEL = "gpt-4o-mini"


async def run_framework_workflow(
    model_choice: str,
    title_choice: str,
    generation_prompt: str,
) -> tuple[str, str]:
    client = AsyncOpenAI()
    agents, main_agent = load_agents(AGENT_CONFIG_PATH, model_choice)
    toolbox = build_toolbox(client, agents)
    request_payload = {
        "job_title": title_choice,
        "generation_prompt": generation_prompt,
    }
    raw_response = await run_agent_with_gradio_error(
        client,
        toolbox,
        main_agent,
        json.dumps(request_payload, ensure_ascii=False),
    )
    data = parse_json_object(raw_response or "")
    jd_text = (data.get("job_description") or "").strip()
    subjective_json = format_json_output(data.get("subjective_json"))
    if not jd_text:
        raise gr.Error("The agent run did not return a job description.")
    if not subjective_json.strip():
        raise gr.Error("The agent run did not return subjective grading output.")
    return jd_text, subjective_json


async def on_generate(
    model_choice: str,
    title_choice: str,
    generation_prompt: str,
) -> tuple[str, str, str]:
    jd_text, subjective_json = await run_framework_workflow(
        model_choice,
        title_choice,
        generation_prompt,
    )

    objective_text = format_objective_report(objective_eval(jd_text))
    return objective_text, format_json_output(subjective_json), jd_text


with gr.Blocks(title="Job Description Generator + Dual Evaluation") as demo:
    gr.Markdown("## Job Description Generator — Objective & Subjective Evaluation Demo")

    with gr.Row():
        with gr.Column(scale=1):
            model = gr.Dropdown(
                MODEL_CHOICES,
                value=DEFAULT_MODEL,
                label="Model",
            )
            title = gr.Dropdown(JOB_TITLES, value=JOB_TITLES[0], label="Job Title")
            prompt = gr.Textbox(
                value=DEFAULT_GEN_PROMPT,
                label="JD Generation Prompt",
                lines=10,
            )
            run_button = gr.Button("Generate JD", variant="primary")

        with gr.Column(scale=2):
            with gr.Row():
                objective_box = gr.Textbox(
                    label="Objective (Code) — Structure & Overview Match",
                    lines=10,
                )
                subjective_box = gr.Textbox(
                    label="Subjective (LLM-as-Judge) — Rubric JSON",
                    lines=10,
                )
            jd_box = gr.Markdown(label="Generated Job Description")

    run_button.click(
        on_generate,
        inputs=[model, title, prompt],
        outputs=[objective_box, subjective_box, jd_box],
    )


if __name__ == "__main__":
    demo.launch()
