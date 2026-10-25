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
#
# El `tr -d '\r'` no es cosmetico: si el .env se edita en Windows y queda con
# finales CRLF, el `\r` se cuela en el valor y deja URLs como
# "http://127.0.0.1:3000\r/api/status", que curl no puede pedir.
read_env() {
  local key="$1" default="${2:-}"
  local value
  value="$(grep -E "^${key}=" "$PROJ/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^ *//;s/ *$//')"
  [ -n "$value" ] && echo "$value" || echo "$default"
}

BACKEND_HOST="$(read_env BACKEND_HOST 127.0.0.1)"
BACKEND_PORT="$(read_env BACKEND_PORT 8000)"
FRONTEND_HOST="$(read_env FRONTEND_HOST 127.0.0.1)"
FRONTEND_PORT="$(read_env FRONTEND_PORT 5173)"
LIVE_URL="$(read_env F1_LIVETIMING_URL http://127.0.0.1:3000)"
LIVE_PORT="${LIVE_URL##*:}"
INGEST_INTERVAL="$(read_env INGEST_POLL_SECONDS 3)"

# --------------------------------------------------------------------------- #
# Utilidades de puertos
#
# El PID que se guarda tiene que ser el del proceso que REALMENTE escucha, no
# el de un envoltorio: `npm run dev` deja a vite como proceso hijo, asi que
# el pidfile quedaba con un proceso ya muerto y stop-dev.sh no lo paraba
# nunca. Con esto se resuelve el PID real y se distingue el conflicto con
# otro proyecto (que no se toca) del servicio propio que ya esta corriendo.
# --------------------------------------------------------------------------- #

# PID que escucha en un puerto TCP (vacio si nada escucha).
port_pid() {
  local port="$1"
  ss -ltnp 2>/dev/null | awk -v pat=":$port\$" '
    $4 ~ pat {
      if (match($0, /pid=[0-9]+/)) { print substr($0, RSTART + 4, RLENGTH - 4); exit }
    }'
}

# PID de un proceso de ESTE proyecto que escucha en el puerto (vacio si el
# puerto lo tiene otro proyecto: ese no se adopta ni se toca).
own_port_pid() {
  local port="$1" pid cmd cwd
  pid="$(port_pid "$port")"
  [ -n "$pid" ] || return 0
  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)"
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)"
  case "$cmd" in *"$PROJ"*) echo "$pid"; return 0 ;; esac
  case "$cwd" in "$PROJ"*) echo "$pid"; return 0 ;; esac
}

# Arranca un servicio en segundo plano y registra su PID.
#
#   $1 nombre   $2 directorio de trabajo   $3 puerto   $4.. comando
#
# Devuelve 1 si el servicio no quedo levantado.
start_service() {
  local name="$1" workdir="$2" port="$3"; shift 3
  local pidfile="$PIDS/${name}.pid"

  if [ -f "$pidfile" ] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
    echo -e "${YELLOW}[YA CORRE]${NC} $name (pid $(cat "$pidfile"))"
    return 0
  fi

  # El puerto ya lo sirve un proceso de este proyecto: se reutiliza.
  local owner
  owner="$(own_port_pid "$port")"
  if [ -n "$owner" ]; then
    echo "$owner" > "$pidfile"
    echo -e "${YELLOW}[YA CORRE]${NC} $name (pid $owner) -> puerto $port ya servido por este proyecto"
    return 0
  fi

  # El puerto lo tiene otro proyecto: no se arranca un segundo servicio ni se
  # toca el proceso ajeno.
  local foreign
  foreign="$(port_pid "$port")"
  if [ -n "$foreign" ]; then
    echo -e "${RED}[CONFLICTO]${NC} el puerto $port lo ocupa el pid $foreign (otro proyecto): no se arranca $name"
    return 1
  fi

  cd "$workdir"
  setsid nohup "$@" >> "$LOGS/${name}.log" 2>&1 < /dev/null &
  local pid=$!
  echo "$pid" > "$pidfile"
  echo -e "${GREEN}[ARRANCADO]${NC} $name (pid $pid) -> logs/${name}.log"

  # Si el proceso muere en los primeros segundos (puerto ocupado, error de
  # configuracion), se muestra el error real del log en vez de un PID muerto.
  sleep 2
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pidfile"
    echo -e "${RED}[FALLO]${NC} $name no arranco. Ultimas lineas de logs/${name}.log:"
    tail -n 6 "$LOGS/${name}.log" 2>/dev/null | sed 's/^/        /'
    return 1
  fi
  return 0
}

FAILED=0

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
#
# Se le pasan las credenciales de la cuenta de F1 (si estan en el .env): sin
# ellas el feed no entrega las coordenadas de los autos ni la telemetria.
# --------------------------------------------------------------------------- #
F1_USER="$(read_env F1_USERNAME '')"
F1_PASS="$(read_env F1_PASSWORD '')"

if [ -n "$F1_USER" ] && [ -n "$F1_PASS" ]; then
  echo -e "${GREEN}[CREDENCIALES]${NC} cuenta de F1 configurada: se pediran coordenadas y telemetria"
  start_service "live-timing" "$PROJ/services/live-timing" "$LIVE_PORT" \
    env PORT="$LIVE_PORT" HOST=127.0.0.1 F1_USERNAME="$F1_USER" F1_PASSWORD="$F1_PASS" \
    node src/server.js || FAILED=$((FAILED + 1))
else
  start_service "live-timing" "$PROJ/services/live-timing" "$LIVE_PORT" \
    env PORT="$LIVE_PORT" HOST=127.0.0.1 node src/server.js || FAILED=$((FAILED + 1))
fi

# --------------------------------------------------------------------------- #
# 2. Proceso de ingesta (unico consumidor de los proveedores)
# --------------------------------------------------------------------------- #
start_service "ingest" "$PROJ/backend" 0 \
  "$PROJ/backend/.venv/bin/python" manage.py ingest_live --interval "$INGEST_INTERVAL" || FAILED=$((FAILED + 1))

# --------------------------------------------------------------------------- #
# 3. API Django
# --------------------------------------------------------------------------- #
start_service "backend" "$PROJ/backend" "$BACKEND_PORT" \
  "$PROJ/backend/.venv/bin/python" manage.py runserver "$BACKEND_HOST:$BACKEND_PORT" --noreload || FAILED=$((FAILED + 1))

# --------------------------------------------------------------------------- #
# 4. Frontend Vite
#
# Se invoca vite de forma directa y no con `npm run dev`: npm deja a vite como
# proceso hijo, de modo que el PID registrado era el de npm (que ademas muere
# cuando vite no puede tomar el puerto) y el frontend se escapaba de
# stop-dev.sh. Con node + vite.js el PID registrado es el del servidor real.
# --------------------------------------------------------------------------- #
start_service "frontend" "$PROJ/frontend" "$FRONTEND_PORT" \
  node "$PROJ/frontend/node_modules/vite/bin/vite.js" \
  --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" || FAILED=$((FAILED + 1))

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

if [ "$FAILED" -gt 0 ]; then
  echo
  echo -e "${RED}[FALLO]${NC} $FAILED servicio(s) no arrancaron. Revisa los logs de arriba."
  exit 1
fi
