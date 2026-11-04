.PHONY: install dev-api dev-web build demo test benchmark lint

install:            ## Python + Node dependencies
	pip install -r requirements-dev.txt
	cd frontend && npm install

dev-api:            ## API on :8000 (OCI_LLM_MODE=bedrock by default)
	cd python_api && uvicorn app.main:app --reload --port 8000

dev-web:            ## Vite dev server on :5173, proxies /api to :8000
	cd frontend && npm run dev

build:              ## Build the SPA into frontend/dist (served by the API)
	cd frontend && npm run build

demo: build         ## One process, offline mock narrative, http://localhost:8000
	cd python_api && OCI_LLM_MODE=mock uvicorn app.main:app --port 8000

benchmark:
	cd python_api && python3 verify_benchmark.py

test: benchmark
	python3 -m pytest -q tests

lint:
	cfn-lint infra/*.yaml
