# Discord Radio Bot — common actions.
#
#   make update              create the venv (if needed) and install dependencies
#   make run                 run the bot (default browser: chrome)
#   make run BROWSER=firefox run the bot reading cookies from Firefox
#   make run BROWSER=none    run the bot without browser cookies

VENV   := .venv
PYTHON := $(VENV)/bin/python
PIP    := $(VENV)/bin/pip

# Optional: forwarded to bot.py as --cookies-from-browser when set.
BROWSER ?=
BROWSER_ARG := $(if $(BROWSER),--cookies-from-browser $(BROWSER),)

.PHONY: help update run

help:
	@echo "Targets:"
	@echo "  update              create venv (if needed) and install dependencies"
	@echo "  run                 run the bot (default browser: chrome)"
	@echo "  run BROWSER=firefox run the bot reading cookies from a given browser"
	@echo "  run BROWSER=none    run the bot without browser cookies"

update:
	@test -d $(VENV) || python3 -m venv $(VENV)
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt

run:
	$(PYTHON) bot.py $(BROWSER_ARG)
