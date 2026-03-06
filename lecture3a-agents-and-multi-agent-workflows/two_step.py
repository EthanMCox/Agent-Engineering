from pathlib import Path

import yaml
from openai import AsyncOpenAI

from run_agent import run_agent
from tools import ToolBox
from usage import print_usage

toolbox = ToolBox()


async def main(agent_config: Path, post_config: Path, message: str):
    client = AsyncOpenAI()

    agent = yaml.safe_load(agent_config.read_text())
    second_agent = yaml.safe_load(post_config.read_text())

    history = []
    usage = []

    response = await run_agent(
        client, toolbox, agent,
        message, history, usage
    )

    final_result = await run_agent(
        client, toolbox, second_agent,
        response, [], usage
    )

    print('Agent:', final_result)
    print()
    print_usage(agent['model'], usage)


if __name__ == '__main__':
    import sys
    import asyncio

    asyncio.run(main(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]))
