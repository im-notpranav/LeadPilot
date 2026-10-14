# LeadPilot - one command: `make dev` (backend + simulator + frontend)

ifeq ($(OS),Windows_NT)
  PY_BOOT ?= py -3
  VENV_PY := backend/.venv/Scripts/python.exe
else
  PY_BOOT ?= python3
  VENV_PY := backend/.venv/bin/python
endif

.PHONY: dev install backend frontend test test-pg e2e perf build seed clean

# scripts/dev.py creates the venv and installs/refreshes dependencies itself, so these work on a fresh clone
# and after pulls that change requirements.txt or package-lock.json.
dev:
	$(PY_BOOT) scripts/dev.py

install:
	$(PY_BOOT) scripts/dev.py --setup

$(VENV_PY):
	$(PY_BOOT) -m venv backend/.venv
	$(VENV_PY) -m pip install -q --upgrade pip
	$(VENV_PY) -m pip install -q -r backend/requirements.txt

frontend/node_modules:
	cd frontend && npm install --no-audit --no-fund

backend: $(VENV_PY)
	cd backend && $(abspath $(VENV_PY)) -m uvicorn app.main:app --reload --port 8000

frontend: frontend/node_modules
	cd frontend && npm run dev

test: $(VENV_PY)
	cd backend && $(abspath $(VENV_PY)) -m pytest -q

test-pg: $(VENV_PY)
	cd backend && LEADPILOT_TEST_POSTGRES=1 $(abspath $(VENV_PY)) -m pytest -q tests/test_postgres.py

e2e: install
	cd frontend && npx playwright install chromium && npm run test:e2e

perf: $(VENV_PY)
	cd backend && $(abspath $(VENV_PY)) scripts/perf.py

build: frontend/node_modules
	cd frontend && npm run build

seed: $(VENV_PY)
	$(VENV_PY) backend/scripts/gen_seed_data.py

clean:
	rm -rf backend/var frontend/dist
