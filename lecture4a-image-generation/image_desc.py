import argparse
import base64
import io
import json
import mimetypes
import traceback
from pathlib import Path

import gradio as gr
from openai import AsyncOpenAI
from PIL import Image

from tools import ToolBox
from usage import format_usage_markdown, print_usage

our_tools = ToolBox()

DEFAULT_MODEL = 'gpt-5-mini'
DEFAULT_IMAGE_SIZE = '1024x1024'
DEFAULT_MODIFY_PROMPT = "Add a subtle handwritten label in the upper right corner that says 'CS301 demo'."

CAPTION_PROMPT = """
Write a concise, vivid caption for this image in no more than 20 words.
"""

DESCRIPTION_PROMPT = """
Describe this image in 3-4 sentences. Mention the main subjects, setting, visible actions, and notable visual details.
"""

MODIFICATION_PROMPT = """
Modify the provided image according to this instruction: {instruction}

Return exactly one edited image at size {size}. Preserve the original scene unless the instruction requires a larger change.
"""


def pil_to_data_url(img: Image.Image, src_path: str | None = None) -> str:
    mime = None
    fmt = getattr(img, "format", None)
    format_map = {
        '.jpg': 'JPEG',
        '.jpeg': 'JPEG',
        '.png': 'PNG',
        '.webp': 'WEBP',
        '.gif': 'GIF',
    }

    if src_path:
        ext = Path(src_path).suffix.lower()
        mime = mimetypes.types_map.get(ext)
        if not fmt and mime and mime.startswith("image/"):
            fmt = format_map.get(ext, ext.lstrip(".").upper() if ext else 'PNG')

    if mime is None:
        mime = 'image/png'
    if not fmt:
        fmt = 'PNG'

    buffer = io.BytesIO()
    img.convert('RGB').save(buffer, format=fmt)
    b64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    return f'data:{mime};base64,{b64}'


def load_image(image_path: str | None) -> Image.Image:
    if not image_path:
        raise gr.Error('Please upload an image first.')
    with Image.open(image_path) as image:
        return image.convert('RGB')


def _image_size_text(image: Image.Image | None, prefix: str) -> str:
    if image is None:
        return ''
    return f'{prefix}: {image.width} x {image.height}px'


def _image_size_from_path(image_path: str | None, prefix: str = 'Image size') -> str:
    if not image_path:
        return ''
    with Image.open(image_path) as image:
        return _image_size_text(image, prefix)


class ImageAgent:
    def __init__(self, model: str, prompt: str, show_reasoning: bool, reasoning_effort: str | None):
        self._ai = AsyncOpenAI()
        self.model = model
        self.show_reasoning = show_reasoning
        self.reasoning = {}
        if show_reasoning:
            self.reasoning['summary'] = 'auto'
        if 'gpt-5' in self.model and reasoning_effort:
            self.reasoning['effort'] = reasoning_effort

        self.usage = []
        self.usage_markdown = format_usage_markdown(self.model, [])
        self._prompt = prompt

    def _new_history(self) -> list[dict]:
        history = []
        if self._prompt:
            history.append({'role': 'system', 'content': self._prompt})
        return history

    async def _run_agent_loop(self, user_content: str | list[dict], extra_tools: list[dict] | None = None):
        history = self._new_history()
        history.append({'role': 'user', 'content': user_content})
        tool_defs = [*our_tools.tools, *(extra_tools or [])]

        while True:
            response = await self._ai.responses.create(
                input=history,
                model=self.model,
                reasoning=self.reasoning,
                tools=tool_defs or None,
            )

            self.usage.append(response.usage)
            self.usage_markdown = format_usage_markdown(self.model, self.usage)
            history.extend(response.output)

            for item in response.output:
                if item.type == 'reasoning':
                    for chunk in item.summary:
                        yield 'reasoning', chunk.text

                elif item.type == 'function_call':
                    yield 'reasoning', f"{item.name}({item.arguments})"
                    func = our_tools.get_tool_function(item.name)
                    args = json.loads(item.arguments)
                    result = func(**args)
                    history.append(
                        {
                            'type': 'function_call_output',
                            'call_id': item.call_id,
                            'output': str(result),
                        }
                    )
                    yield 'reasoning', str(result)

                elif item.type == 'image_generation_call':
                    yield 'image', item.result

                elif item.type == 'message':
                    for chunk in item.content:
                        text = getattr(chunk, 'text', None)
                        if text:
                            yield 'output', text
                    return

    async def collect_text_response(self, user_content: list[dict]) -> tuple[str, str]:
        output = ''
        reasoning = ''

        async for text_type, text in self._run_agent_loop(user_content):
            if text_type == 'reasoning':
                reasoning += text
            elif text_type == 'output':
                output += text

        return output.strip(), reasoning.strip()

    async def collect_image_response(self, user_content: list[dict]) -> tuple[Image.Image, str]:
        reasoning = ''
        image_b64 = None

        async for text_type, text in self._run_agent_loop(
            user_content,
            extra_tools=[{'type': 'image_generation'}],
        ):
            if text_type == 'reasoning':
                reasoning += text
            elif text_type == 'image':
                image_b64 = text

        if not image_b64:
            raise RuntimeError('The model did not return an edited image.')

        raw = base64.b64decode(image_b64)
        with Image.open(io.BytesIO(raw)) as image:
            edited = image.convert('RGB')

        return edited, reasoning.strip()

    async def caption_image(self, data_url: str) -> tuple[str, str]:
        content = [
            {
                'type': 'input_text',
                'text': CAPTION_PROMPT.strip(),
            },
            {'type': 'input_image', 'image_url': data_url},
        ]
        return await self.collect_text_response(content)

    async def describe_image(self, data_url: str) -> tuple[str, str]:
        content = [
            {
                'type': 'input_text',
                'text': DESCRIPTION_PROMPT.strip(),
            },
            {'type': 'input_image', 'image_url': data_url},
        ]
        return await self.collect_text_response(content)

    async def modify_image(self, data_url: str, instruction: str, size: str) -> tuple[Image.Image, str]:
        prompt = MODIFICATION_PROMPT.format(instruction=instruction, size=size).strip()
        content = [
            {'type': 'input_text', 'text': prompt},
            {'type': 'input_image', 'image_url': data_url},
        ]
        return await self.collect_image_response(content)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print_usage(self.model, self.usage)


