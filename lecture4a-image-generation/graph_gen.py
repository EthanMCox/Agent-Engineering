import argparse
import json
import re
import tempfile
import traceback
from pathlib import Path

import gradio as gr
import pandas as pd
from openai import AsyncOpenAI
from PIL import Image

from tools import ToolBox
from usage import format_usage_markdown, print_usage

our_tools = ToolBox()

DEFAULT_CHART_PROMPT = "Create a plot comparing Q1 drink sales in 2024 and 2025 using the data in drink_sales.csv."

GENERATION_PROMPT = """
You are a data visualization expert.

Return your answer strictly in this format:

<execute_python>
# valid python code here
</execute_python>

Do not add explanations, only the tags and the code.

The selected CSV file is: {dataset_name}

The code should create a visualization from a pandas DataFrame named `df`.

Schema:
{schema_text}

Sample rows:
{sample_rows}

User instruction:
{instruction}

Requirements for the code:
1. Assume the DataFrame is already loaded as `df`.
2. Use matplotlib for plotting.
3. Add a clear title and axis labels, and a legend if needed.
4. Save the figure as '{out_path}' with dpi=300.
5. Do not call plt.show().
6. Close all plots with plt.close().
7. Add all necessary import statements.
8. Do not read from files.

Return only the code wrapped in <execute_python> tags.
"""

REFLECTION_PROMPT = """
You are a data visualization expert.
Your task: critique the attached chart and the original code against the given instruction,
 reflect on how the chart could be improved, then return improved matplotlib code to produce a better chart.

The selected CSV file is: {dataset_name}

Original code (for context):
{code_v1}

Output format (strict):
1. First line: a valid JSON object with only the "feedback" field.
Example: {{"feedback": "The legend is unclear and the axis labels overlap."}}

2. After a newline, output only the refined Python code wrapped in:
<execute_python>
...
</execute_python>

Hard constraints:
- Do not include Markdown, backticks, or extra prose outside the two parts above.
- Use matplotlib for plotting.
- Assume `df` already exists; do not read from files.
- Save to '{out_path_v2}' with dpi=300.
- Always call plt.close() at the end.
- Include all necessary import statements.

Schema:
{schema_text}

Original instruction:
{instruction}
"""

class ChatAgent:
    def __init__(self, model: str, prompt: str, show_reasoning: bool, reasoning_effort: str | None):
        self._ai = AsyncOpenAI()
        self.model = model
        self.show_reasoning = show_reasoning
        self.reasoning = {}
        if show_reasoning:
            self.reasoning["summary"] = "auto"
        if "gpt-5" in self.model and reasoning_effort:
            self.reasoning["effort"] = reasoning_effort

        self.usage = []
        self.usage_markdown = format_usage_markdown(self.model, [])

        self._prompt = prompt

    def _new_history(self) -> list[dict]:
        history = []
        if self._prompt:
            history.append({"role": "system", "content": self._prompt})
        return history

    async def _run_agent_loop(self, user_content: str | list[dict]):
        history = self._new_history()
        history.append({"role": "user", "content": user_content})

        while True:
            response = await self._ai.responses.create(
                input=history,
                model=self.model,
                reasoning=self.reasoning,
                tools=our_tools.tools,
            )

            self.usage.append(response.usage)
            self.usage_markdown = format_usage_markdown(self.model, self.usage)
            history.extend(response.output)

            for item in response.output:
                if item.type == 'reasoning':
                    for chunk in item.summary:
                        yield 'reasoning', chunk.text

                elif item.type == 'function_call':
                    yield 'reasoning', f'{item.name}({item.arguments})'

                    func = our_tools.get_tool_function(item.name)
                    args = json.loads(item.arguments)
                    result = func(**args)
                    history.append({
                        'type': 'function_call_output',
                        'call_id': item.call_id,
                        'output': str(result)
                    })
                    yield 'reasoning', str(result)

                elif item.type == 'message':
                    for chunk in item.content:
                        text = getattr(chunk, "text", None)
                        if text:
                            yield 'output', text
                    return

    async def get_response(self, user_message: str):
        async for event in self._run_agent_loop(user_message):
            yield event

    async def collect_response(self, user_content: str | list[dict]) -> tuple[str, str]:
        output = ""
        reasoning = ""

        async for text_type, text in self._run_agent_loop(user_content):
            if text_type == 'reasoning':
                reasoning += text
            elif text_type == 'output':
                output += text
            else:
                raise NotImplementedError(text_type)

        return output, reasoning

    async def generate_chart_code(
        self,
        dataset_name: str,
        schema_text: str,
        sample_rows: str,
        instruction: str,
        out_path: str,
    ) -> tuple[str, str]:
        prompt = GENERATION_PROMPT.format(
            dataset_name=dataset_name,
            schema_text=schema_text,
            sample_rows=sample_rows,
            instruction=instruction,
            out_path=out_path,
        ).strip()
        return await self.collect_response(prompt)

    async def reflect_on_chart(
        self,
        dataset_name: str,
        schema_text: str,
        instruction: str,
        code_v1: str,
        chart_data_url: str,
        out_path_v2: str,
    ) -> tuple[str, str]:
        prompt = REFLECTION_PROMPT.format(
            dataset_name=dataset_name,
            code_v1=code_v1,
            out_path_v2=out_path_v2,
            schema_text=schema_text,
            instruction=instruction,
        ).strip()

        user_content = [
            {"type": 'input_text', 'text': prompt},
            {"type": 'input_image', 'image_url': chart_data_url},
        ]
        return await self.collect_response(user_content)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print_usage(self.model, self.usage)


