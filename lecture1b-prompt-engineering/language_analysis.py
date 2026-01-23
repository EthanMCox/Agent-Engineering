import argparse
import json
import sys
from pathlib import Path
from time import time

from openai import OpenAI
from pydantic import BaseModel

from usage import print_usage


class LanguageAnalysis(BaseModel):
    language: str
    known_language: bool
    greeting: str | None
    fact: str | None

def load_languages(language_file: Path) -> list[str]:
    """Load languages from file, one per line."""
    with open(language_file, 'r', encoding='utf-8') as f:
        return [line.strip() for line in f if line.strip()]


def main(model: str, prompt: str, languages: list[str]):
    client = OpenAI()
    usages = []

    start = time()
    for language in languages:
        print(f"{'-' * 50}\nLANGUAGE: {language}\n")
        
        full_prompt = f"{prompt}\n\n{language}"
        
        response = client.responses.parse(
            model=model,
            input=full_prompt,
            reasoning={'effort': 'low'},
            text_format=LanguageAnalysis
        )
        
        # Pretty print the JSON output
        json_data = json.loads(response.output_text)
        print(json.dumps(json_data, indent=2, ensure_ascii=False))
        print()
        
        usages.append(response.usage)

    print(f'{round(time()-start, 2)} seconds elapsed', file=sys.stderr)
    print_usage(model, usages)


if __name__ == "__main__":
    parser = argparse.ArgumentParser('Language Analysis')
    parser.add_argument('prompt_file', type=Path)
    parser.add_argument('input_file', type=Path)
    parser.add_argument('--model', default='gpt-5-nano')
    args = parser.parse_args()

    prompt_text = args.prompt_file.read_text(encoding='utf-8')
    languages = load_languages(args.input_file)
    
    main(args.model, prompt_text, languages)
