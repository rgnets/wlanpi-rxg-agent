.PHONY: sync test-unit test lint format test-integration cov-html gen-reqs run preflight

PY ?= python

sync:
	./scripts/sync-remote.sh

test-unit:
	./scripts/test-unit.sh

test:
	./scripts/test.sh

test-integration:
	./scripts/test-integration.sh

lint:
	./scripts/lint.sh

format:
	./scripts/format.sh

cov-html:
	./scripts/test-cov-html.sh

gen-reqs:
	./scripts/generate_requirements.sh

run:
	$(PY) -m wlanpi_rxg_agent

preflight:
	./scripts/format.sh && ./scripts/lint.sh && ./scripts/test-unit.sh