def _make_schema_text(df: pd.DataFrame) -> str:
    return "\n".join(f"- {column}: {dtype}" for column, dtype in df.dtypes.items())


def _sample_rows_text(df: pd.DataFrame, count: int = 5) -> str:
    sample_size = min(len(df.index), count)
    if sample_size == 0:
        return "(empty dataframe)"
    sampled = df.sample(n=sample_size, random_state=42) if len(df.index) > sample_size else df.head(sample_size)
    return sampled.to_csv(index=False)


def _extract_python_code(text: str) -> str:
    match = re.search(r"<execute_python>([\s\S]*?)</execute_python>", text)
    if not match:
        raise ValueError("The model did not return code wrapped in <execute_python> tags.")
    return match.group(1).strip()


def _parse_reflection_response(content: str) -> tuple[str, str]:
    lines = content.strip().splitlines()
    json_line = lines[0].strip() if lines else ""
    feedback = ""

    try:
        feedback = str(json.loads(json_line).get("feedback", "")).strip()
    except Exception:
        match = re.search(r"\{.*?\}", content, flags=re.DOTALL)
        if match:
            try:
                feedback = str(json.loads(match.group(0)).get("feedback", "")).strip()
            except Exception:
                feedback = ""

    return feedback, _extract_python_code(content)


def _image_to_data_url(path: Path) -> str:
    import base64
    import mimetypes

    media_type, _ = mimetypes.guess_type(path)
    encoded = base64.b64encode(path.read_bytes()).decode("utf-8")
    return f"data:{media_type or 'image/png'};base64,{encoded}"


def _execute_generated_code(df: pd.DataFrame, code: str, output_path: Path):
    exec_globals = {"df": df, "__builtins__": __builtins__}
    exec(code, exec_globals)
    if not output_path.exists():
        raise FileNotFoundError(f"Expected chart image was not created: {output_path}")


def _load_image(path: Path) -> Image.Image:
    with Image.open(path) as image:
        return image.copy()


def _list_csv_files() -> list[str]:
    files = sorted(
        str(path.relative_to(Path.cwd()))
        for path in Path.cwd().rglob("*.csv")
        if path.is_file()
    )
    return files or [""]


def _initial_csv_value() -> str:
    files = _list_csv_files()
    if "drink_sales.csv" in files:
        return "drink_sales.csv"
    return files[0]


