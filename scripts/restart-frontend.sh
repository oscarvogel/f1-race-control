#!/usr/bin/env bash
# Reinicia solo el frontend (util tras cambios en /mnt/c, donde el watcher
# de Vite no dispara eventos del sistema de archivos).
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
PIDS="$PROJ/.run/pids"
LOGS="$PROJ/.run/logs"

if [ -f "$PIDS/frontend.pid" ]; then
  pid="$(cat "$PIDS/frontend.pid")"
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
  sleep 2
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
fi
pkill -f "vite --host 127.0.0.1 --port 5173" 2>/dev/null
sleep 1

cd "$PROJ/frontend"
setsid nohup npm run dev -- --host 127.0.0.1 --port 5173 \
  >> "$LOGS/frontend.log" 2>&1 < /dev/null &
echo $! > "$PIDS/frontend.pid"
echo "frontend reiniciado (pid $(cat "$PIDS/frontend.pid"))"
sleep 7
curl -s -o /dev/null -w "frontend http=%{http_code}\n" --max-time 8 http://127.0.0.1:5173/
