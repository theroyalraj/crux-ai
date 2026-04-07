.PHONY: setup run test test-tts-voices speak docker-up docker-down \
	stop-server stop-all start-server start-server-terminal start-all start-all-terminal \
	restart-all restart-server restart-all-terminal restart-server-terminal status \
	clean

setup:
	bash scripts/setup.sh

run:
	. .venv/bin/activate && python -m server.main

test:
	. .venv/bin/activate && python -m pytest tests/ -x -q

test-tts-voices:
	bash scripts/test_tts_voices.sh

test-tts-voices-async:
	bash scripts/test_tts_voices.sh --async

speak:
	bash scripts/speak.sh "$(TEXT)" $(or $(P),0)

docker-up:
	docker compose -f docker/docker-compose.yml up -d

docker-down:
	docker compose -f docker/docker-compose.yml down

stop-server:
	bash scripts/crux-service.sh stop-server

stop-all:
	bash scripts/crux-service.sh stop-all

start-server:
	bash scripts/crux-service.sh start-server

start-server-terminal:
	bash scripts/crux-service.sh start-server-terminal

start-all:
	bash scripts/crux-service.sh start-all

start-all-terminal:
	bash scripts/crux-service.sh start-all-terminal

restart-all:
	bash scripts/crux-service.sh restart-all

restart-server:
	bash scripts/crux-service.sh restart-server

restart-all-terminal:
	bash scripts/crux-service.sh restart-all-terminal

restart-server-terminal:
	bash scripts/crux-service.sh restart-server-terminal

status:
	bash scripts/crux-service.sh status

clean:
	bash scripts/clear-locks.sh
