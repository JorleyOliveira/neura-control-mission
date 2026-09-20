PYTHON ?= python3

.PHONY: setup test index dev bootstrap-agents clean docker-up docker-test runtime-smoke

setup:
	$(PYTHON) -m venv .venv
	. .venv/bin/activate && pip install --upgrade pip && pip install -e '.[dev]'

bootstrap-agents:
	bash scripts/bootstrap_agents.sh

index:
	. .venv/bin/activate && PYTHONPATH=. python scripts/index_agents.py

test:
	. .venv/bin/activate && pytest -q

dev:
	. .venv/bin/activate && python scripts/dev.py

docker-up:
	docker compose up -d --build

docker-test:
	docker compose ps
	curl -fsS http://127.0.0.1:8000/health
	curl -fsS http://127.0.0.1:8001/health
	curl -fsS http://127.0.0.1:8002/health

runtime-smoke:
	docker compose exec marcelo python scripts/test_runtime.py

clean:
	rm -f neura.db neura.db-shm neura.db-wal
