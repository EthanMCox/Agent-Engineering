import argparse
import base64
import io
import traceback
from pathlib import Path

import gradio as gr
from openai import AsyncOpenAI
from PIL import Image

from usage import format_usage_markdown, print_usage

DEFAULT_MODEL = 'gpt-5-nano'
DEFAULT_PARTIAL_IMAGES = 3
DEFAULT_PROMPT = 'A watercolor landscape of Zion National Park at sunrise.'

SAMPLE_PROMPTS = [
    '',
    'A mountain lake fed by a waterfall with a sunset in the background.',
    'A watercolor landscape of Zion National Park at sunrise.',
    'A vintage poster of a steam locomotive crossing a canyon.',
    'A view inside Lavell Edwards stadium from the 50 yard line during a football game.',
]


def _b64_to_pil(b64_data: str) -> Image.Image:
    raw = base64.b64decode(b64_data)
    with Image.open(io.BytesIO(raw)) as image:
        return image.convert('RGB')


def _image_size_text(image: Image.Image | None, prefix: str = 'Generated image') -> str:
    if image is None:
        return ''
    return f'{prefix}: {image.width} x {image.height}px'


class ImageGenerationAgent:
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

    async def stream_image_generation(
        self,
        prompt: str,
        partial_images: int,
        previous_response_id: str | None = None,
    ):
        if not prompt.strip():
            raise gr.Error('Please enter an image prompt first.')

        request = {
            'model': self.model,
            'input': prompt.strip(),
            'stream': True,
            'tools': [{'type': 'image_generation', 'partial_images': partial_images}],
        }
        if self.reasoning:
            request['reasoning'] = self.reasoning
        if self._prompt:
            request['instructions'] = self._prompt
        if previous_response_id:
            request['previous_response_id'] = previous_response_id

        try:
            stream = await self._ai.responses.create(**request)
        except Exception as exc:
            raise gr.Error(f'Image generation failed: {exc}') from exc

        response_id = previous_response_id
        reasoning_text = ''
        final_image = None

        async for event in stream:
            if event.type == 'response.created':
                response_id = event.response.id

            elif event.type == 'response.reasoning_summary_text.delta':
                reasoning_text += event.delta

            elif event.type == 'response.image_generation_call.partial_image':
                b64 = getattr(event, 'partial_image_b64', None)
                if b64:
                    final_image = _b64_to_pil(b64)
                    yield final_image, response_id, reasoning_text, False

            elif event.type == 'response.completed':
                usage = getattr(event.response, 'usage', None)
                if usage is not None:
                    self.usage.append(usage)
                    self.usage_markdown = format_usage_markdown(self.model, self.usage)

                output = getattr(event.response, 'output', []) or []
                for item in output:
                    if getattr(item, 'type', None) == 'image_generation_call' and getattr(item, 'result', None):
                        final_image = _b64_to_pil(item.result)
                    elif getattr(item, 'type', None) == 'reasoning':
                        for chunk in getattr(item, 'summary', []) or []:
                            reasoning_text += getattr(chunk, 'text', '')

                yield final_image, response_id, reasoning_text.strip(), True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print_usage(self.model, self.usage)


def _reasoning_markdown(reasoning: str) -> str:
    if not reasoning.strip():
        return ''
    return f'## Generation\n\n{reasoning.strip()}'


def _make_agent(agent_args: dict) -> ImageGenerationAgent:
    return ImageGenerationAgent(
        model=agent_args['model'],
        prompt=agent_args['prompt'],
        show_reasoning=agent_args['show_reasoning'],
        reasoning_effort=agent_args['reasoning_effort'],
    )


