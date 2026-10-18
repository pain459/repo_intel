# repo_intel — developer convenience targets

SHELL := /bin/bash
COMPOSE   := docker compose
COMPOSE_YAML := compose.yaml

.PHONY: all build up down restart logs doctor migrate test lint clean shell-api shell-worker shell-db

all: up

## -- Infrastructure --
build:
	$(COMPOSE) -f $(COMPOSE_YAML) build

up: build
	$(COMPOSE) -f $(COMPOSE_YAML) up -d

down:
	$(COMPOSE) -f $(COMPOSE_YAML) down

restart: down up

logs:
	$(COMPOSE) -f $(COMPOSE_YAML) logs -f

## -- Shell access --
shell-api:
	$(COMPOSE) -f $(COMPOSE_YAML) exec api bash

shell-worker:
	$(COMPOSE) -f $(COMPOSE_YAML) exec worker bash

shell-db:
	$(COMPOSE) -f $(COMPOSE_YAML) exec postgres bash

## -- DB --
migrate:
	$(COMPOSE) -f $(COMPOSE_YAML) exec api alembic upgrade head

migrate-down:
	$(COMPOSE) -f $(COMPOSE_YAML) exec api alembic downgrade -1

## -- Quality --
doctor:
	$(COMPOSE) -f $(COMPOSE_YAML) exec api repo-intel doctor

test:
	$(COMPOSE) -f $(COMPOSE_YAML) exec api pytest -v --tb=short tests/

lint:
	$(COMPOSE) -f $(COMPOSE_YAML) exec api ruff check src/ tests/

## -- Misc --
clean:
	$(COMPOSE) -f $(COMPOSE_YAML) down -v --remove-orphans
	rm -rf .pytest_cache __pycache__ .ruff_cache .mypy_cache