def _empty_reasoning(title: str, reasoning: str) -> str:
    if not reasoning:
        return ''
    return f'## {title}\n\n{reasoning}'

async def _run_caption(image_path: str | None, agent: ImageAgent):
    image = load_image(image_path)
    data_url = pil_to_data_url(image, src_path=image_path)
    caption, reasoning = await agent.caption_image(data_url)
    return caption, agent.usage_markdown, _empty_reasoning('Caption', reasoning), agent


async def _run_description(image_path: str | None, agent: ImageAgent):
    image = load_image(image_path)
    data_url = pil_to_data_url(image, src_path=image_path)
    description, reasoning = await agent.describe_image(data_url)
    return description, agent.usage_markdown, _empty_reasoning('Description', reasoning), agent


async def _run_modification(image_path: str | None, instruction: str, size: str, agent: ImageAgent):
    if not instruction.strip():
        raise gr.Error('Please enter a modification instruction.')

    image = load_image(image_path)
    data_url = pil_to_data_url(image, src_path=image_path)
    edited_image, reasoning = await agent.modify_image(data_url, instruction, size)
    return (
        edited_image,
        _image_size_text(edited_image, 'Edited image'),
        agent.usage_markdown,
        _empty_reasoning('Modification', reasoning),
        agent,
    )


