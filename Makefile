.PHONY: help install dev test lint fmt run docker-build docker-run clean

help:  ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install:  ## Install runtime dependencies
	pip install -e .

dev:  ## Install dev dependencies (tests + linters + pre-commit)
	pip install -e ".[dev]"
	pre-commit install || true

test:  ## Run pytest
	pytest -q

lint:  ## Run ruff linter
	ruff check .

fmt:  ## Auto-format with ruff
	ruff check --fix .
	ruff format .

run:  ## Run engine on sample_urls.txt
	python sovereign_lead_engine.py sample_urls.txt --export both

docker-build:  ## Build Docker image
	docker build -t sovereign-lead-engine:latest .

docker-run:  ## Run engine in Docker on ./data/urls.txt
	docker compose run --rm engine urls.txt --export both

clean:  ## Remove build artifacts and caches
	rm -rf build dist *.egg-info .pytest_cache .ruff_cache .mypy_cache
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -f leads.db leads.db-wal leads.db-shm pipeline.log
