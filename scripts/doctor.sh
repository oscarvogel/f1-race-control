#!/usr/bin/env bash
# Race Center - diagnostico.
#
# Imprime datos concretos (versiones, URLs, sesiones, timestamps, errores),
# no solo "OK".
set -uo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ"
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
export VIRTUAL_ENV="$PROJ/backend/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; BLUE='\033[0;34m'; DIM='\033[2m'; NC='\033[0m'
ok()   { echo -e "${GREEN}OK${NC}      $*"; }
warn() { echo -e "${YELLOW}AVISO${NC}   $*"; }
bad()  { echo -e "${RED}FALLO${NC}   $*"; }
title(){ echo; echo -e "${BLUE}== $* ==${NC}"; }

read_env() {
  local key="$1" default="${2:-}"
  local value
  value="$(grep -E "^${key}=" "$PROJ/.env" 2>/dev/null | head -1 | cut -d= -f2- | sed 's/^ *//;s/ *$//')"
  [ -n "$value" ] && echo "$value" || echo "$default"
}

LIVE_URL="$(read_env F1_LIVETIMING_URL http://127.0.0.1:3000)"
BACKEND_HOST="$(read_env BACKEND_HOST 127.0.0.1)"
BACKEND_PORT="$(read_env BACKEND_PORT 8000)"
FRONTEND_HOST="$(read_env FRONTEND_HOST 127.0.0.1)"
FRONTEND_PORT="$(read_env FRONTEND_PORT 5173)"

# --------------------------------------------------------------------------- #
title "Entorno"
# --------------------------------------------------------------------------- #
echo "  SO:      $(. /etc/os-release && echo "$PRETTY_NAME")"
echo "  Kernel:  $(uname -r)"
echo "  Python:  $(python3 --version 2>&1)"
if [ -x "$PROJ/backend/.venv/bin/python" ]; then
  echo "  Venv:    $("$PROJ/backend/.venv/bin/python" --version 2>&1) en backend/.venv"
else
  warn "No existe backend/.venv (ejecuta ./scripts/setup.sh)"
fi
echo "  Node:    $(node --version 2>&1 || echo 'no instalado')"
echo "  npm:     $(npm --version 2>&1 || echo 'no instalado')"
echo "  uv:      $(uv --version 2>&1 || echo 'no instalado')"
echo "  Proyecto: $PROJ"

# --------------------------------------------------------------------------- #
title "Puertos y procesos"
# --------------------------------------------------------------------------- #
for entry in "live-timing:$LIVE_URL/api/status" "backend:http://$BACKEND_HOST:$BACKEND_PORT/api/health/" "frontend:http://$FRONTEND_HOST:$FRONTEND_PORT/"; do
  name="${entry%%:*}"; url="${entry#*:}"
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$url" 2>/dev/null)"
  if [ "$code" = "200" ]; then ok "$name responde 200 en $url"; else warn "$name -> $url (HTTP $code)"; fi
done
echo
for name in live-timing ingest backend frontend; do
  pidfile="$PROJ/.run/pids/${name}.pid"
  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then ok "$name corre (pid $pid)"; else warn "$name: pid $pid registrado pero muerto"; fi
  else
    echo -e "${DIM}  $name: sin PID registrado${NC}"
  fi
done

# --------------------------------------------------------------------------- #
title "Proveedor live timing (f1-livetiming-api)"
# --------------------------------------------------------------------------- #
if command -v node >/dev/null 2>&1; then
  st="$(curl -s --max-time 8 "$LIVE_URL/api/status" 2>/dev/null)"
  if [ -n "$st" ]; then
    echo "  $st"
    echo "$st" | python3 -c "
import sys, json
from datetime import datetime, timezone
d = json.load(sys.stdin)
print('  conexion SignalR :', d.get('status'))
last = d.get('lastMessageAt')
if last:
    try:
        t = datetime.fromisoformat(str(last).replace('Z', '+00:00'))
        age = (datetime.now(timezone.utc) - t).total_seconds()
        print('  ultimo mensaje   :', last, '(hace %.1f s)' % age)
    except ValueError:
        print('  ultimo mensaje   :', last)