async def _run_chart_workflow(csv_path: str, instruction: str, agent: ChatAgent):
    if agent is None:
        agent = ChatAgent(model="gpt-5-nano", prompt="", show_reasoning=False, reasoning_effort=None)

    if not csv_path:
        raise ValueError("Select a CSV file before running the workflow.")
    if not instruction.strip():
        raise ValueError("Enter a chart instruction before running the workflow.")

    dataset_path = Path(csv_path)
    if not dataset_path.exists():
        raise FileNotFoundError(f"CSV file not found: {csv_path}")

    df = pd.read_csv(dataset_path)
    schema_text = _make_schema_text(df)
    sample_rows = _sample_rows_text(df)
    
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        out_v1 = temp_dir / "chart_v1.png"
        out_v2 = temp_dir / "chart_v2.png"

        code_v1_response, reasoning_v1 = await agent.generate_chart_code(
            dataset_name=dataset_path.name,
            schema_text=schema_text,
            sample_rows=sample_rows,
            instruction=instruction,
            out_path=str(out_v1),
        )
        code_v1 = _extract_python_code(code_v1_response)
        _execute_generated_code(df, code_v1, out_v1)
        chart_v1_image = _load_image(out_v1)

        reflection_response, reasoning_v2 = await agent.reflect_on_chart(
            dataset_name=dataset_path.name,
            schema_text=schema_text,
            instruction=instruction,
            code_v1=code_v1_response,
            chart_data_url=_image_to_data_url(out_v1),
            out_path_v2=str(out_v2),
        )
        reflection_text, code_v2 = _parse_reflection_response(reflection_response)
        _execute_generated_code(df, code_v2, out_v2)
        chart_v2_image = _load_image(out_v2)

    reasoning_sections = []
    if reasoning_v1.strip():
        reasoning_sections.append("## V1 Generation\n\n" + reasoning_v1.strip())
    if reasoning_v2.strip():
        reasoning_sections.append("## V2 Reflection\n\n" + reasoning_v2.strip())
    reasoning_markdown = "\n\n".join(reasoning_sections)

    return (
        code_v1,
        chart_v1_image,
        reflection_text,
        code_v2,
        chart_v2_image,
        agent.usage_markdown,
        reasoning_markdown,
        agent,
    )


