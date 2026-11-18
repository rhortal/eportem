# Development checks. `make check` is what CI runs; run it before every push.
PYTHON ?= python3.13
VENV   ?= .venv
BIN     = $(VENV)/bin

.PHONY: venv lint test test-fast check clean-venv

$(BIN)/python: requirements.txt requirements-service.txt requirements-dev.txt
	$(PYTHON) -m venv $(VENV)
	$(BIN)/python -m pip install --quiet --upgrade pip
	$(BIN)/python -m pip install --quiet -r requirements-dev.txt
	touch $(BIN)/python

venv: $(BIN)/python

lint: venv
	$(BIN)/ruff check .

# The engine and (later) the service must stay at 85% or more (docs/refactor/PLAN.md).
CORE_COVERAGE_FLOOR = 85

test: venv
	$(BIN)/python -m pytest --cov --cov-report=term:skip-covered
	$(BIN)/python -m coverage report --include='eportem/*' --fail-under=$(CORE_COVERAGE_FLOOR) > /dev/null \
		|| { echo "eportem/ coverage is below $(CORE_COVERAGE_FLOOR)%:"; \
		     $(BIN)/python -m coverage report --include='eportem/*'; exit 1; }

# Everything except the real-browser tests (tests/browser/, ~35 s).
test-fast: venv
	$(BIN)/python -m pytest --ignore=tests/browser

check: lint test

clean-venv:
	rm -rf $(VENV)
