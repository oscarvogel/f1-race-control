#!/usr/bin/env bash
# Arranque DETACHED del proveedor: survives al cierre de la sesion WSL.
# systemd esta activo -> usamos systemd-run --user (transient unit) con fallback a setsid.
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
SVC="$PROJ/services/live-timing"
RUN="$PROJ/.run"
mkdir -p "$RUN/logs" "$RUN/pids"

pkill -f "node src/server.js" 2>/dev/null
sleep 1

cd "$SVC"

if command -v systemctl >/dev/null 2>&1 && systemctl --user show-environment >/dev/null 2>&1; then
  systemctl --user stop race-center-livetiming.service 2>/dev/null
  systemd-run --user --unit=race-center-livetiming.service \
    --property=WorkingDirectory="$SVC" \
    --property=Environment=PORT=3000 \
    --property=Environment=HOST=127.0.0.1 \
    --property=StandardOutput=append:"$RUN/logs/live-timing.log" \
    --property=StandardError=append:"$RUN/logs/live-timing.log" \
    /usr/bin/env node src/server.js >/dev/null 2>&1 \
    && echo "modo: systemd-run --user" \
    || echo "modo: systemd-run fallo, uso setsid"
else
  echo "modo: setsid (systemd --user no disponible)"
fi

if ! pgrep -f "node src/server.js" >/dev/null 2>&1; then
  setsid nohup env PORT=3000 HOST=127.0.0.1 node src/server.js \
    >> "$RUN/logs/live-timing.log" 2>&1 < /dev/null &
  echo $! > "$RUN/pids/live-timing.pid"
  echo "modo: setsid pid=$(cat "$RUN/pids/live-timing.pid")"
fi

sleep 6
echo "=== proc ==="
pgrep -af "node src/server.js" || echo "NO CORRE"
echo "=== status ==="
curl -s --max-time 8 http://127.0.0.1:3000/api/status; echo ""
