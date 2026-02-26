
build:
	docker build -t sandbox-bot:latest .

start:
	docker run -d --name sandbox-bot --rm \
		--network none \
		--cpus="1.0" \
		--memory="512m" \
		--cap-drop ALL \
		--security-opt no-new-privileges:true \
		sandbox-bot:latest

stop:
	docker stop sandbox-bot

restart: stop start

status:
	@docker ps | grep sandbox-bot || echo "Container not running"

logs:
	docker logs sandbox-bot

shell:
	docker exec -it sandbox-bot /bin/bash

clean:
	docker stop sandbox-bot 2>/dev/null || true
	docker rmi sandbox-bot:latest 2>/dev/null || true

.PHONY: build start stop restart status logs shell clean
