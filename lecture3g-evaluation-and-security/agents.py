import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import yaml
from openai import AsyncOpenAI

from run_agent import run_agent, as_tool, Agent, conclude, current_agent
from tools import ToolBox
from usage import print_usage

LOG_FORMAT = '%(filename)-10.10s %(levelname)-4.4s %(asctime)s %(message)s'

toolbox = ToolBox()
toolbox.tool(conclude)


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
