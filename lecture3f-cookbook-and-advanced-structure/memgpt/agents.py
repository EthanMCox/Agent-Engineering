import argparse
import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import yaml
from openai import AsyncOpenAI

from run_agent import run_agent, as_tool, Agent, conclude, current_agent, current_memory
from tools import ToolBox
from usage import print_usage

LOG_FORMAT = '%(filename)-10.10s %(levelname)-4.4s %(asctime)s %(message)s'

toolbox = ToolBox()
toolbox.tool(conclude)


def _require_memory():
    memory = current_memory.get()
    if not memory or not memory.enabled:
        raise RuntimeError('Memory is not enabled for the current agent.')
    return memory


@toolbox.tool
def talk_to_user(message: str):
    """
    Use this function to communicate with the user.
    All communication to and from the user **MUST**
    be through this tool.
    :param message: The message to send to the user.
    :return: The user's response.
    """
    _agent = current_agent.get()
    name = _agent['name'] if _agent else 'Agent'
    print(f'{name}: {message}')
    return input('User: ')


@toolbox.tool
def append_core_memory(section: str, content: str) -> str:
    """
    Append durable information to core memory.
    :param section: The core memory section to update: persona or user.
    :param content: The text to append.
    :return: A status message.
    """
    memory = _require_memory()
    return memory.append_core_memory(section, content)


@toolbox.tool
def replace_core_memory(section: str, content: str) -> str:
    """
    Replace a core memory section.
    :param section: The core memory section to replace: persona or user.
    :param content: The new text for the section.
    :return: A status message.
    """
    memory = _require_memory()
    return memory.replace_core_memory(section, content)


@toolbox.tool
def search_recall_memory(query: str, limit: int, offset: int | None = None) -> str:
    """
    Search chat and tool history stored in recall memory.
    :param query: Search text.
    :param limit: Number of results to return.
    :param offset: Pagination offset.
    :return: Formatted search results.
    """
    memory = _require_memory()
    results = memory.search_recall_memory(query, limit=limit, offset=offset or 0)
    return memory.format_search_results('Recall memory', query, results, 'text')


@toolbox.tool
def search_archival_memory(query: str, limit: int, offset: int | None = None) -> str:
    """
    Search archival memory stored on disk.
    :param query: Search text.
    :param limit: Number of results to return.
    :param offset: Pagination offset.
    :return: Formatted search results.
    """
    memory = _require_memory()
    results = memory.search_archival_memory(query, limit=limit, offset=offset or 0)
    return memory.format_search_results('Archival memory', query, results, 'content')


@toolbox.tool
def insert_archival_memory(content: str, metadata: str | None = None) -> str:
    """
    Store a note in archival memory.
    :param content: The content to persist.
    :param metadata: Optional JSON metadata.
    :return: The archival record identifier.
    """
    memory = _require_memory()
    parsed_metadata = json.loads(metadata) if metadata else None
    record_id = memory.insert_archival_memory(content, metadata=parsed_metadata)
    return f'Archived memory as {record_id}.'


@toolbox.tool
def show_memory_status() -> str:
    """
    Show token budgets and current memory usage.
    :return: Memory status text.
    """
    memory = _require_memory()
    return memory.status(current_agent.get().get('prompt'))


async def main(agent_config: Path, message: str):
    client = AsyncOpenAI()
    usages = []

    def add_to_toolbox(_agent):
        toolbox.tool(as_tool(client, toolbox, _agent, usage=usages))

    agents: list[Agent] = list(yaml.safe_load_all(agent_config.read_text()))

    for agent in agents:
        if agent['name'] == 'main':
            continue
        add_to_toolbox(agent)

    main_agent = next(agent for agent in agents if agent['name'] == 'main')

    response = await run_agent(
        client, toolbox, main_agent,
        message, usage=usages
    )

    if response:
        print(response)
        print()

    print_usage(usages)


def _configure_logging(debug: bool) -> None:
    local_level = logging.DEBUG if debug else logging.INFO
    use_dark_gray = (
            sys.stderr.isatty()
            and os.getenv('NO_COLOR') is None
            and os.getenv('TERM', '').lower() != 'dumb'
    )
    format_string = f'\x1b[90m{LOG_FORMAT}\x1b[0m' if use_dark_gray else LOG_FORMAT
    logging.basicConfig(
        level=logging.WARNING,
        format=format_string,
        datefmt='%H:%M:%S',
        force=True,
    )
    for logger_name in ('__main__', 'agents', 'run_agent', 'tools', 'usage'):
        logging.getLogger(logger_name).setLevel(local_level)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('agent_config', type=Path, nargs='?', default=Path('quotes.yaml'))
    parser.add_argument('message', nargs='?', default=None)
    parser.add_argument('--debug', action='store_true')
    args = parser.parse_args()
    _configure_logging(args.debug)
    asyncio.run(main(args.agent_config, args.message))
