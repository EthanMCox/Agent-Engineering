#!/bin/sh
# Start the sandbox container in the background
docker run -d \
  --name sandbox-bot \
  --rm \
  --network none \
  --cpus="1.0" \
  --memory="512m" \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  sandbox-bot:latest
