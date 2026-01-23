import argparse
import json
import sys
from pathlib import Path
from time import time

import pandas as pd
from openai import OpenAI
from pydantic import BaseModel

from usage import print_usage


class EmailClassification(BaseModel):
    classification: int
    confidence: float
    threat_type: str
    risk_indicators: list[str]
    reasoning: str


# get the email data. Schema is: subject,body,label {0,1}
def load_data(prompt: str) -> pd.DataFrame:
    data = pd.read_csv('Ling.csv')
    num_samples = 10
    sampled_data = pd.concat([
        data[data.label == 1].iloc[:num_samples],
        data[data.label == 0].iloc[:num_samples]],
        ignore_index=True
    )

    def fmt_prompt(row):
        """
        Uses .format() to inject `row['subject']` and `row['body']`
        into the template in a single operation.
        """
        return prompt.format(**row)

    sampled_data["prompt"] = sampled_data.apply(fmt_prompt, axis=1)
    return sampled_data

def main(model: str, prompt: str):
    client = OpenAI()
    usages = []
    data = load_data(prompt)

    start = time()
    for row in data.itertuples():
        print(f"{'-' * 50}\nEXPECTED: {row.label}\n")
        response = client.responses.parse(
            model=model,
            input=str(row.prompt),
            reasoning={'effort': 'low'},
            text_format=EmailClassification
        )
        
        # Pretty print the JSON output
        json_data = json.loads(response.output_text)
        print(json.dumps(json_data, indent=2))
        print()
        
        usages.append(response.usage)

    print(f'{round(time()-start, 2)} seconds elapsed', file=sys.stderr)
    print_usage(model, usages)


# Launch app
if __name__ == "__main__":
    parser = argparse.ArgumentParser('AI Response')
    parser.add_argument('prompt_file', type=Path)
    parser.add_argument('--model', default='gpt-5-nano')
    args = parser.parse_args()

    main(args.model, args.prompt_file.read_text())
