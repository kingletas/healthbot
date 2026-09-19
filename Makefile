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
lint: collections ## Static checks: the linter, the formatter and the playbook
	@$(UV) run ruff check .
	@$(UV) run ruff format --check .
	@$(UV) run ansible-lint IT/ansible

.PHONY: collections
collections: ## Install the Ansible collections the playbook uses
	@$(UV) run ansible-galaxy collection install -r IT/ansible/requirements.yml >/dev/null

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

# Tracked HCL only: -recursive walks into a developer's own gitignored
# terraform.tfvars, so the gate failed on the formatting of a file that is
# never committed and holds real credentials.
.PHONY: terraform
terraform: ## Format and validate the infrastructure, with no credentials and no state
	@cd $(ROOT_DIR)/IT/terraform && terraform fmt -check $$(git ls-files '*.tf' | sed 's|^IT/terraform/||')
	@cd $(ROOT_DIR)/IT/terraform && terraform init -backend=false -input=false >/dev/null
	@cd $(ROOT_DIR)/IT/terraform && terraform validate
	@$(ROOT_DIR)/IT/terraform/tf-vars-check.sh

# hatchling reads .gitignore, not git's index, so an unanchored pattern can
# drop a tracked module out of the wheel with nothing to say it did. That is
# how healthbot/aws/secrets.py went missing from a build that reported success.
.PHONY: packaging
packaging: ## Refuse a tracked file the wheel build would silently leave out
	@swallowed=$$(git ls-files -i -c --exclude-standard); \
	if [ -n "$$swallowed" ]; then \
		echo "these tracked files match .gitignore and will be missing from the wheel:"; \
		echo "$$swallowed"; exit 1; \
	fi

# terraform-docs owns everything between the markers in IT/terraform/README.md,
# so regenerating is how that table changes and hand-editing it is overwritten.
.PHONY: tf-docs
tf-docs: ## Regenerate the generated table in IT/terraform/README.md
	@terraform-docs markdown table --output-file README.md --output-mode inject $(ROOT_DIR)/IT/terraform

.PHONY: tf-docs-check
tf-docs-check: ## Refuse a generated table that no longer matches the variables
	@terraform-docs markdown table --output-file README.md --output-mode inject --output-check $(ROOT_DIR)/IT/terraform

# Terraform writes every value it manages into state in plaintext, and this
# configuration builds a Secrets Manager secret out of the vendor tokens, so its
# state holds them. .gitignore stops an ordinary add; this stops a forced one.
.PHONY: tfstate
tfstate: ## Refuse a tracked Terraform state file
	@tracked=$$(git ls-files '*.tfstate*'); \
	if [ -n "$$tracked" ]; then \
		echo "terraform state is tracked, and state holds secret values in plaintext:"; \
		echo "$$tracked"; exit 1; \
	fi

# Every tracked file the shebang says is shell, since an extension is not a
# reliable signal and IT/packer/bin holds two scripts that have none.
.PHONY: shell
shell: ## Shellcheck every tracked shell script
	@scripts=$$(git ls-files | while read -r f; do \
		case "$$f" in \
			*.sh) echo "$$f" ;; \
			*) if head -1 "$$f" 2>/dev/null | grep -qaE '^#!.*[ /](ba)?sh'; then echo "$$f"; fi ;; \
		esac; \
	done); \
	if [ -n "$$scripts" ]; then shellcheck -x $$scripts; fi

.PHONY: packer
packer: ## Initialise the AMI template's plugins and validate it against the example vars
	@cd $(ROOT_DIR)/IT/packer && packer fmt -check .
	@cd $(ROOT_DIR)/IT/packer && packer init . >/dev/null
	@cd $(ROOT_DIR)/IT/packer && packer validate -var-file=etc/example.hcl .

# A real plan, which validate cannot approximate: it resolves the six data
# sources the tree reads and propagates computed values. ACTION passes through.
.PHONY: tf-local
tf-local: ## Plan against the local AWS emulator: make tf-local ACTION=plan
	@$(ROOT_DIR)/IT/terraform/tf-local.sh $(or $(ACTION),plan)

.PHONY: check
check: lint shell packaging tfstate test terraform tf-docs-check packer ## Everything a commit has to pass

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