def _main_gradio(agent_args):
    css = """
    .gradio-container, .gradio-app, .gradio-root {
      max-width: 1800px !important;
      margin-left: auto !important;
      margin-right: auto !important;
    }

    #caption-box textarea,
    #description-box textarea,
    #reasoning-md,
    #usage-md {
      overflow-y: auto !important;
    }

    #caption-box textarea {
      max-height: 7em !important;
    }

    #description-box textarea {
      max-height: 12em !important;
    }

    #reasoning-md,
    #usage-md {
      max-height: 420px;
    }

    .image-meta {
      margin-top: -0.35rem;
      font-size: 0.82rem;
      color: #555;
    }

    .action-btn button {
      min-height: 48px !important;
      font-size: 0.95rem !important;
      font-weight: 600 !important;
      border-radius: 10px !important;
      padding: 0.6rem 1rem !important;
      width: 100% !important;
    }
    """

    with gr.Blocks(css=css, theme=gr.themes.Monochrome(), title='Image Understanding and Editing') as demo:
        agent_state = gr.State()

        gr.Markdown("# Image Understanding and Editing")
        gr.Markdown(
            "Upload an image to generate a short caption, a fuller description, or an edited version of the image based on your instruction. "
            "Each action sends the image through the Responses API, updates the usage panel, and can optionally surface model reasoning summaries. "
        )

        with gr.Row():
            with gr.Column(scale=2):
                image_input = gr.Image(
                    label='Input Image',
                    sources=['upload'],
                    type='filepath',
                    height=420,
                )
                input_size_view = gr.Markdown(elem_classes='image-meta')
                with gr.Row():
                    caption_button = gr.Button(
                        'Generate Caption',
                        variant='secondary',
                        elem_classes='action-btn',
                    )
                    describe_button = gr.Button(
                        'Describe Image',
                        variant='secondary',
                        elem_classes='action-btn',
                    )
                modify_instruction = gr.Textbox(
                    label='Modification Instruction',
                    value=DEFAULT_MODIFY_PROMPT,
                    lines=3,
                )
                size_dropdown = gr.Dropdown(
                    label='Edited Image Size',
                    choices=['1024x1024', "1536x1024", "1024x1536"],
                    value=DEFAULT_IMAGE_SIZE,
                )
                modify_button = gr.Button(
                    'Edit Image',
                    variant='primary',
                    elem_classes='action-btn',
                )

            with gr.Column(scale=2):
                caption_box = gr.Textbox(
                    label='Caption',
                    lines=3,
                    max_lines=3,
                    elem_id='caption-box',
                )
                description_box = gr.Textbox(
                    label='Description',
                    lines=6,
                    max_lines=6,
                    elem_id='description-box',
                )
                image_output = gr.Image(
                    label='Edited Image',
                    type='pil',
                    height=520,
                )
                output_size_view = gr.Markdown(elem_classes='image-meta')

            with gr.Column(scale=1):
                usage_view = gr.Markdown("", elem_id='usage-md')
                reasoning_view = gr.Markdown("", elem_id='reasoning-md')

        async def run_caption(image_path, agent):
            try:
                return await _run_caption(image_path, agent)
            except Exception as exc:
                return "", (agent.usage_markdown if agent else format_usage_markdown(DEFAULT_MODEL, [])), (
                    f"Caption failed: {exc}\n\n```text\n{traceback.format_exc()}\n```"
                ), agent

        async def run_description(image_path, agent):
            try:
                return await _run_description(image_path, agent)
            except Exception as exc:
                return "", (agent.usage_markdown if agent else format_usage_markdown(DEFAULT_MODEL, [])), (
                    f"Description failed: {exc}\n\n```text\n{traceback.format_exc()}\n```"
                ), agent

        async def run_modification(image_path, instruction, size, agent):
            try:
                return await _run_modification(image_path, instruction, size, agent)
            except Exception as exc:
                return None, '', (agent.usage_markdown if agent else format_usage_markdown(DEFAULT_MODEL, [])), (
                    f"Image edit failed: {exc}\n\n```text\n{traceback.format_exc()}\n```"
                ), agent

        demo.load(
            fn=lambda: (ImageAgent(**agent_args), format_usage_markdown(agent_args["model"], [])),
            outputs=[agent_state, usage_view],
        )

        image_input.change(
            fn=lambda image_path: _image_size_from_path(image_path, 'Uploaded image'),
            inputs=[image_input],
            outputs=[input_size_view],
        )

        caption_button.click(
            fn=run_caption,
            inputs=[image_input, agent_state],
            outputs=[caption_box, usage_view, reasoning_view, agent_state],
        )
        describe_button.click(
            fn=run_description,
            inputs=[image_input, agent_state],
            outputs=[description_box, usage_view, reasoning_view, agent_state],
        )
        modify_button.click(
            fn=run_modification,
            inputs=[image_input, modify_instruction, size_dropdown, agent_state],
            outputs=[image_output, output_size_view, usage_view, reasoning_view, agent_state],
        )

    demo.launch()


def main(prompt_path: Path, model: str, show_reasoning: bool, reasoning_effort: str | None):
    agent_args = dict(
        model=model,
        prompt=prompt_path.read_text() if prompt_path else "",
        show_reasoning=show_reasoning,
        reasoning_effort=reasoning_effort,
    )
    _main_gradio(agent_args)


if __name__ == "__main__":
    parser = argparse.ArgumentParser('ImageDesc')
    parser.add_argument('prompt_file', nargs="?", type=Path, default=None)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--show-reasoning', action="store_true")
    parser.add_argument('--reasoning-effort', default='low')
    args = parser.parse_args()
    main(args.prompt_file, args.model, args.show_reasoning, args.reasoning_effort)
