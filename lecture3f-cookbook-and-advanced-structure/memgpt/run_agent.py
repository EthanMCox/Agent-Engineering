import asyncio
import json
import logging
import time
from contextvars import ContextVar
from typing import TypedDict

from memory import MemoryManager

current_agent = ContextVar('current_agent')
current_memory = ContextVar('current_memory', default=None)
logger = logging.getLogger(__name__)


class Agent(TypedDict):
    name: str
    description: str
    model: str
    prompt: str
    tools: list[str]
    kwargs: dict
    memory: dict


def conclude():
    """
    Conclude the conversation.
    """


async def run_agent(
        client,
        toolbox,
        agent: Agent,
        user_message: str = None,
        history=None,
        usage=None
) -> str | None:
    agent_token = current_agent.set(agent)
    model = agent.get('model', 'gpt-5-mini')
    memory = current_memory.get()
    if memory is None or memory.agent is not agent:
        memory = MemoryManager(agent, model)
    memory_token = current_memory.set(memory)

    try:
        if history is None:
            history = []
        if usage is None:
            usage = []

        if user_message:
            user_item = {'role': 'user', 'content': user_message}
            if memory.enabled:
                memory.append_fifo(user_item)
                memory.add_recall_item(user_item)
                memory.save()
            else:
                history.append(user_item)

        while True:
            prompt = agent.get('prompt')
            if memory.enabled:
                memory.maybe_add_memory_pressure_message(prompt)
                await memory.maybe_flush(client, prompt, usage)
                history_for_response = memory.build_input(prompt)
                memory.save()
            else:
                history_for_response = history
                if prompt:
                    history_for_response = history_for_response + [{'role': 'system', 'content': prompt}]

            start = time.time()
            logger.debug('AGENT %s', agent['name'])
            response = await client.responses.create(
                input=history_for_response,
                model=model,
                tools=toolbox.get_tools(agent.get('tools', [])),
                **agent.get('kwargs', {})
            )
            logger.debug(
                'RESPONSE from %s in %.2f seconds',
                agent['name'],
                time.time() - start,
            )

            usage.append((agent.get('model', response.model), response.usage))
            if memory.enabled:
                for item in response.output:
                    if item.type in {'message', 'function_call'}:
                        memory.append_fifo(item)
                    memory.add_recall_item(item)
                memory.save()
            else:
                history.extend(
                    response.output
                )

            # output -> we're done
            if outputs := [
                item
                for item in response.output
                if item.type == 'message'
            ]:
                return '\n'.join(
                    chunk.text
                    for item in outputs
                    for chunk in item.content
                )

            # tool calls
            tool_calls = {
                item.call_id: toolbox.run_tool(item.name, **json.loads(item.arguments))
                for item in response.output
                if item.type == 'function_call'
            }

            results = await asyncio.gather(*(
                asyncio.create_task(tool_call)
                for tool_call in tool_calls.values()
            ))

            for call_id, result in zip(tool_calls.keys(), results):
                output_item = {
                    'type': 'function_call_output',
                    'call_id': call_id,
                    'output': str(result)
                }
                if memory.enabled:
                    memory.append_fifo(output_item)
                    memory.add_recall_item(output_item)
                else:
                    history.append(output_item)

            if memory.enabled and tool_calls:
                memory.save()

            if any(
                    item.type == 'function_call'
                    and item.name == conclude.__name__
                    for item in response.output
            ):
                return None
    finally:
        current_memory.reset(memory_token)
        current_agent.reset(agent_token)


def as_tool(
        client, toolbox, agent,
        history=None,
        usage=None
):
    async def function(input: str) -> str:
        return await run_agent(
            client, toolbox, agent,
            user_message=input, history=history, usage=usage
        )

    function.__name__ = agent['name']
    function.__doc__ = agent.get('description', '')

    return function
