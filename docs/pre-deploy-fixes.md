# mcp-opsmate — Pre-Deployment Fix List

## CRITICAL (App won't run without these)

### Fix 1: Directory Structure — Source code nested one level too deep
**Problem**: All Python source is at `opsmate/opsmate/` but Python expects `opsmate/`
**Impact**: `from opsmate.core...` imports will fail with ModuleNotFoundError
**Fix**: Move all files from `opsmate/opsmate/*` → `opsmate/*`

### Fix 2: Missing __init__.py files
**Problem**: 7 directories are missing package markers
**Impact**: Python won't treat them as importable packages
**Fix**: Create empty `__init__.py` in:
  - `opsmate/__init__.py`
  - `opsmate/api/__init__.py`
  - `opsmate/api/routes/__init__.py`
  - `opsmate/api/middleware/__init__.py`
  - `opsmate/core/__init__.py`
  - `opsmate/infra/__init__.py`
  - `opsmate/services/__init__.py`

### Fix 3: mcp_hub.py in wrong location
**Problem**: `mcp_hub.py` is at `opsmate/infra/mcp_hub.py` (outer) but all other infra files are at `opsmate/opsmate/infra/` (nested)
**Impact**: After Fix 1, the imports in routes will look in `opsmate/infra/mcp_hub.py` but find the OLD file, not the comprehensive one
**Fix**: Ensure the comprehensive mcp_hub.py is at the correct location after restructuring

### Fix 4: Dockerfile CMD path wrong
**Problem**: `CMD ["uvicorn", "opsmate.main:app", ...]` but main.py is at `opsmate/api/main.py`
**Impact**: Uvicorn will crash with "Cannot find opsmate.main"
**Fix**: Change to `CMD ["uvicorn", "opsmate.api.main:app", ...]`

### Fix 5: Docker Compose env vars don't match .env.template
**Problem**: docker-compose uses `GITHUB_TOKEN` and `SLACK_BOT_TOKEN` but .env.template uses `GITHUB_PAT` and `SLACK_WEBHOOK_URL`
**Impact**: Credentials won't be passed to containers even when set
**Fix**: Align env var names between docker-compose.yml and .env.template

### Fix 6: Vite proxy rewrite strips /api prefix incorrectly
**Problem**: `rewrite: (path) => path.replace(/^\/api/, '')` turns `/api/commands` → `/commands`
**Impact**: FastAPI routes are at `/commands`, `/executions` etc. — this would work for dev but nginx adds `/api` prefix in production. Need consistent behavior.
**Fix**: Remove rewrite — proxy should forward `/api/commands` to `http://localhost:8000/api/commands` and add `/api` prefix to all FastAPI routes

### Fix 7: Missing api/routes/__init__.py exports
**Problem**: `main.py` does `from opsmate.api.routes import admin, commands, ...` but no __init__.py exists to expose these
**Impact**: ImportError on startup
**Fix**: Create __init__.py that re-exports all route modules

## VERIFICATION STEPS (After all fixes)
1. `python -c "from opsmate.api.main import create_app; print('OK')"` — imports work
2. `docker compose config` — no YAML errors
3. Check all `__init__.py` files exist
4. Verify Dockerfile CMD path
