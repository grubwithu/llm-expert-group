.PHONY: backend-install backend-test backend-dev frontend-dev frontend-build

backend-install:
	python3 -m venv backend/.venv
	backend/.venv/bin/python -m pip install -e 'backend[dev]'

backend-test:
	cd backend && .venv/bin/python -m pytest

backend-dev:
	backend/.venv/bin/python -m uvicorn backend.app.main:app --reload --port 8000

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build
