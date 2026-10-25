#!/usr/bin/env bash
# Race Center - detencion de los servicios.
#
# Solo detiene los procesos que Race Center inicio (segun los PID registrados
# en .run/pids) o los que belonguecen a este proyecto. No toca ningun otro
# proceso del sistema.
set -uo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PIDS="$PROJ/.run/pids"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'

stopped=0

for name in frontend backend ingest live-timing; do
  pidfile="$PIDS/${name}.pid"
  if [ ! -f "$pidfile" ]; then
    echo -e "${YELLOW}[NADA]${NC} $name (sin PID registrado)"
    continue
  fi
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    # Se mata el grupo de procesos para arrastrar los hijos (npm -> vite).
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
    sleep 1
    if kill -0 "$pid" 2>/dev/null; then
      kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
    fi
    echo -e "${GREEN}[DETENIDO]${NC} $name (pid $pid)"
    stopped=$((stopped + 1))
  else
    echo -e "${YELLOW}[YA ESTABA]${NC} $name (pid $pid no existe)"
  fi
  rm -f "$pidfile"
done

# --------------------------------------------------------------------------- #
# Procesos residuales
#
# Un servicio puede quedarse escuchando sin PID valido (por ejemplo, un vite
# de una corrida anterior o el proveedor, cuyo cmdline es relativo y por eso
# no lo cubre el pkill por ruta). Se localizan por puerto y SOLO se detienen
# si pertenecen a este proyecto: un puerto tomado por otro proyecto no se
# toca.
# --------------------------------------------------------------------------- #

port_pid() {
  local port="$1"
  ss -ltnp 2>/dev/null | awk -v pat=":$port\$" '
    $4 ~ pat {
      if (match($0, /pid=[0-9]+/)) { print substr($0, RSTART + 4, RLENGTH - 4); exit }
    }'
}

# Detiene el proceso de este proyecto que escucha en el puerto.
stop_port_owner() {
  local name="$1" port="$2" pid cmd cwd
  pid="$(port_pid "$port")"
  [ -n "$pid" ] || return 0

  cmd="$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null)"
  cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null)"
  case "$cmd" in
    *"$PROJ"*) ;;
    *) case "$cwd" in "$PROJ"*) ;; *) return 0 ;; esac ;;
  esac

  kill -TERM "$pid" 2>/dev/null
  sleep 1
  if kill -0 "$pid" 2>/dev/null; then
    kill -KILL "$pid" 2>/dev/null
  fi
  echo -e "${GREEN}[DETENIDO]${NC} $name (proceso residual en el puerto $port, pid $pid)"
  stopped=$((stopped + 1))
}

LIVE_PORT="$(grep -E '^F1_LIVETIMING_URL=' "$PROJ/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' | sed 's#.*:##;s#/.*##')"
LIVE_PORT="${LIVE_PORT:-3000}"
BACKEND_PORT="$(grep -E '^BACKEND_PORT=' "$PROJ/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^ *//;s/ *$//')"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="$(grep -E '^FRONTEND_PORT=' "$PROJ/.env" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '\r' | sed 's/^ *//;s/ *$//')"
FRONTEND_PORT="${FRONTEND_PORT:-5174}"

stop_port_owner "live-timing" "$LIVE_PORT"
stop_port_owner "backend" "$BACKEND_PORT"
stop_port_owner "frontend" "$FRONTEND_PORT"

# Limpia restos del proveedor live (por nombre de proceso, dentro del proyecto).
pkill -f "$PROJ/services/live-timing/src/server.js" 2>/dev/null && \
  echo -e "${GREEN}[DETENIDO]${NC} live-timing (proceso residual)"

echo
echo "Servicios detenidos: $stopped"
