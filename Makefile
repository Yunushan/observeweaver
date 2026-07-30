PYTHON ?= python3
CONFIG ?= config/examples/standalone.yml
OUTPUT ?= build

.PHONY: help bootstrap validate render test lint check secrets clean

help:
	@$(PYTHON) -m observeweaver.cli --help

bootstrap:
	$(PYTHON) -m venv .venv
	.venv/bin/python -m pip install --upgrade pip
	.venv/bin/python -m pip install -r requirements-dev.txt

validate:
	PYTHONPATH=src $(PYTHON) -m observeweaver.cli validate --config $(CONFIG)

render:
	PYTHONPATH=src $(PYTHON) -m observeweaver.cli render --config $(CONFIG) --output $(OUTPUT)

test:
	PYTHONPATH=src $(PYTHON) -m unittest discover -s tests -v

lint:
	PYTHONPATH=src $(PYTHON) -m compileall -q src tests
	find scripts deployments -type f -name '*.sh' -exec bash -n {} +

check: lint test validate

secrets:
	PYTHONPATH=src $(PYTHON) -m observeweaver.cli secrets --output secrets/observeweaver.env

clean:
	$(PYTHON) -c "from pathlib import Path; import shutil; [shutil.rmtree(p, ignore_errors=True) for p in (Path('build'), Path('.pytest_cache'), Path('.ruff_cache'))]"