else:
    print('  edad del dato    :', d.get('lastMessageAt'))
print('  uptime (s)       :', d.get('uptimeSeconds'))
" 2>/dev/null
  else
    bad "El proveedor live no responde en $LIVE_URL"
  fi

  echo
  sess="$(curl -s --max-time 8 "$LIVE_URL/api/session" 2>/dev/null)"
  if [ -n "$sess" ]; then
    echo "$sess" | python3 -c "
import sys, json
d = json.load(sys.stdin).get('Session') or {}
m = d.get('Meeting') or {}
print('  Gran Premio :', m.get('Name'))
print('  Circuito    :', (m.get('Circuit') or {}).get('ShortName'), '/', m.get('Location'))
print('  Pais        :', (m.get('Country') or {}).get('Name'))
print('  Round       :', m.get('Number'))
print('  Sesion      :', d.get('Name'), '| tipo:', d.get('Type'))
print('  ID sesion   :', d.get('Key'))
print('  Estado      :', d.get('SessionStatus'))
print('  Inicio local:', d.get('StartDate'), 'GMT', d.get('GmtOffset'))
" 2>/dev/null
  fi

  echo
  echo "  Endpoints comprobados:"
  for ep in status session standings leaderboard tyres weather race-control radio lap-count drivers; do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 6 "$LIVE_URL/api/$ep" 2>/dev/null)"
    size="$(curl -s --max-time 6 "$LIVE_URL/api/$ep" 2>/dev/null | wc -c)"
    if [ "$code" = "200" ]; then
      echo -e "    ${GREEN}200${NC}  /api/$ep  (${size} bytes)"
    else
      echo -e "    ${RED}$code${NC}  /api/$ep"
    fi
  done

  # Comprueba si el servicio escucha fuera de loopback.
  if command -v ss >/dev/null 2>&1; then
    bind="$(ss -ltnp 2>/dev/null | grep ":${LIVE_URL##*:} " | head -1)"
    if echo "$bind" | grep -qE '0\.0\.0\.0|\*:' && ! echo "$bind" | grep -q '127.0.0.1'; then
      bad "El proveedor escucha fuera de loopback: $bind"
    else
      ok "El proveedor escucha solo en loopback"
    fi
  fi
fi

# --------------------------------------------------------------------------- #
title "API Race Center (Django)"
# --------------------------------------------------------------------------- #
health="$(curl -s --max-time 8 "http://$BACKEND_HOST:$BACKEND_PORT/api/health/" 2>/dev/null)"
if [ -n "$health" ]; then
  echo "$health" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('  estado          :', d.get('status'))
print('  modo            :', d.get('mode'))
print('  zona horaria    :', d.get('timezone'))
print('  hay snapshot    :', d.get('has_snapshot'))
print('  estado de datos :', d.get('data_state'))
li = d.get('last_ingestion') or {}
print('  ultima ingesta  :', li.get('started_at'), '| ok:', li.get('ok'), '| entradas:', li.get('entries_count'), '| cambio:', li.get('changed'))
if li.get('error'):
    print('  error ingesta   :', li.get('error'))
for p in d.get('providers') or []:
    print('  proveedor       :', p.get('provider_id'), '->', p.get('state'))
" 2>/dev/null
else
  bad "La API no responde en http://$BACKEND_HOST:$BACKEND_PORT/api/health/"
fi

echo
current="$(curl -s --max-time 8 "http://$BACKEND_HOST:$BACKEND_PORT/api/sessions/current/" 2>/dev/null)"
if [ -n "$current" ]; then
  echo "$current" | python3 -c "
import sys, json
d = json.load(sys.stdin)
if not d.get('found'):
    print('  sin snapshot:', d.get('reason'))
else:
    s = d.get('session') or {}
    print('  sesion         :', s.get('meeting_name'), '/', s.get('session_name'))
    print('  estado datos   :', d.get('data_state'))
    print('  entradas       :', len(d.get('timing') or []))
    print('  pilotos        :', len(d.get('drivers') or []))
    print('  control carrera:', len(d.get('race_control') or []))
    print('  fuentes        :', d.get('sources'))
    print('  generado       :', d.get('generated_at'))
" 2>/dev/null
fi

# --------------------------------------------------------------------------- #
title "Proveedores externos"
# --------------------------------------------------------------------------- #
OPENF1="$(read_env OPENF1_BASE_URL https://api.openf1.org/v1)"
code="$(curl -s -o /tmp/_rc_o1 -w '%{http_code}' --max-time 20 "$OPENF1/sessions?year=2026" 2>/dev/null)"
if [ "$code" = "200" ]; then
  ok "OpenF1 responde 200"
  python3 -c "
import json
try:
    d = json.load(open('/tmp/_rc_o1'))
    austin = [s for s in d if s.get('circuit_short_name') == 'Austin']
    print('  sesiones 2026   :', len(d))
    for s in sorted(austin, key=lambda x: x.get('date_start') or '')[:6]:
        print('    -', s.get('session_key'), s.get('session_type'), s.get('date_start'))
except Exception as e:
    print('  (no se pudo analizar la respuesta:', e, ')')
" 2>/dev/null
elif [ "$code" = "404" ]; then
  warn "OpenF1 responde 404 (sin resultados para ese filtro)"
else
  bad "OpenF1 responde HTTP $code"
fi

JOLPICA="$(read_env JOLPICA_BASE_URL https://api.jolpi.ca/ergast/f1)"
code="$(curl -s -o /tmp/_rc_jo -w '%{http_code}' --max-time 20 "$JOLPICA/current.json" 2>/dev/null)"
if [ "$code" = "200" ]; then
  ok "Jolpica responde 200"
  python3 -c "
import json
try:
    d = json.load(open('/tmp/_rc_jo'))
    mr = d.get('MRData', {})
    print('  temporada actual :', mr.get('series'), mr.get('limit'))
except Exception:
    pass
" 2>/dev/null
else
  bad "Jolpica responde HTTP $code"
fi

# --------------------------------------------------------------------------- #
title "Acceso de red"
# --------------------------------------------------------------------------- #
ip="$(hostname -I 2>/dev/null | awk '{print $1}')"
if [ -n "$ip" ]; then
  echo "  IP de la LAN     : $ip"
  echo "  (acceso desde la LAN: ENABLE_LAN_ACCESS=true en .env + firewall;"
  echo "   nunca abrir puertos del router)"
else
  echo "  IP de la LAN     : no detectada"
fi
pub="$(read_env ENABLE_PUBLIC_ACCESS false)"
if [ "$pub" = "true" ]; then
  bad "ENABLE_PUBLIC_ACCESS=true: la aplicacion esta expuesta a Internet"
else
  ok "ENABLE_PUBLIC_ACCESS=false: la aplicacion no se publica a Internet"
fi
lan="$(read_env ENABLE_LAN_ACCESS false)"
if [ "$lan" = "true" ]; then
  warn "ENABLE_LAN_ACCESS=true: acceso desde la LAN habilitado"
else
  ok "ENABLE_LAN_ACCESS=false: solo localhost"
fi

# --------------------------------------------------------------------------- #
title "Base de datos"
# --------------------------------------------------------------------------- #
if [ -f "$PROJ/backend/db.sqlite3" ]; then
  ok "SQLite en backend/db.sqlite3 ($(du -h "$PROJ/backend/db.sqlite3" | cut -f1))"
  python3 - <<'PY' 2>/dev/null
import os, sqlite3
path = os.path.join(os.environ.get("PROJ", "."), "backend", "db.sqlite3")
try:
    con = sqlite3.connect(path)
    for table in ("core_session", "core_sessionsnapshot", "core_ingestionrun", "core_providerstatus"):
        try:
            n = con.execute("select count(*) from %s" % table).fetchone()[0]
            print("  %-26s %d filas" % (table, n))
        except sqlite3.Error:
            pass
except sqlite3.Error as exc:
    print("  (no se pudo leer:", exc, ")")
PY
else
  warn "No existe backend/db.sqlite3 (ejecuta ./scripts/setup.sh)"
fi

echo
echo "Resumen: ./scripts/doctor.sh  |  Detener: ./scripts/stop-dev.sh"
