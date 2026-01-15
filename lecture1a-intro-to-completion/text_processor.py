import argparse
import sys
import yaml
from pathlib import Path
from time import time

from openai import OpenAI

from usage import print_usage


def main(model: str, prompt: str, sports_texts: dict):
    client = OpenAI()
    print(f"\nPROMPT: {prompt}")
    usages = []
    start = time()

    for url, text in sports_texts.items():
        print(f"\n{'-' * 60}\n{url}\n\n{text}\nRESPONSE: ")
        model_input = f"{prompt}\n{text}"
        response = client.responses.create(
            model=model,
            input=model_input,
            reasoning={'effort': 'low'}
        )
        print(response.output_text)
        usages.append(response.usage)

    print(f'\n\n{round(time()-start, 2)} seconds elapsed', file=sys.stdout)
    print_usage(model, usages, file=sys.stdout)


# Launch app
if __name__ == "__main__":
    parser = argparse.ArgumentParser('AI Response')
    parser.add_argument('prompt_file', type=Path)
    parser.add_argument('--sports_file', type=Path, default='sports-articles.yaml')
    parser.add_argument('--model', default='gpt-5-nano')
    args = parser.parse_args()
    with open(args.sports_file, "r") as f:
        sports_data = yaml.safe_load(f)

    main(args.model, args.prompt_file.read_text(), sports_data)
