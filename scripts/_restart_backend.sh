#!/usr/bin/env bash
# Reinicia backend + ingesta (para tomar cambios de codigo) y verifica la API.
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
export VIRTUAL_ENV="$PROJ/backend/.venv"
export PATH="$VIRTUAL_ENV/bin:$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
PIDS="$PROJ/.run/pids"
LOGS="$PROJ/.run/logs"

for name in ingest backend; do
  if [ -f "$PIDS/$name.pid" ]; then
    pid="$(cat "$PIDS/$name.pid")"
    kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
  fi
done
sleep 2
pkill -f "manage.py ingest_live" 2>/dev/null
pkill -f "manage.py runserver" 2>/dev/null
sleep 1

cd "$PROJ/backend"
setsid nohup "$PROJ/backend/.venv/bin/python" manage.py ingest_live --interval 3 \
  >> "$LOGS/ingest.log" 2>&1 < /dev/null &
echo $! > "$PIDS/ingest.pid"

setsid nohup "$PROJ/backend/.venv/bin/python" manage.py runserver 127.0.0.1:8000 --noreload \
  >> "$LOGS/backend.log" 2>&1 < /dev/null &
echo $! > "$PIDS/backend.pid"
echo "backend + ingesta reiniciados"

sleep 12
echo "=== health ==="
curl -s --max-time 10 http://127.0.0.1:8000/api/health/ | head -c 700; echo ""
echo ""
echo "=== trazados ==="
curl -s --max-time 10 http://127.0.0.1:8000/api/track/outlines/ | head -c 500; echo ""
echo ""
echo "=== posiciones en el snapshot ==="
curl -s --max-time 10 http://127.0.0.1:8000/api/sessions/current/ | python3 -c "
import sys, json
d = json.load(sys.stdin)
print('posiciones:', len(d.get('positions') or []))
print('track_status:', d.get('track_status'))
print('sources:', d.get('sources'))
print('data_state:', d.get('data_state'))
" 2>&1
echo "=== log de ingesta ==="
tail -6 "$LOGS/ingest.log"