def _main_gradio(agent_args):
    css = """
    .gradio-container, .gradio-app, .gradio-root {
      max-width: 1800px !important;
      margin-left: auto !important;
      margin-right: auto !important;
    }

    #usage-md, #reasoning-md {
      max-height: 420px;
      overflow-y: auto;
    }

    #prompt-box textarea,
    #reflection-box textarea {
      max-height: 8.5em !important;
      overflow-y: auto !important;
    }

    #code-v1-box,
    #code-v2-box {
      height: 22em !important;
      max-height: 22em !important;
      overflow: hidden !important;
    }

    #code-v1-box .cm-editor,
    #code-v2-box .cm-editor,
    #code-v1-box .cm-scroller,
    #code-v2-box .cm-scroller,
    #code-v1-box .cm-content,
    #code-v2-box .cm-content,
    #code-v1-box textarea,
    #code-v2-box textarea,
    #code-v1-box pre,
    #code-v2-box pre {
      max-height: 22em !important;
    }

    #code-v1-box .cm-editor,
    #code-v2-box .cm-editor,
    #code-v1-box .cm-scroller,
    #code-v2-box .cm-scroller {
      height: 22em !important;
      overflow: auto !important;
    }

    #chart-v1,
    #chart-v2 {
      min-height: 520px;
    }

    #chart-v1 img,
    #chart-v2 img {
      max-height: 700px;
      object-fit: contain;
    }
    """

    with gr.Blocks(title='Chart Generation', css=css, theme=gr.themes.Monochrome()) as demo:
        agent_state = gr.State()

        gr.Markdown("# Chart Generation Workflow")
        gr.Markdown(
            "The model first generates a chart using matplotlib from the selected CSV file and your prompt, then executes that code to produce an initial chart. "
            "Next, the model reviews the first chart alongside the original code and prompt, writes a short reflection, and generates improved code for a second chart. "
            "The right panel shows token usage for the full run and, if enabled, the model's reasoning summaries."
        )

        with gr.Row():
            csv_selector = gr.Dropdown(
                label="CSV File",
                choices=_list_csv_files(),
                value=_initial_csv_value(),
                allow_custom_value=False,
            )
            refresh_button = gr.Button("Refresh Files", variant="secondary")
            run_button = gr.Button("Generate Charts", variant="primary")

        with gr.Row():
            with gr.Column(scale=4):
                prompt_box = gr.Textbox(
                    label="Chart Prompt",
                    value=agent_args.get("prompt", DEFAULT_CHART_PROMPT),
                    lines=4,
                    max_lines=4,
                    elem_id="prompt-box",
                    autoscroll=False,
                    container=True,
                )
                code_v1_box = gr.Code(
                    label="Generated Code (V1)",
                    language="python",
                    lines=10,
                    elem_id="code-v1-box",
                )
                chart_v1_image = gr.Image(
                    label="Generated Chart (V1)",
                    type="pil",
                    height=520,
                    elem_id="chart-v1",
                )

            with gr.Column(scale=4):
                reflection_box = gr.Textbox(
                    label="Reflection",
                    lines=4,
                    max_lines=4,
                    elem_id="reflection-box",
                    autoscroll=False,
                    container=True,
                )
                code_v2_box = gr.Code(
                    label="Generated Code (V2)",
                    language="python",
                    lines=10,
                    elem_id="code-v2-box",
                )
                chart_v2_image = gr.Image(
                    label="Generated Chart (V2)",
                    type="pil",
                    height=520,
                    elem_id="chart-v2",
                )

            with gr.Column(scale=3):
                usage_view = gr.Markdown("", elem_id="usage-md")
                reasoning_view = gr.Markdown("", elem_id="reasoning-md")

        async def run_workflow(csv_path, instruction, agent):
            try:
                return await _run_chart_workflow(csv_path, instruction, agent)
            except Exception as exc:
                error_text = f"Workflow failed: {exc}\n\n```text\n{traceback.format_exc()}\n```"
                usage_markdown = agent.usage_markdown if agent else format_usage_markdown(agent_args["model"], [])
                return (
                    "",
                    None,
                    "",
                    "",
                    None,
                    usage_markdown,
                    error_text,
                    agent,
                )

        def refresh_csv_selector():
            choices = _list_csv_files()
            value = _initial_csv_value() if choices else ""
            return gr.update(choices=choices, value=value)

        demo.load(
            fn=lambda: (ChatAgent(**agent_args), format_usage_markdown(agent_args["model"], [])),
            outputs=[agent_state, usage_view],
        )

        refresh_button.click(fn=refresh_csv_selector, outputs=[csv_selector])
        run_button.click(
            fn=run_workflow,
            inputs=[csv_selector, prompt_box, agent_state],
            outputs=[
                code_v1_box,
                chart_v1_image,
                reflection_box,
                code_v2_box,
                chart_v2_image,
                usage_view,
                reasoning_view,
                agent_state,
            ],
        )

    demo.launch()


def main(prompt_path: Path, model: str, show_reasoning, reasoning_effort: str | None):
    agent_args = dict(
        model=model,
        prompt=prompt_path.read_text() if prompt_path else DEFAULT_CHART_PROMPT,
        show_reasoning=show_reasoning,
        reasoning_effort=reasoning_effort,
    )
    _main_gradio(agent_args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser("ChartBot")
    parser.add_argument("prompt_file", nargs="?", type=Path, default=None)
    parser.add_argument("--model", default="gpt-4o-mini")
    parser.add_argument("--show-reasoning", action="store_true")
    parser.add_argument("--reasoning-effort", default="low")
    args = parser.parse_args()
    main(args.prompt_file, args.model, args.show_reasoning, args.reasoning_effort)
