# Before running this script:
# pip install gradio openai

# This version uses the OpenAI Assistants API with file_search tool
# To use file_search, you need to:
# 1. Upload your scripture files to OpenAI
# 2. Create a vector store with those files
# 3. Pass the vector_store_id when creating the agent

import argparse
import asyncio
import io
import json
import sys
from pathlib import Path

import gradio as gr
from openai import AsyncOpenAI

from tools import ToolBox
from usage import print_usage, format_usage_markdown

our_tools = ToolBox()

# # if you want to try the superbowl "database" use this
from superbowldb import get_superbowl_info
our_tools.tool(get_superbowl_info)
#
# # if you want to try executing code in the container from the docker directory use this
# from codebot import execute_code
# our_tools.tool(execute_code)

def _exec_python(code) -> tuple[str, str]:
    out_buffer = io.StringIO()
    err_buffer = io.StringIO()

    original_stdout = sys.stdout
    original_stderr = sys.stderr
    try:
        sys.stdout = out_buffer
        sys.stderr = err_buffer
        try:
            exec(code, {})  # isolated global namespace
        except:
            import traceback as tb
            tb.format_exc()
    finally:
        sys.stdout = original_stdout
        sys.stderr = original_stderr
    return out_buffer.getvalue(), err_buffer.getvalue()


@our_tools.tool
def exec_python(code: str) -> tuple[str, str]:
    """Execute the provided python code. STDOUT and STDERR are returned."""
    print()
    print(' Agent Code '.center(40, '-'))
    print(code)
    print('-' * 40)
    response = input('Allow? [y/N] ')

    if response.lower() == 'y':
        return _exec_python(code)

    print()
    return 'This code was not approved by the user. Discuss with them an alternative.'


