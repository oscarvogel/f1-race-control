#!/usr/bin/env bash
# Race Center - detencion de los servicios.
#
# Solo detiene los procesos que Race Center inicio (segun los PID registrados
# en .run/pids). No toca ningun otro proceso del sistema.
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

# Limpia restos del proveedor live (por nombre de proceso, dentro del proyecto).
pkill -f "$PROJ/services/live-timing/src/server.js" 2>/dev/null && \
  echo -e "${GREEN}[DETENIDO]${NC} live-timing (proceso residual)"

echo
echo "Servicios detenidos: $stopped"
