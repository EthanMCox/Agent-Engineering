import argparse
import sys
from pathlib import Path
from time import time

from openai import OpenAI

from usage import print_usage


def main(model: str, prompt: str, text: str):
    client = OpenAI()
    prompt += text


    start = time()
    response = client.responses.create(
        model=model,
        input=prompt,
        reasoning={'effort': 'low'}
    )
    print(response.output_text)

    print(f'{round(time()-start, 2)} seconds elapsed', file=sys.stderr)
    print_usage(model, response.usage)


# Launch app
if __name__ == "__main__":
    parser = argparse.ArgumentParser('AI Response')
    parser.add_argument('prompt_file', type=Path)
    parser.add_argument('input_file', type=Path)
    parser.add_argument('--model', default='gpt-5-nano')
    args = parser.parse_args()
    main(args.model, args.prompt_file.read_text(), args.input_file.read_text())
