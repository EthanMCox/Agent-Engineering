from pathlib import Path
from time import time
import sys

from openai import Client

from usage import print_usage


def _swap_roles(history):
    swapped = []
    for message in history:
        role = message['role']
        if role == 'user':
            role = 'assistant'
        elif role == 'assistant':
            role = 'user'
        swapped.append({'role': role, 'content': message['content']})
    return swapped


def main(prompt_a, prompt_b):
    client = Client()
    model = "gpt-5-nano"

    history = []
    usage = []

    try:
        while True:
            start = time()

            response_a = client.responses.create(
                model=model,
                input=[{'role': 'system', 'content': prompt_a}] + history,
                reasoning={'effort': 'low'}
            )
            history.append({'role': 'assistant', 'content': response_a.output_text})
            usage.append(response_a.usage)
            print('Agent A:', response_a.output_text)
            print('----------------------------------')
            print()

            swapped_history = _swap_roles(history)
            response_b = client.responses.create(
                model=model,
                input=[{'role': 'system', 'content': prompt_b}] + swapped_history,
                reasoning={'effort': 'low'}
            )
            usage.append(response_b.usage)
            history.append({'role': 'user', 'content': response_b.output_text})
            print('Agent B:', response_b.output_text)
            print('----------------------------------')
            print()

            print(f'Round took {round(time() - start, 2)} seconds')
            # cont = input("Press Enter to continue, or type 'q' to stop: ").strip().lower()
            # if cont == 'q':
            #     break
    except KeyboardInterrupt:
        pass

    print_usage(model, usage)


if __name__ == '__main__':
    main(Path(sys.argv[1]).read_text(), Path(sys.argv[2]).read_text())
