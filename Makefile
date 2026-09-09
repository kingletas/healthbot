SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

ROOT_DIR := $(shell dirname $(realpath $(firstword $(MAKEFILE_LIST))))
UV ?= uv
COMPOSE ?= docker compose -f $(ROOT_DIR)/IT/local/docker-compose.yml

.PHONY: help
help: ## Show this help
	@grep -hE '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

# --- the environment ---

.PHONY: install
install: ## Build the virtualenv from uv.lock and fetch the browser the checkout check drives
	@$(UV) sync
	@$(UV) run playwright install --with-deps chromium

.PHONY: sync
sync: ## Build the virtualenv from uv.lock, without the browser
	@$(UV) sync

# --- the gate ---

.PHONY: lint
lint: ## Static checks: the linter, the formatter and the playbook
	@$(UV) run ruff check .
	@$(UV) run ruff format --check .
	@$(UV) run ansible-lint IT/ansible

.PHONY: format
format: ## Apply the formatter
	@$(UV) run ruff format .
	@$(UV) run ruff check --fix .

.PHONY: test
test: ## The unit suite. Integration is a separate target because it needs the stack
	@$(UV) run pytest -q

.PHONY: integration
integration: ## The nine tests that drive the IT/local stack. Needs `make up` and `make seed`
	@$(UV) run pytest -q -m integration

.PHONY: terraform
terraform: ## Format and validate the infrastructure, with no credentials and no state
	@cd $(ROOT_DIR)/IT/terraform && terraform fmt -check -recursive
	@cd $(ROOT_DIR)/IT/terraform && terraform init -backend=false -input=false >/dev/null
	@cd $(ROOT_DIR)/IT/terraform && terraform validate

.PHONY: check
check: lint test terraform ## Everything a commit has to pass

# --- the local environment ---

.PHONY: up
up: ## Start the local stack: stub storefront, Mattermost, observability
	@$(COMPOSE) up -d --build

.PHONY: down
down: ## Stop the local stack
	@$(COMPOSE) down

.PHONY: seed
seed: ## Seed the local AWS emulator with parameters, secrets, an instance and a topic
	@$(UV) run healthbot-local seed

.PHONY: run-env
run-env: ## Print the fully-wired command that runs the bot against the local stack
	@$(UV) run healthbot-local run-env

.PHONY: demo
demo: ## Drive the whole telemetry pipeline with synthetic runs through the real code path
	@$(UV) run healthbot-demo

# --- shipping ---

.PHONY: build
build: ## Build the deployable wheel into dist/
	@$(UV) build

.PHONY: deploy
deploy: build ## Install the newest wheel onto the inventory hosts
	@cd $(ROOT_DIR)/IT/ansible && $(UV) run ansible-playbook -i inventory playbook.yml

.PHONY: notes
notes: ## Print a version's release notes: make notes VERSION=0.2.0
	@test -n "$(VERSION)" || { echo "VERSION= is required, e.g. make notes VERSION=0.2.0"; exit 2; }
	@$(ROOT_DIR)/packaging/release-notes.sh "$(VERSION)"

.PHONY: clean
clean: ## Remove caches and build products; the virtualenv stays
	@rm -rf dist .pytest_cache .ruff_cache .coverage
	@find . -name __pycache__ -type d -not -path "./.venv/*" -exec rm -rf {} + 2>/dev/null || true
	@echo "cleaned"
