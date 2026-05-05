.PHONY: help install serve test extract rebuild update

help:
	@echo "Old Recipe Intelligence — developer commands"
	@echo ""
	@echo "  make install    Install Python dependencies into venv"
	@echo "  make serve      Start the API server (http://127.0.0.1:8000)"
	@echo "  make ui         Start the Gradio dev UI (http://127.0.0.1:7861)"
	@echo "  make test       Run the API test suite (requires server running)"
	@echo "  make rebuild    Rebuild FAISS index + crossref + validate"
	@echo "  make extract    Extract substitutions from any new books (append mode)"
	@echo "  make update     Full pipeline: download → extract → rebuild"
	@echo "  make status     Show corpus and extraction status"

install:
	python3 -m venv venv
	venv/bin/pip install --upgrade pip
	venv/bin/pip install -r requirements.txt

serve:
	venv/bin/uvicorn api:app --host 127.0.0.1 --port 8000 --reload

ui:
	venv/bin/python app.py

test:
	venv/bin/python test_api.py

rebuild:
	bash rebuild.sh

extract:
	venv/bin/python extract_substitutions.py --append
	venv/bin/python extract_measurements.py --append

update:
	venv/bin/python update.py

status:
	@echo "Books        : $$(ls books/*.txt 2>/dev/null | wc -l | tr -d ' ')"
	@echo "Substitutions: $$(wc -l < data/substitutions.jsonl 2>/dev/null || echo 0)"
	@[ -f data/measurements.jsonl ] && echo "Measurements : $$(wc -l < data/measurements.jsonl)" || echo "Measurements : (not yet extracted)"
	@[ -f data/terms.jsonl ]        && echo "Terms        : $$(wc -l < data/terms.jsonl)" || echo "Terms        : (not yet extracted)"
	@[ -f data/crossref.json ]      && echo "Crossref     : $$(python3 -c "import json; d=json.load(open('data/crossref.json')); print(len(d), 'ingredients')" 2>/dev/null)" || echo "Crossref     : (not built)"
