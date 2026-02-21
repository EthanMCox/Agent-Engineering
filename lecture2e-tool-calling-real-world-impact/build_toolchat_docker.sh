#!/usr/bin/env bash
set -euo pipefail

IMAGE_NAME="${1:-toolchat:latest}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cd "$SCRIPT_DIR"

docker build -t "$IMAGE_NAME" -f- . <<'DOCKERFILE'
FROM python:latest

WORKDIR /app

RUN pip install --no-cache-dir gradio openai canvasapi

COPY *.py /app/
COPY *.md /app/

CMD ["python", "toolbot.py", "prompt.md"]

DOCKERFILE

echo "Built Docker image: $IMAGE_NAME"
