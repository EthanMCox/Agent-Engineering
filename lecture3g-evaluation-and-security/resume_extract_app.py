import asyncio
import json
from pathlib import Path
from typing import Any

import gradio as gr
from openai import AsyncOpenAI

from app_helpers import (
    OPENAI_MODEL_CHOICES,
    build_toolbox,
    list_resume_files,
    load_agents,
    load_truth,
    run_agent_with_gradio_error,
)
from resume_extract_helpers import (
    DEFAULT_PROMPT_TEMPLATE,
    FIELDS,
    extract_resume_context,
    make_pdf_html,
    make_scores_matrix_html,
    make_truth_comparison_html,
    parse_extraction_response,
    score_prediction,
)


BASE_DIR = Path(__file__).resolve().parent
AGENT_CONFIG_PATH = BASE_DIR / "resume-extract.yaml"
TRUTH = load_truth()
ALL_FILES = list_resume_files()
DEFAULT_SELECTED = ALL_FILES[:4]
MODEL_CHOICES = OPENAI_MODEL_CHOICES
DEFAULT_MODEL = "gpt-4o-mini"


def load_resume_context(file_name: str) -> str:
    """
    Return OCR-derived resume text and metadata as JSON.
    """
    return extract_resume_context(file_name)


async def extract_single_resume(
    client: AsyncOpenAI,
    toolbox,
    main_agent,
    file_name: str,
    prompt_template: str,
) -> dict[str, Any]:
    request_payload = {
        "file_name": file_name,
        "prompt_template": prompt_template,
    }
    raw_response = await run_agent_with_gradio_error(
        client,
        toolbox,
        main_agent,
        json.dumps(request_payload, ensure_ascii=False),
    )
    return parse_extraction_response(raw_response or "")


async def evaluate_dataset(
    model_choice: str,
    prompt_template: str,
    selected_files: list[str],
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, float]]]:
    if not selected_files:
        return {}, {}

    client = AsyncOpenAI()
    agents, main_agent = load_agents(AGENT_CONFIG_PATH, model_choice)
    toolbox = build_toolbox(client, agents, extra_tools=[load_resume_context])
    semaphore = asyncio.Semaphore(4)
    predictions: dict[str, dict[str, Any]] = {}
    scores: dict[str, dict[str, float]] = {}

    async def run_for_file(file_name: str) -> tuple[str, dict[str, Any], dict[str, float]]:
        async with semaphore:
            prediction = await extract_single_resume(
                client,
                toolbox,
                main_agent,
                file_name,
                prompt_template,
            )
        return file_name, prediction, score_prediction(prediction, TRUTH.get(file_name, {}))

    tasks = [asyncio.create_task(run_for_file(file_name)) for file_name in sorted(selected_files)]
    for completed in asyncio.as_completed(tasks):
        file_name, prediction, score = await completed
        predictions[file_name] = prediction
        scores[file_name] = score

    return predictions, scores


async def on_compute(
    model_choice: str,
    prompt_template: str,
    selected_files: list[str],
) -> tuple[str, dict[str, dict[str, Any]], dict[str, dict[str, float]], dict]:
    if not selected_files:
        empty_message = "<p>Tick at least one resume and hit \"Compute Results\".</p>"
        return empty_message, {}, {}, gr.update(choices=[], value=None)

    predictions, scores = await evaluate_dataset(model_choice, prompt_template, selected_files)
    scores_html = make_scores_matrix_html(selected_files, scores)
    ordered_files = sorted(selected_files)
    return scores_html, predictions, scores, gr.update(choices=ordered_files, value=ordered_files[0])


def on_select_file(
    file_name: str | None,
    predictions: dict[str, dict[str, Any]],
) -> tuple[str, str]:
    if not file_name:
        return "<p>Select a file after running Compute Results.</p>", "<p>No resume selected.</p>"

    prediction = predictions.get(file_name) or {field: ([] if field == "employers" else "") for field in FIELDS}
    truth_html = make_truth_comparison_html(file_name, prediction, TRUTH)
    pdf_html = make_pdf_html(file_name)
    return truth_html, pdf_html


with gr.Blocks(title="Resume Extraction Agent Evaluation", analytics_enabled=False) as demo:
    gr.Markdown("# Resume Extraction Agent Evaluation")

    predictions_state = gr.State({})
    scores_state = gr.State({})

    with gr.Row():
        with gr.Column(scale=1):
            model = gr.Dropdown(
                label="OpenAI model",
                choices=MODEL_CHOICES,
                value=DEFAULT_MODEL,
            )
            prompt_template = gr.Textbox(
                label="Prompt template",
                lines=12,
                value=DEFAULT_PROMPT_TEMPLATE,
            )
            compute_button = gr.Button("Compute Results")
            file_selector = gr.CheckboxGroup(
                label="Select resumes to evaluate. Resumes 00-09 are text, the remainder are images.",
                choices=ALL_FILES,
                value=DEFAULT_SELECTED,
            )
        with gr.Column(scale=3):
            scores_matrix = gr.HTML("<p>Select files and click Compute Results to see the field score matrix.</p>")
            file_select = gr.Dropdown(label="Selected file", choices=[], value=None)
            with gr.Row():
                truth_html = gr.HTML("<p>Select a file after running Compute Results.</p>")
                pdf_view = gr.HTML(label="Resume PDF", value="<p>Select a file to load.</p>")

    compute_button.click(
        on_compute,
        inputs=[model, prompt_template, file_selector],
        outputs=[scores_matrix, predictions_state, scores_state, file_select],
        api_name=False,
    )

    file_select.change(
        on_select_file,
        inputs=[file_select, predictions_state],
        outputs=[truth_html, pdf_view],
        api_name=False,
        show_api=False,
    )


if __name__ == "__main__":
    demo.launch(share=False, show_api=False)
