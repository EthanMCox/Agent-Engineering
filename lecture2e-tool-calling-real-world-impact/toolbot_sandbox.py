# Before running this script:
# pip install gradio openai

# Sandbox Bot - AI agent with containerized filesystem access
# All file operations happen within the Docker container, not on your host

import argparse
import asyncio
import sys
from pathlib import Path

import gradio as gr
from openai import AsyncOpenAI

from tools import ToolBox
from usage import print_usage, format_usage_markdown
from superbowldb import get_superbowl_info

# Import sandbox tools
from sandbox_tools import (
    sandbox_read_file,
    sandbox_write_file,
    sandbox_list_files,
    sandbox_exec_python,
    sandbox_exec_command,
    sandbox_delete_file,
    sandbox_create_directory,
    check_sandbox_status
)

our_tools = ToolBox()

# Register superbowl tool (non-destructive)
our_tools.tool(get_superbowl_info)

# For console mode only - these tools will be registered without approval wrappers
# The approval happens in the get_response method instead

@our_tools.tool
def sandbox_read(path: str) -> str:
    """Read a file from the sandbox filesystem"""
    return sandbox_read_file(path)


@our_tools.tool
def sandbox_write(path: str, content: str) -> str:
    """Write content to a file in the sandbox filesystem"""
    return sandbox_write_file(path, content)


@our_tools.tool
def sandbox_list(path: str = "/sandbox") -> str:
    """List files in the sandbox directory"""
    return sandbox_list_files(path)


@our_tools.tool
def sandbox_python(code: str) -> str:
    """Execute Python code in the sandbox"""
    return sandbox_exec_python(code)


@our_tools.tool
def sandbox_command(command: str) -> str:
    """Execute a shell command in the sandbox"""
    return sandbox_exec_command(command)


@our_tools.tool
def sandbox_delete(path: str) -> str:
    """Delete a file from the sandbox (requires approval)"""
    return sandbox_delete_file(path)


@our_tools.tool
def sandbox_mkdir(path: str) -> str:
    """Create a directory in the sandbox (requires approval)"""
    return sandbox_create_directory(path)


@our_tools.tool
def sandbox_status() -> str:
    """Check if the sandbox container is running (no approval needed)"""
    return check_sandbox_status()


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
        
        # Process the response
        async for item_type, item_data in self._continue_response():
            yield item_type, item_data
    
    async def _continue_response(self):
        """Continue processing the conversation (used internally and after function execution)"""
        while True:
            response = await self._ai.responses.create(
                input=self._history,
                model=self.model,
                reasoning=self.reasoning,
                tools=our_tools.tools
            )

            self.usage.append(response.usage)
            self.usage_markdown = format_usage_markdown(self.model, self.usage)
            
            # Store reasoning to add later (must stay paired with function_call or message)
            reasoning_items = []
            has_function_calls = False
            first_function_call = True
            
            for item in response.output:
                if item.type == 'reasoning':
                    reasoning_items.append(item)
                    for chunk in item.summary:
                        yield 'reasoning', chunk.text

                elif item.type == 'function_call':
                    import json
                    has_function_calls = True
                    # Don't pass reasoning - it doesn't get added to history with function calls
                    yield 'function_call', {
                        'name': item.name,
                        'arguments': json.loads(item.arguments),
                        'call_id': item.call_id
                    }

                elif item.type == 'message':
                    # Add reasoning (if any) followed by message - they must stay paired
                    for r_item in reasoning_items:
                        self._history.append(r_item)
                    self._history.append(item)
                    
                    for chunk in item.content:
                        yield 'output', chunk.text
                    return
            
            # If there were function calls, stop and wait for them to be executed
            # Don't add reasoning for function calls - it doesn't get paired with them
            if has_function_calls:
                return
    
    def execute_function_call(self, name: str, arguments: dict, call_id: str, approved: bool = True) -> str:
        """Execute a function call and add result to history. Returns the result string."""
        if not approved:
            result = "Action denied by user"
        else:
            func = our_tools.get_tool_function(name)
            result = func(**arguments)
        
        # Add function call and output to history (no reasoning for function calls)
        import json
        
        self._history.append({
            'type': 'function_call',
            'call_id': call_id,
            'name': name,
            'arguments': json.dumps(arguments)
        })
        self._history.append({
            'type': 'function_call_output',
            'call_id': call_id,
            'output': str(result)
        })
        
        return str(result)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        print_usage(self.model, self.usage)


