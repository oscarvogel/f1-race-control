#!/usr/bin/env bash
# Sondeo continuo del proveedor: estado + muestra de /api/session
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
LOG="$PROJ/.run/logs/live-timing.log"
for i in $(seq 1 "${1:-12}"); do
  ST=$(curl -s --max-time 6 http://127.0.0.1:3000/api/status 2>/dev/null)
  TS=$(date -u +%H:%M:%S)
  echo "[$TS] $ST"
  LAST=$(echo "$ST" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('lastMessageAt') or '-')" 2>/dev/null || echo '-')
  if [ "$LAST" != "-" ] && [ "$LAST" != "None" ]; then
    echo ">>> RECIBIENDO DATOS <<<"
    echo "--- /api/session ---"
    curl -s --max-time 8 http://127.0.0.1:3000/api/session | head -c 1500
    echo ""
    echo "--- /api/standings (primeras entradas) ---"
    curl -s --max-time 8 http://127.0.0.1:3000/api/standings | head -c 2500
    echo ""
    break
  fi
  sleep 10
done
echo ""
echo "=== LOG ==="
tail -40 "$LOG"
