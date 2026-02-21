# Before running this script:
# pip install gradio openai

import argparse
import asyncio
import json
import random
from pathlib import Path

import gradio as gr
from openai import AsyncOpenAI

from tools import ToolBox
from usage import print_usage, format_usage_markdown
from url_fetcher import fetch_url_content
from conference_tools import scrape_speaker_talks

our_tools = ToolBox()


@our_tools.tool
def get_random_number(lower: int, upper: int) -> int:
    """Get a random number"""
    return random.randint(lower, upper)


@our_tools.tool
def reverse_string(text: str) -> str:
    """Reverse a string by returning the characters in reverse order"""
    return text[::-1]


@our_tools.tool
def random_sample(items: list[str], sample_size: int, with_replacement: bool) -> list[str]:
    """Randomly sample items from a list with or without replacement.
    
    Args:
        items: The list of items to sample from
        sample_size: The number of items to sample
        with_replacement: If True, allows sampling the same item multiple times. If False, each item can only be selected once.
    """
    if with_replacement:
        return random.choices(items, k=sample_size)
    else:
        return random.sample(items, k=sample_size)


@our_tools.tool
def boolean_classifier(probability: float) -> bool:
    """Return True or False based on a probability threshold.
    
    Args:
        probability: A float between 0.0 and 1.0 representing the probability of returning True.
                    For example, 0.7 means 70% chance of True, 30% chance of False.
    """
    return random.random() < probability


@our_tools.tool
def get_url_content(url: str) -> str:
    """Fetch and extract text content from a URL, removing HTML tags and formatting.
    
    Args:
        url: The URL to fetch content from (must be http or https protocol)
    """
    try:
        return fetch_url_content(url)
    except Exception as e:
        return f"Error fetching URL: {str(e)}"


@our_tools.tool
def get_speaker_conference_talks(speaker_page_url: str, max_talks: int = 10) -> str:
    """Scrape talks from a General Conference speaker's page with configurable limit.
    
    Args:
        speaker_page_url: The URL to the speaker's General Conference page 
                         (e.g., https://www.churchofjesuschrist.org/study/general-conference/speakers/russell-m-nelson)
        max_talks: Maximum number of talks to retrieve (default: 10, max: 100). Higher values will take longer due to rate limiting.
    """
    try:
        # Cap at 100 and add delay for rate limiting
        limited_talks = min(max_talks, 100)
        # Adjust delay based on number of talks (more talks = longer delay to respect rate limits)
        delay = 1.5 if limited_talks <= 20 else 2.0
        return scrape_speaker_talks(speaker_page_url, max_talks=limited_talks, delay_between_talks=delay)
    except Exception as e:
        return f"Error fetching speaker talks: {str(e)}"



class ChatAgent:
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

        self._history = []
        self._prompt = prompt
        if prompt:
            self._history.append({'role': 'system', 'content': prompt})

    async def get_response(self, user_message: str):
        self._history.append({'role': 'user', 'content': user_message})

        while True:
            response = await self._ai.responses.create(
                input=self._history,
                model=self.model,
                reasoning=self.reasoning,
                tools=our_tools.tools
            )

            self.usage.append(response.usage)
            self.usage_markdown = format_usage_markdown(self.model, self.usage)
            self._history.extend(
                response.output
            )

            for item in response.output:
                if item.type == 'reasoning':
                    for chunk in item.summary:
                        yield 'reasoning', chunk.text

                elif item.type == 'function_call':
                    yield 'reasoning', f'{item.name}({item.arguments})'

                    func = our_tools.get_tool_function(item.name)
                    args = json.loads(item.arguments)
                    result = func(**args)
                    self._history.append({
                        'type': 'function_call_output',
                        'call_id': item.call_id,
                        'output': str(result)
                    })
                    yield 'reasoning', str(result)

                elif item.type == 'message':
                    for chunk in item.content:
                        yield 'output', chunk.text
                    return

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print_usage(self.model, self.usage)


async def _main_console(agent_args):
    with ChatAgent(**agent_args) as agent:
        while True:
            message = input('User: ')
            if not message:
                break

            reasoning_complete = True
            if agent.show_reasoning:
                print(' Reasoning '.center(30, '-'))
                reasoning_complete = False

            async for text_type, text in agent.get_response(message):
                if text_type == 'output' and not reasoning_complete:
                    print()
                    print('-' * 30)
                    print()
                    print('Agent: ')
                    reasoning_complete = True

                print(text, end='', flush=True)
            print()
            print()


def _main_gradio(agent_args):
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
    
    #reasoning-md {
        max-height: 300px;
        overflow-y: auto;
    }
    """

    reasoning_view = gr.Markdown('', elem_id='reasoning-md')
    usage_view = gr.Markdown('')

    with gr.Blocks(css=css, theme=gr.themes.Monochrome()) as demo:
        agent = gr.State()

        async def get_response(message, chat_view_history, agent):
            output = ""
            reasoning = ""

            async for text_type, text in agent.get_response(message):
                if text_type == 'reasoning':
                    reasoning += text
                elif text_type == 'output':
                    output += text
                else:
                    raise NotImplementedError(text_type)

                yield output, reasoning, agent.usage_markdown, agent

            yield output, reasoning, agent.usage_markdown, agent

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
                    additional_inputs=[agent],
                    additional_outputs=[reasoning_view, usage_view, agent]
                )

            with gr.Column(scale=1):
                reasoning_view.render()
                usage_view.render()

        demo.load(fn=lambda: ChatAgent(**agent_args), outputs=[agent])

    demo.launch()


def main(prompt_path: Path, model: str, show_reasoning, reasoning_effort: str | None, use_web: bool):
    agent_args = dict(
        model=model,
        prompt=prompt_path.read_text() if prompt_path else '',
        show_reasoning=show_reasoning,
        reasoning_effort=reasoning_effort

    )

    if use_web:
        _main_gradio(agent_args)
    else:
        asyncio.run(_main_console(agent_args))


# Launch app
if __name__ == "__main__":
    parser = argparse.ArgumentParser('ChatBot')
    parser.add_argument('prompt_file', nargs='?', type=Path, default=None)
    parser.add_argument('--web', action='store_true')
    parser.add_argument('--model', default='gpt-5-nano')
    parser.add_argument('--show-reasoning', action='store_true')
    parser.add_argument('--reasoning-effort', default='low')
    args = parser.parse_args()
    main(args.prompt_file, args.model, args.show_reasoning, args.reasoning_effort, args.web)
