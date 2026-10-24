#!/usr/bin/env bash
# Race Center - arranque de los servicios locales.
#
# Arranca: proveedor live (Node), ingesta (Django), API (Django), frontend (Vite).
# Todo queda en segundo plano, con PID y log por servicio, y sobrevive a la
# salida de este script.
set -uo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ"
RUN="$PROJ/.run"
LOGS="$RUN/logs"
PIDS="$RUN/pids"
mkdir -p "$LOGS" "$PIDS"

export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
export VIRTUAL_ENV="$PROJ/backend/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'

# Lee una variable del .env sin ejecutarlo como codigo.
read_env() {
  local key="$1" default="${2:-}"
  local value
  value="$(grep -E "^${key}=" "$PROJ/.env" 2>/dev/null | head -1 | cut -d= -f2- | sed 's/^ *//;s/ *$//')"
  [ -n "$value" ] && echo "$value" || echo "$default"
}

BACKEND_HOST="$(read_env BACKEND_HOST 127.0.0.1)"
BACKEND_PORT="$(read_env BACKEND_PORT 8000)"
FRONTEND_HOST="$(read_env FRONTEND_HOST 127.0.0.1)"
FRONTEND_PORT="$(read_env FRONTEND_PORT 5173)"
LIVE_URL="$(read_env F1_LIVETIMING_URL http://127.0.0.1:3000)"
LIVE_PORT="${LIVE_URL##*:}"
INGEST_INTERVAL="$(read_env INGEST_POLL_SECONDS 3)"

# Arranca un servicio en segundo plano y registra su PID.
start_service() {
  local name="$1" workdir="$2"; shift 2
  local pidfile="$PIDS/${name}.pid"
  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo -e "${YELLOW}[YA CORRE]${NC} $name (pid $(cat "$pidfile"))"
    return 0
  fi
  cd "$workdir"
  setsid nohup "$@" >> "$LOGS/${name}.log" 2>&1 < /dev/null &
  local pid=$!
  echo "$pid" > "$pidfile"
  echo -e "${GREEN}[ARRANCADO]${NC} $name (pid $pid) -> logs/${name}.log"
}

echo -e "${BLUE}== Race Center - arranque ==${NC}"

# --------------------------------------------------------------------------- #
# 0. Esquema de la base
#
# Las migraciones se aplican ANTES de arrancar los servicios, con el stack
# detenido. Es importante: un proceso que ya esta corriendo con el codigo
# viejo no conoce las columnas nuevas y cada escritura falla con
# "NOT NULL constraint failed" (pasó con el campo `scope` de SessionSnapshot).
# --------------------------------------------------------------------------- #
if [ -x "$PROJ/backend/.venv/bin/python" ]; then
  cd "$PROJ/backend"
  if ! "$PROJ/backend/.venv/bin/python" manage.py migrate --noinput 2>&1 | tail -3; then
    echo -e "${RED}[FALLO]${NC} no se pudieron aplicar las migraciones"
    exit 1
  fi
  cd "$PROJ"
fi

# --------------------------------------------------------------------------- #
# 1. Proveedor live timing
# --------------------------------------------------------------------------- #
if pgrep -f "node src/server.js" >/dev/null 2>&1; then
  echo -e "${YELLOW}[YA CORRE]${NC} live-timing (servicio Node)"
else
  cd "$PROJ/services/live-timing"
  setsid nohup env PORT="$LIVE_PORT" HOST=127.0.0.1 node src/server.js \
    >> "$LOGS/live-timing.log" 2>&1 < /dev/null &
  echo $! > "$PIDS/live-timing.pid"
  echo -e "${GREEN}[ARRANCADO]${NC} live-timing (pid $(cat "$PIDS/live-timing.pid")) -> logs/live-timing.log"
fi

sleep 2

# --------------------------------------------------------------------------- #
# 2. Proceso de ingesta (unico consumidor de los proveedores)
# --------------------------------------------------------------------------- #
start_service "ingest" "$PROJ/backend" \
  "$PROJ/backend/.venv/bin/python" manage.py ingest_live --interval "$INGEST_INTERVAL"

# --------------------------------------------------------------------------- #
# 3. API Django
# --------------------------------------------------------------------------- #
start_service "backend" "$PROJ/backend" \
  "$PROJ/backend/.venv/bin/python" manage.py runserver "$BACKEND_HOST:$BACKEND_PORT" --noreload

# --------------------------------------------------------------------------- #
# 4. Frontend Vite
# --------------------------------------------------------------------------- #
start_service "frontend" "$PROJ/frontend" \
  npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"

# --------------------------------------------------------------------------- #
# 5. Estado inicial
# --------------------------------------------------------------------------- #
sleep 6
echo
echo -e "${BLUE}== Estado ==${NC}"

check_url() {
  local name="$1" url="$2"
  local code
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "$url" 2>/dev/null)"
  if [ "$code" = "200" ]; then
    echo -e "  ${GREEN}OK${NC}    $name  ->  $url"
  else
    echo -e "  ${YELLOW}AVISO${NC} $name  ->  $url  (HTTP $code)"
  fi
}

check_url "Proveedor live" "$LIVE_URL/api/status"
check_url "API Race Center" "http://$BACKEND_HOST:$BACKEND_PORT/api/health/"
check_url "Frontend" "http://$FRONTEND_HOST:$FRONTEND_PORT/"

echo
echo "  Frontend:  http://$FRONTEND_HOST:$FRONTEND_PORT"
echo "  API:       http://$BACKEND_HOST:$BACKEND_PORT/api/"
echo "  Proveedor: $LIVE_URL"
echo
echo "  Logs:      $LOGS"
echo "  PIDs:      $PIDS"
echo
echo "  Diagnostico: ./scripts/doctor.sh"
echo "  Detener:     ./scripts/stop-dev.sh"
