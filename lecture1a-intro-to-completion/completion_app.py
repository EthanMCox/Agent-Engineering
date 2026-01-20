import argparse
import sys
from pathlib import Path
from time import time

from openai import OpenAI

from usage import print_usage


def main(model: str, prompt: str, input_text: str | None = None):
    client = OpenAI()
    start = time()
    
    if input_text:
        full_prompt = f"{prompt}\n\n{input_text}"
    else:
        full_prompt = prompt
    
    response = client.responses.create(
        model=model,
        input=full_prompt,
        reasoning={'effort': 'low'}
    )
    
    print(response.output_text)
    
    print(f'\n{round(time()-start, 2)} seconds elapsed', file=sys.stderr)
    print_usage(model, response.usage)


if __name__ == "__main__":
    parser = argparse.ArgumentParser('AI Completion Response')
    parser.add_argument('prompt_file', type=Path, help='File containing the prompt/instructions')
    parser.add_argument('--input', type=Path, help='Optional input file to process with the prompt')
    parser.add_argument('--model', default='gpt-5-nano', help='Model to use (default: gpt-5-nano)')
    args = parser.parse_args()
    
    prompt_text = args.prompt_file.read_text(encoding='utf-8')
    input_text = args.input.read_text(encoding='utf-8') if args.input else None
    
    main(args.model, prompt_text, input_text)
