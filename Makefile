.PHONY: install backend-dev frontend-dev lint format test start-all

# Installation
install:
	pip install -r backend/requirements.txt
	pip install ruff mypy pytest pytest-asyncio httpx
	cd frontend && npm install

# Development
backend-dev:
	cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

frontend-dev:
	cd frontend && npm run dev

# Professionalism: Linting & Formatting
lint:
	python -m ruff check backend scripts
	cd frontend && npm run lint

format:
	python -m ruff format backend scripts
	python -m ruff check --fix backend scripts

# Verification: Testing
test:
	python -m pytest backend/tests tests/

# Orchestration: Start Everything (using start_reliable.py logic)
start-all:
	python start_reliable.py
