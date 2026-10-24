#!/usr/bin/env bash
# Grabador de evidencia LIVE: sondea el proveedor y registra cambios reales.
# Sirve como prueba objetiva de "llegaron mensajes nuevos de la clasificacion".
export PATH="$HOME/.local/node/bin:$PATH"
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
OUT="$PROJ/.run/logs/live-evidence.log"
INTERVAL="${1:-5}"
mkdir -p "$PROJ/.run/logs"

PREV=""
echo "# Evidencia LIVE - $(date -u +%Y-%m-%dT%H:%M:%SZ) - intervalo ${INTERVAL}s" > "$OUT"

while true; do
  NOW=$(date -u +%Y-%m-%dT%H:%M:%SZ)
  ST=$(curl -s --max-time 8 http://127.0.0.1:3000/api/status 2>/dev/null)
  SESS=$(curl -s --max-time 8 http://127.0.0.1:3000/api/session 2>/dev/null)
  STAND=$(curl -s --max-time 8 http://127.0.0.1:3000/api/standings 2>/dev/null)

  LASTMSG=$(printf '%s' "$ST" | python3 -c "import sys,json;print(json.load(sys.stdin).get('lastMessageAt'))" 2>/dev/null || echo None)
  STYPE=$(printf '%s' "$SESS" | python3 -c "
import sys,json
try:
    s=json.load(sys.stdin).get('Session') or {}
    m=s.get('Meeting') or {}
    print('%s|%s|%s|%s|%s' % (m.get('Name'), m.get('Location'), s.get('Type'), s.get('Key'), s.get('SessionStatus')))
except Exception: print('ERROR|ERROR|ERROR|ERROR|ERROR')
" 2>/dev/null || echo "ERROR|ERROR|ERROR|ERROR|ERROR")

  # Huella de la clasificacion: tiempo del lider + mejor vuelta del lider
  FPRINT=$(printf '%s' "$STAND" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    lb=d.get('Leaderboard') or []
    lines=d.get('Lines') or {}
    lead=lb[0] if lb else None
    l=lines.get(lead) or {}
    bl=(l.get('BestLapTime') or {}).get('Value')
    print('%s|%s|%s' % (lead, bl, len(lb)))
except Exception: print('none')
" 2>/dev/null || echo none)

  if [ "$FPRINT" != "$PREV" ]; then
    echo "[$NOW] lastMessageAt=$LASTMSG | sesion=$STYPE | lider=$FPRINT | *** CAMBIO DETECTADO ***" >> "$OUT"
    PREV="$FPRINT"
  else
    echo "[$NOW] lastMessageAt=$LASTMSG | sesion=$STYPE | lider=$FPRINT | (sin cambio)" >> "$OUT"
  fi
  sleep "$INTERVAL"
done
