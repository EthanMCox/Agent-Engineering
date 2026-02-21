
build:
	docker build -t safe-container:latest .

run:
	docker run --rm --name llm-exec \
  --network none \
  --cpus="0.5" \
  --memory="256m" \
  --pids-limit=50 \
  --read-only \
  --tmpfs /tmp:rw,nosuid,nodev,mode=1777 \
  --cap-drop ALL \
  --user 1000:1000 \
  --security-opt no-new-privileges:true \
  -v ./task.py:/workspace/task.py:ro \
  safe-container:latest /workspace/task.py --timeout 10
