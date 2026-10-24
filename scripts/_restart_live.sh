#!/usr/bin/env bash
# Reinicia el proveedor live y comprueba el canal CarData (posiciones).
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
LOGS="$PROJ/.run/logs"
PIDS="$PROJ/.run/pids"

pkill -f "node src/server.js" 2>/dev/null
sleep 2

cd "$PROJ/services/live-timing"
setsid nohup env PORT=3000 HOST=127.0.0.1 node src/server.js \
  >> "$LOGS/live-timing.log" 2>&1 < /dev/null &
echo $! > "$PIDS/live-timing.pid"
echo "proveedor reiniciado (pid $(cat "$PIDS/live-timing.pid"))"

sleep 12
echo "=== status ==="
curl -s --max-time 8 http://127.0.0.1:3000/api/status; echo ""
echo "=== car-data ==="
curl -s --max-time 8 http://127.0.0.1:3000/api/car-data | head -c 1500; echo ""
echo "=== log ==="
tail -12 "$LOGS/live-timing.log"
