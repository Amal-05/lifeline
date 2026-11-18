.PHONY: demo test lint typecheck build simulate k6-sync
demo:
	docker compose -f infra/docker-compose.yml up -d --build
	python -c "import webbrowser; webbrowser.open('http://localhost:4173/dashboard')"
test:
	python -m pytest
	npm test
lint:
	python -m ruff check .
	npm run lint
typecheck:
	python -m compileall -q services packages
	npm run typecheck
build:
	python -m compileall -q services packages
	npm run build
simulate:
	python -m services.simulator.m4 --scenario $(or $(SCENARIO),all)
k6-sync:
	python -m services.simulator.k6_corpus --events $(or $(EVENTS),60000)
	k6 run infra/k6/sync_ingestion.js
