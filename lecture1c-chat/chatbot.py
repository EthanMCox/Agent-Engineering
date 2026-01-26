# Before running this script:
# pip install gradio openai

import argparse
import asyncio
import sys
from pathlib import Path

import gradio as gr
from openai import AsyncOpenAI

from usage import print_usage, format_usage_markdown


class ChatAgent:
    def __init__(self, model: str, prompt: str):
        self._ai = AsyncOpenAI()
        self.usage = []
        self.model = model
        self._prompt = prompt
        self._history = []
        if prompt:
            self._history.append({'role': 'system', 'content': prompt})

    async def get_response(self, user_message: str):
        self._history.append({'role': 'user', 'content': user_message})

        response = await self._ai.responses.create(
            input=self._history,
            model=self.model
        )
        self.usage.append(response.usage)
        self._history.extend(
            response.output
        )
        return response.output_text

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print_usage(self.model, self.usage)


async def _main_console(agent):
    while True:
        message = input('User: ')
        if not message:
            break
        response = await agent.get_response(message)
        print('Agent:', response)


def _main_gradio(agent):
    # Constrain width with CSS and center
    css = """
    /* limit overall Gradio app width and center it */
    .gradio-container, .gradio-app, .gradio-root {
      width: 120ch;
      max-width: 120ch !important;
      margin-left: auto !important;
      margin-right: auto !important;
      box-sizing: border-box !important;
    }
    """

    usage_view = gr.Markdown(format_usage_markdown(agent.model, []))

    with gr.Blocks(css=css) as demo:
        async def get_response(message, chat_view_history):
            response = await agent.get_response(message)
            usage_content = format_usage_markdown(agent.model, agent.usage)
            return response, usage_content

        with gr.Row():
            with gr.Column(scale=5):
                bot = gr.Chatbot(
                    label=' ',
                    height=600,
                    resizable=True,
                )
                chat = gr.ChatInterface(
                    chatbot=bot,
                    fn=get_response,
                    additional_outputs=[usage_view]
                )

            with gr.Column(scale=1):
                usage_view.render()

    demo.launch()


def main(prompt_path: Path, model: str, use_web: bool):
    with ChatAgent(model, prompt_path.read_text(encoding='utf-8') if prompt_path else '') as agent:
        if use_web:
            _main_gradio(agent)
        else:
            asyncio.run(_main_console(agent))


# Launch app
if __name__ == "__main__":
    parser = argparse.ArgumentParser('ChatBot')
    parser.add_argument('prompt_file', nargs='?', type=Path, default=None)
    parser.add_argument('--web', action='store_true')
    parser.add_argument('--model', default='gpt-5-nano')
    args = parser.parse_args()
    main(args.prompt_file, args.model, args.web)
