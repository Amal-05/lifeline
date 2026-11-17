.PHONY: demo test lint typecheck build
demo:
	docker compose -f infra/docker-compose.yml up --build
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
