#!/usr/bin/env bash
# Race Center - bateria de pruebas.
#
#   ./scripts/test.sh          -> backend + frontend + smoke test
#   ./scripts/test.sh backend  -> solo backend
#   ./scripts/test.sh frontend -> solo frontend
set -uo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ"
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
export VIRTUAL_ENV="$PROJ/backend/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

GREEN='\033[0;32m'; RED='\033[0;31m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'
target="${1:-all}"
failures=0

banner() { echo; echo -e "${BLUE}== $* ==${NC}"; }

# --------------------------------------------------------------------------- #
if [ "$target" = "all" ] || [ "$target" = "backend" ]; then
  banner "Pruebas del backend (pytest)"
  cd "$PROJ/backend"
  if "$PROJ/backend/.venv/bin/python" -m pytest 2>&1 | tail -40; then
    echo -e "${GREEN}[OK]${NC} backend"
  else
    echo -e "${RED}[FALLO]${NC} backend"
    failures=$((failures + 1))
  fi
fi

# --------------------------------------------------------------------------- #
if [ "$target" = "all" ] || [ "$target" = "frontend" ]; then
  banner "Compilacion del frontend (vite build)"
  cd "$PROJ/frontend"
  if npm run build 2>&1 | tail -20; then
    if [ -f "$PROJ/frontend/dist/index.html" ]; then
      echo -e "${GREEN}[OK]${NC} frontend compilado -> frontend/dist"
    else
      echo -e "${RED}[FALLO]${NC} frontend: no se genero dist/index.html"
      failures=$((failures + 1))
    fi
  else
    echo -e "${RED}[FALLO]${NC} frontend"
    failures=$((failures + 1))
  fi
fi

# --------------------------------------------------------------------------- #
if [ "$target" = "all" ] || [ "$target" = "smoke" ]; then
  banner "Smoke test sobre la API real"
  cd "$PROJ/backend"
  "$PROJ/backend/.venv/bin/python" - <<'PY'
import os, sys, json, urllib.request

BASE = "http://127.0.0.1:8000/api"
failures = []


def get(path):
    try:
        with urllib.request.urlopen(BASE + path, timeout=10) as resp:
            return resp.status, json.load(resp)
    except Exception as exc:
        return None, str(exc)


status, health = get("/health/")
if status == 200:
    print("  OK  /api/health/  estado=%s  datos=%s" % (health.get("status"), health.get("data_state")))
else:
    failures.append("/api/health/ no responde (servidor Django arrancado?)")

status, current = get("/sessions/current/")
if status == 200 and current.get("found"):
    timing = current.get("timing") or []
    session = current.get("session") or {}
    print("  OK  /api/sessions/current/  estado=%s  GP=%s  sesion=%s  pilotos=%d"
          % (current.get("data_state"), session.get("meeting_name"),
             session.get("session_name"), len(timing)))
    if not timing:
        failures.append("el snapshot no tiene filas de clasificacion")
    sources = current.get("sources") or {}
    if not any(sources.values()):
        failures.append("el snapshot no declara la fuente de los datos")
else:
    failures.append("/api/sessions/current/ sin snapshot: %s" % current)

status, providers = get("/providers/status/")
if status == 200:
    for p in providers.get("providers") or []:
        print("  OK  proveedor %-16s estado=%-12s latencia=%sms"
              % (p.get("provider_id"), p.get("state"), p.get("latency_ms")))
else:
    failures.append("/api/providers/status/ no responde")

# El proveedor live directo (no nuestra API) tambien debe estar vivo.
try:
    with urllib.request.urlopen("http://127.0.0.1:3000/api/status", timeout=8) as resp:
        st = json.load(resp)
    print("  OK  proveedor live directo: %s (ultimo mensaje %s)"
          % (st.get("status"), st.get("lastMessageAt")))
    if not st.get("isConnected"):
        failures.append("el proveedor live no esta conectado al feed")
except Exception as exc:
    failures.append("el proveedor live local no responde: %s" % exc)

print()
if failures:
    print("SMOKE TEST: %d fallo(s)" % len(failures))
    for f in failures:
        print("  - %s" % f)
    sys.exit(1)
print("SMOKE TEST: todo correcto")
PY
  if [ $? -eq 0 ]; then
    echo -e "${GREEN}[OK]${NC} smoke test"
  else
    echo -e "${YELLOW}[AVISO]${NC} smoke test: la API puede no estar arrancada (./scripts/start-dev.sh)"
    failures=$((failures + 1))
  fi
fi

# --------------------------------------------------------------------------- #
echo
if [ "$failures" -eq 0 ]; then
  echo -e "${GREEN}TODO CORRECTO${NC}"
  exit 0
fi
echo -e "${RED}FALLOS: $failures${NC}"
exit 1