def _main_gradio(agent_args):
    css = """
    .gradio-container, .gradio-app, .gradio-root {
      max-width: 1800px !important;
      margin-left: auto !important;
      margin-right: auto !important;
    }

    #prompt-box textarea,
    #reasoning-md,
    #usage-md {
      overflow-y: auto !important;
    }

    #prompt-box textarea {
      max-height: 9em !important;
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

    with gr.Blocks(title='Image Generation') as demo:
        agent_state = gr.State()
        response_id_state = gr.State(value=None)

        gr.Markdown('# Image Generation')
        gr.Markdown(
            'Enter a prompt to generate an image, optionally stream partial previews, and then use a revised prompt to continue editing from the previous response. '
            'The center panel shows the current generated image and its size, while the right panel tracks usage and any reasoning summaries returned by the model. '
        )

        with gr.Row():
            with gr.Column(scale=3):
                prompt_box = gr.Textbox(
                    label='Image Prompt',
                    value=agent_args.get('default_prompt', DEFAULT_PROMPT),
                    lines=4,
                    max_lines=4,
                    elem_id='prompt-box',
                )
                sample_prompts = gr.Dropdown(
                    label='Sample Prompts',
                    choices=SAMPLE_PROMPTS,
                    value='',
                )
                model_dropdown = gr.Dropdown(
                    label='Model',
                    choices=['gpt-4.1', 'gpt-4.1-mini', 'gpt-5', 'gpt-5-mini', 'gpt-5-nano'],
                    value=agent_args['model'],
                )
                partial_slider = gr.Slider(
                    minimum=0,
                    maximum=3,
                    step=1,
                    value=DEFAULT_PARTIAL_IMAGES,
                    label='Partial Images',
                )
                with gr.Row():
                    generate_button = gr.Button(
                        'Generate Image',
                        variant='primary',
                        elem_classes='action-btn',
                    )
                    modify_button = gr.Button(
                        'Modify Previous',
                        variant='secondary',
                        elem_classes='action-btn',
                    )

            with gr.Column(scale=6):
                generated_image = gr.Image(
                    label='Generated Image',
                    type='pil',
                    height=560,
                )
                image_size_view = gr.Markdown(elem_classes='image-meta')
                response_id_view = gr.Markdown(elem_classes='image-meta')

            with gr.Column(scale=1):
                usage_view = gr.Markdown('', elem_id='usage-md')
                reasoning_view = gr.Markdown('', elem_id='reasoning-md')

        sample_prompts.change(
            fn=lambda value: gr.update(value=value or ''),
            inputs=[sample_prompts],
            outputs=[prompt_box],
        )

        async def run_generation(prompt, model, partial_images, previous_response_id, agent, is_modify):
            if agent is None:
                agent = _make_agent(agent_args)

            agent.model = model

            if is_modify and not previous_response_id:
                raise gr.Error('Generate an image first before using Modify Previous.')

            current_image = None
            current_response_id = previous_response_id
            current_reasoning = ''

            try:
                async for image, response_id, reasoning, completed in agent.stream_image_generation(
                    prompt=prompt,
                    partial_images=int(partial_images),
                    previous_response_id=previous_response_id if is_modify else None,
                ):
                    if image is not None:
                        current_image = image
                    if response_id:
                        current_response_id = response_id
                    current_reasoning = reasoning

                    response_id_text = (
                        f'Current response id: `{current_response_id}`' if current_response_id else ''
                    )
                    yield (
                        current_image,
                        _image_size_text(current_image),
                        response_id_text,
                        agent.usage_markdown,
                        _reasoning_markdown(current_reasoning),
                        current_response_id,
                        agent,
                    )

            except Exception as exc:
                usage_markdown = agent.usage_markdown if agent else format_usage_markdown(model, [])
                yield (
                    current_image,
                    _image_size_text(current_image),
                    f'Current response id: `{current_response_id}`' if current_response_id else '',
                    usage_markdown,
                    f'Generation failed: {exc}\n\n```text\n{traceback.format_exc()}\n```',
                    current_response_id,
                    agent,
                )

        demo.load(
            fn=lambda: (_make_agent(agent_args), format_usage_markdown(agent_args['model'], [])),
            outputs=[agent_state, usage_view],
        )

        async def generate_handler(prompt, model, partial, agent):
            async for update in run_generation(prompt, model, partial, None, agent, False):
                yield update

        async def modify_handler(prompt, model, partial, response_id, agent):
            async for update in run_generation(prompt, model, partial, response_id, agent, True):
                yield update

        generate_button.click(
            fn=generate_handler,
            inputs=[prompt_box, model_dropdown, partial_slider, agent_state],
            outputs=[
                generated_image,
                image_size_view,
                response_id_view,
                usage_view,
                reasoning_view,
                response_id_state,
                agent_state,
            ],
        )
        modify_button.click(
            fn=modify_handler,
            inputs=[prompt_box, model_dropdown, partial_slider, response_id_state, agent_state],
            outputs=[
                generated_image,
                image_size_view,
                response_id_view,
                usage_view,
                reasoning_view,
                response_id_state,
                agent_state,
            ],
        )

    demo.launch(css=css, theme=gr.themes.Monochrome())


def main(prompt_path: Path, model: str, show_reasoning: bool, reasoning_effort: str | None):
    agent_args = {
        'model': model,
        'prompt': prompt_path.read_text() if prompt_path else '',
        'default_prompt': DEFAULT_PROMPT,
        'show_reasoning': show_reasoning,
        'reasoning_effort': reasoning_effort,
    }
    _main_gradio(agent_args)


if __name__ == '__main__':
    parser = argparse.ArgumentParser('ImageGen')
    parser.add_argument('prompt_file', nargs='?', type=Path, default=None)
    parser.add_argument('--model', default=DEFAULT_MODEL)
    parser.add_argument('--show-reasoning', action='store_true')
    parser.add_argument('--reasoning-effort', default='low')
    args = parser.parse_args()
    main(args.prompt_file, args.model, args.show_reasoning, args.reasoning_effort)
