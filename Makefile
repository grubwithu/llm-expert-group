.PHONY: backend-test backend-dev frontend-dev frontend-build

backend-test:
	cd backend && pytest

backend-dev:
	LLM_EXPERT_GROUP_CONFIG=./config.yaml uvicorn backend.app.main:app --reload --port 8000

frontend-dev:
	cd frontend && npm run dev

frontend-build:
	cd frontend && npm run build
