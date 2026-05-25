.PHONY: lint lint-backend lint-frontend format format-backend format-frontend check

lint: lint-backend lint-frontend

lint-backend:
	cd backend && python3 -m ruff check soundcheck/

lint-frontend:
	cd frontend && npx eslint .
	cd frontend && npx svelte-kit sync && npx svelte-check --tsconfig ./tsconfig.json

format: format-backend format-frontend

format-backend:
	cd backend && python3 -m ruff format soundcheck/

format-frontend:
	cd frontend && npx prettier --write .

format-check: format-check-backend format-check-frontend

format-check-backend:
	cd backend && python3 -m ruff format --check soundcheck/

format-check-frontend:
	cd frontend && npx prettier --check .

check: lint format-check
