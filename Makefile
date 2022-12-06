#* Variables
SHELL := /usr/bin/env bash
PYTHON := python3
PYTHONPATH := `pwd`

ifneq ($(VERBOSE),)
TESTFLAGS := -s
endif

ifeq ($(TESTTARGET),)
TESTTARGET := tests/
else
endif

#* Poetry
.PHONY: poetry-download
poetry-download:
	curl -sSL https://install.python-poetry.org | $(PYTHON) -

.PHONY: poetry-remove
poetry-remove:
	curl -sSL https://install.python-poetry.org | $(PYTHON) - --uninstall

#* Installation
.PHONY: install
install:
	poetry lock -n && poetry export --without-hashes > requirements.txt
	poetry install -n
	-poetry run mypy --install-types --non-interactive together_worker

.PHONY: install-extras
install-extras:
	poetry lock -n && poetry export --without-hashes > requirements.txt
	poetry install -n --all-extras
	-poetry run mypy --install-types --non-interactive together_worker

.PHONY: pre-commit-install
pre-commit-install:
	poetry run pre-commit install

#* Formatters
.PHONY: codestyle
codestyle:
	poetry run pyupgrade --exit-zero-even-if-changed --py37-plus **/*.py
	poetry run isort --settings-path pyproject.toml together_worker
	poetry run autopep8 --in-place together_worker

.PHONY: formatting
formatting: codestyle

#* Linting
.PHONY: test
test:
	PYTHONPATH=$(PYTHONPATH) poetry run pytest $(TESTFLAGS) -c pyproject.toml --cov-report=html --cov=together --timeout=600 $(TESTTARGET)
	#poetry run coverage-badge -o assets/images/coverage.svg -f

.PHONY: check-codestyle
check-codestyle:
	poetry run isort --diff --check-only --settings-path pyproject.toml together_worker
	poetry run autopep8 --diff together_worker
	poetry run darglint --verbosity 2 together_worker

.PHONY: mypy
mypy:
	poetry run mypy --config-file pyproject.toml together_worker

.PHONY: check-safety
check-safety:
	poetry check
	poetry run safety check --full-report || true
	poetry run bandit -ll --recursive together

.PHONY: lint
lint: test check-codestyle mypy check-safety

.PHONY: update-dev-deps
update-dev-deps:
	poetry add -D bandit@latest darglint@latest "isort[colors]@latest" mypy@latest pre-commit@latest pydocstyle@latest pylint@latest pytest@latest pyupgrade@latest safety@latest coverage@latest coverage-badge@latest pytest-html@latest pytest-cov@latest
	poetry add -D --allow-prereleases autopep8@latest

#* Cleaning
.PHONY: pycache-remove
pycache-remove:
	find . | grep -E "(__pycache__|\.pyc|\.pyo$$)" | xargs rm -rf

.PHONY: dsstore-remove
dsstore-remove:
	find . | grep -E ".DS_Store" | xargs rm -rf

.PHONY: mypycache-remove
mypycache-remove:
	find . | grep -E ".mypy_cache" | xargs rm -rf

.PHONY: ipynbcheckpoints-remove
ipynbcheckpoints-remove:
	find . | grep -E ".ipynb_checkpoints" | xargs rm -rf

.PHONY: pytestcache-remove
pytestcache-remove:
	find . | grep -E ".pytest_cache" | xargs rm -rf

.PHONY: build-remove
build-remove:
	rm -rf build/

.PHONY: cleanup
cleanup: pycache-remove dsstore-remove mypycache-remove ipynbcheckpoints-remove pytestcache-remove

#* Upload to PyPI
clean:
	rm -rf dist

build:
	poetry run python3 -m build

publish-test:
	poetry run python3 -m twine upload --repository testpypi dist/*

publish:
	poetry run python3 -m twine upload dist/*