class ChatAgent:
    def __init__(self, model: str, prompt: str, show_reasoning: bool, reasoning_effort: str | None, vector_store_id: str | None = None):
        self._ai = AsyncOpenAI()
        self.model = model
        self.show_reasoning = show_reasoning
        self.vector_store_id = vector_store_id
        
        # Note: reasoning parameters are not directly supported in Assistants API
        # but we keep them for consistency
        self.reasoning = {}
        if show_reasoning:
            self.reasoning['summary'] = 'auto'
        if 'gpt-5' in self.model and reasoning_effort:
            self.reasoning['effort'] = reasoning_effort

        self.usage = []
        self.usage_markdown = format_usage_markdown(self.model, [])

        self._prompt = prompt
        self._assistant = None
        self._thread = None

    async def _ensure_assistant(self):
        """Create the assistant if it doesn't exist"""
        if self._assistant is None:
            tools = []
            
            # Convert tools from responses API format to Assistants API format
            # responses API: {"type": "function", "name": ..., "description": ..., "parameters": ...}
            # Assistants API: {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
            for tool in our_tools.tools:
                if tool["type"] == "function":
                    tools.append({
                        "type": "function",
                        "function": {
                            "name": tool["name"],
                            "description": tool["description"],
                            "parameters": tool["parameters"],
                            "strict": tool.get("strict", True)
                        }
                    })
            
            tool_resources = {}
            
            # Add file_search tool if vector_store_id is provided
            if self.vector_store_id:
                tools.append({"type": "file_search"})
                tool_resources["file_search"] = {
                    "vector_store_ids": [self.vector_store_id]
                }
            
            self._assistant = await self._ai.beta.assistants.create(
                name="Scripture Assistant",
                instructions=self._prompt or "You are a helpful assistant.",
                model=self.model,
                tools=tools,
                tool_resources=tool_resources if tool_resources else None
            )

    async def _ensure_thread(self):
        """Create the thread if it doesn't exist"""
        if self._thread is None:
            self._thread = await self._ai.beta.threads.create()

    async def get_response(self, user_message: str):
        await self._ensure_assistant()
        await self._ensure_thread()

        # Add the user message to the thread
        await self._ai.beta.threads.messages.create(
            thread_id=self._thread.id,
            role="user",
            content=user_message
        )

        # Create a run and stream the response
        async with self._ai.beta.threads.runs.stream(
            thread_id=self._thread.id,
            assistant_id=self._assistant.id,
        ) as stream:
            async for event in stream:
                # Handle text deltas
                if event.event == 'thread.message.delta':
                    for content in event.data.delta.content:
                        if content.type == 'text':
                            if content.text.value:
                                yield 'output', content.text.value
                
                # Handle tool calls that require action
                elif event.event == 'thread.run.requires_action':
                    run = event.data
                    tool_outputs = []
                    
                    for tool_call in run.required_action.submit_tool_outputs.tool_calls:
                        if tool_call.type == 'function':
                            function_name = tool_call.function.name
                            arguments = json.loads(tool_call.function.arguments)
                            
                            yield 'reasoning', f'\n🔧 Calling: {function_name}({arguments})\n'
                            
                            # Execute the custom tool
                            func = our_tools.get_tool_function(function_name)
                            result = func(**arguments)
                            
                            yield 'reasoning', f'Result: {result}\n'
                            
                            tool_outputs.append({
                                "tool_call_id": tool_call.id,
                                "output": str(result)
                            })
                    
                    # Submit tool outputs and continue streaming
                    if tool_outputs:
                        async with self._ai.beta.threads.runs.submit_tool_outputs_stream(
                            thread_id=self._thread.id,
                            run_id=run.id,
                            tool_outputs=tool_outputs
                        ) as tool_stream:
                            async for tool_event in tool_stream:
                                if tool_event.event == 'thread.message.delta':
                                    for content in tool_event.data.delta.content:
                                        if content.type == 'text' and content.text.value:
                                            yield 'output', content.text.value
                
                # Handle file_search citations (appears in annotations)
                elif event.event == 'thread.message.completed':
                    message = event.data
                    for content in message.content:
                        if content.type == 'text':
                            # Check for annotations (file citations)
                            if content.text.annotations:
                                citations = []
                                for annotation in content.text.annotations:
                                    if hasattr(annotation, 'file_citation'):
                                        citation = annotation.file_citation
                                        citations.append(f"[File: {citation.file_id}]")
                                
                                if citations:
                                    yield 'reasoning', f'\n📚 Sources: {", ".join(citations)}\n'
                
                # Track usage if available
                elif event.event == 'thread.run.completed':
                    run = event.data
                    if hasattr(run, 'usage') and run.usage:
                        # Convert Assistants API usage format to responses API format
                        # Assistants API: prompt_tokens, completion_tokens
                        # Responses API: input_tokens, output_tokens
                        try:
                            # Create a mock usage object compatible with usage.py
                            class UsageAdapter:
                                def __init__(self, assistant_usage):
                                    self.input_tokens = getattr(assistant_usage, 'prompt_tokens', 0)
                                    self.output_tokens = getattr(assistant_usage, 'completion_tokens', 0)
                                    
                                    # Create nested objects for details
                                    class InputDetails:
                                        def __init__(self):
                                            self.cached_tokens = 0
                                    
                                    class OutputDetails:
                                        def __init__(self):
                                            self.reasoning_tokens = 0
                                    
                                    self.input_tokens_details = InputDetails()
                                    self.output_tokens_details = OutputDetails()
                            
                            self.usage.append(UsageAdapter(run.usage))
                            self.usage_markdown = format_usage_markdown(self.model, self.usage)
                        except Exception as e:
                            # If usage tracking fails, just skip it
                            print(f"Warning: Could not track usage: {e}")

    async def cleanup(self):
        """Clean up resources"""
        # Optionally delete the assistant and thread
        # In production, you might want to keep these for conversation history
        pass

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print_usage(self.model, self.usage)
        # Note: Can't call async cleanup here, would need different approach


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

            last_type = ''
            async for text_type, text in agent.get_response(message):
                if text_type == 'output' and not reasoning_complete:
                    print()
                    print('-' * 30)
                    print()
                    print('Agent: ')
                    reasoning_complete = True

                if last_type != text_type:
                    print(f'\n{text_type}: ', end='', flush=True)       # emit a newline between types
                    last_type = text_type

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

    with gr.Blocks() as demo:
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

    demo.launch(css=css, theme=gr.themes.Monochrome())


def main(prompt_path: Path, model: str, show_reasoning, reasoning_effort: str | None, use_web: bool, vector_store_id: str | None):
    agent_args = dict(
        model=model,
        prompt=prompt_path.read_text() if prompt_path else '',
        show_reasoning=show_reasoning,
        reasoning_effort=reasoning_effort,
        vector_store_id=vector_store_id
    )

    if use_web:
        _main_gradio(agent_args)
    else:
        asyncio.run(_main_console(agent_args))


# Launch app
if __name__ == "__main__":
    parser = argparse.ArgumentParser('ChatBot with Scripture Search')
    parser.add_argument('prompt_file', nargs='?', type=Path, default=None)
    parser.add_argument('--web', action='store_true')
    parser.add_argument('--model', default='gpt-4o')
    parser.add_argument('--show-reasoning', action='store_true')
    parser.add_argument('--reasoning-effort', default='low')
    parser.add_argument('--vector-store-id', type=str, default=None, 
                       help='Vector store ID for file search (from OpenAI)')
    args = parser.parse_args()
    main(args.prompt_file, args.model, args.show_reasoning, args.reasoning_effort, args.web, args.vector_store_id)