async def _main_console(agent_args):
    # Check sandbox status first
    print("\n" + "=" * 60)
    print(check_sandbox_status())
    print("=" * 60 + "\n")
    
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
            pending_function_calls = []
            async for text_type, text in agent.get_response(message):
                if text_type == 'function_call':
                    # Store function call for approval
                    pending_function_calls.append(text)
                    # Show what's being called
                    print(f"\n{'='*60}")
                    print(f"Function: {text['name']}")
                    print(f"Arguments: {text['arguments']}")
                    print(f"{'='*60}")
                    continue
                if text_type == 'output' and not reasoning_complete:
                    print()
                    print('-' * 30)
                    print()
                    print('Agent: ')
                    reasoning_complete = True

                if text_type == 'reasoning':
                    print(text, end='', flush=True)
                    last_type = text_type
                elif text_type == 'output':
                    print(text, end='', flush=True)
                    last_type = text_type

            if last_type: print()
            print()
            
            # Handle any pending function calls with approval
            while pending_function_calls:
                for fc in pending_function_calls:
                    # Ask for approval
                    try:
                        approval = input('Allow this action? [y/N] ').lower() == 'y'
                    except (EOFError, KeyboardInterrupt):
                        approval = False
                    
                    # Execute and show result
                    result = agent.execute_function_call(
                        fc['name'], 
                        fc['arguments'], 
                        fc['call_id'],
                        approved=approval
                    )
                    
                    if agent.show_reasoning:
                        print(f"Result: {result}\n")
                
                # Clear the list and continue processing
                pending_function_calls = []
                
                # Continue agent's processing with the function results
                print(' Continuing '.center(30, '-'))
                async for text_type, text in agent._continue_response():
                    if text_type == 'function_call':
                        # Another function call - add to queue
                        pending_function_calls.append(text)
                        print(f"\n{'='*60}")
                        print(f"Function: {text['name']}")
                        print(f"Arguments: {text['arguments']}")
                        print(f"{'='*60}")
                    elif text_type == 'reasoning':
                        print(text, end='', flush=True)
                    elif text_type == 'output':
                        if not reasoning_complete:
                            print()
                            print('-' * 30)
                            print()
                            print('Agent: ')
                            reasoning_complete = True
                        print(text, end='', flush=True)
                
                if not pending_function_calls:
                    print()
                    print()
                    break


def _main_gradio(agent_args):
    css = """
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


def main(prompt_path: Path, model: str, show_reasoning, reasoning_effort: str | None, use_web: bool):
    global _WEB_MODE
    _WEB_MODE = use_web
    
    agent_args = dict(
        model=model,
        prompt=prompt_path.read_text() if prompt_path else '',
        show_reasoning=show_reasoning,
        reasoning_effort=reasoning_effort
    )

    if use_web:
        print("\n" + "=" * 60)
        print("⚠️  WEB MODE: Human-in-the-loop approval is AUTO-APPROVED")
        print("    Actions will be automatically executed.")
        print("    Monitor the reasoning pane to see what's happening.")
        print("=" * 60 + "\n")
        _main_gradio(agent_args)
    else:
        asyncio.run(_main_console(agent_args))


# Launch app
if __name__ == "__main__":
    parser = argparse.ArgumentParser('Sandbox ChatBot')
    parser.add_argument('prompt_file', nargs='?', type=Path, default=None)
    parser.add_argument('--web', action='store_true')
    parser.add_argument('--model', default='gpt-5-nano')
    parser.add_argument('--show-reasoning', action='store_true')
    parser.add_argument('--reasoning-effort', default='low')
    args = parser.parse_args()
    main(args.prompt_file, args.model, args.show_reasoning, args.reasoning_effort, args.web)
