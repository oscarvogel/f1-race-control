#!/usr/bin/env bash
# Arranca el proveedor live-timing en background y sondea /api/status
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
SVC="$PROJ/services/live-timing"
LOG="$PROJ/.run/logs/live-timing.log"
mkdir -p "$PROJ/.run/logs" "$PROJ/.run/pids"

pkill -f "node src/server.js" 2>/dev/null
sleep 1

cd "$SVC"
PORT=3000 HOST=127.0.0.1 nohup node src/server.js > "$LOG" 2>&1 &
echo $! > "$PROJ/.run/pids/live-timing.pid"
echo "PID: $(cat "$PROJ/.run/pids/live-timing.pid")"
echo "LOG: $LOG"

for i in $(seq 1 20); do
  sleep 2
  CODE=$(curl -s -o /tmp/st.json -w "%{http_code}" --max-time 5 http://127.0.0.1:3000/api/status 2>/dev/null)
  if [ "$CODE" = "200" ]; then
    echo "--- /api/status (intento $i) ---"
    cat /tmp/st.json
    echo ""
    break
  fi
  echo "intento $i: http_code=$CODE (servidor arrancando o caido)"
  if ! kill -0 "$(cat "$PROJ/.run/pids/live-timing.pid")" 2>/dev/null; then
    echo "!!! EL PROCESO MURIO !!!"
    break
  fi
done

echo ""
echo "=== LOG (ultimas 60 lineas) ==="
tail -60 "$LOG"
