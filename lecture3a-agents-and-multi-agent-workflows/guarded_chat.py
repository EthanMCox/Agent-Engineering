from pathlib import Path

import yaml
from openai import AsyncOpenAI

from run_agent import run_agent
from tools import ToolBox
from usage import print_usage

toolbox = ToolBox()


async def main(agent_config: Path):
    client = AsyncOpenAI()

    config = yaml.safe_load(agent_config.read_text())
    agents = {agent['name']: agent for agent in config['agents']}

    history = []
    usage = []
    print("What would you like to discuss? ")

    while True:
        message = input(">>> ")
        if not message:
            break

        response = await run_agent(
            client, toolbox, agents['chat'],
            message, history, usage
        )

        final_result = await run_agent(
            client, toolbox, agents['guardrail'],
            response, [], usage
        )

        print('Agent:', final_result)
        print()

    print_usage(agents['chat']['model'], usage)


if __name__ == '__main__':
    import sys
    import asyncio
    config_file = sys.argv[1] if len(sys.argv) > 1 else 'guardrails.yaml'

    asyncio.run(main(Path(config_file)))