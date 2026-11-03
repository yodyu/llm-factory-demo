PYTHON ?= .venv/bin/python
export PYTHONPATH := $(CURDIR)/src
FACTORY_DOCKER_COMMAND ?= docker
export FACTORY_DOCKER_COMMAND

.PHONY: setup test sandbox demo neo4j web
setup:
	python3.12 -m venv .venv
	$(PYTHON) -m pip install -r requirements.txt
	$(PYTHON) -m pip install --no-deps -e .

test:
	$(PYTHON) -m pytest -q

sandbox:
	$(PYTHON) scripts/metrics_bootstrap.py sandbox

demo: sandbox
	FACTORY_KNOWLEDGE_BACKEND=local $(PYTHON) scripts/metrics_bootstrap.py demo

neo4j:
	$(PYTHON) scripts/metrics_bootstrap.py neo4j

web:
	$(PYTHON) -m streamlit run streamlit_app.py --server.address 127.0.0.1
