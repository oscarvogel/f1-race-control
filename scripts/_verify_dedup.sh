#!/usr/bin/env bash
# Reinicia la ingesta y comprueba que el snapshot NO se duplica si el
# contenido no cambia (deduplicacion por huella).
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
export VIRTUAL_ENV="$PROJ/backend/.venv"
export PATH="$VIRTUAL_ENV/bin:$HOME/.local/bin:$PATH"
PIDS="$PROJ/.run/pids"
LOGS="$PROJ/.run/logs"

if [ -f "$PIDS/ingest.pid" ]; then
  pid="$(cat "$PIDS/ingest.pid")"
  kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null
  sleep 2
  kill -KILL -- "-$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null
fi
pkill -f "manage.py ingest_live" 2>/dev/null
sleep 1

cd "$PROJ/backend"
echo "=== limpieza de snapshots duplicados por la huella antigua ==="
./.venv/bin/python manage.py shell -c "
from core.models import SessionSnapshot
n = SessionSnapshot.objects.count()
SessionSnapshot.objects.all().delete()
print('snapshots eliminados:', n)
"

setsid nohup "$PROJ/backend/.venv/bin/python" manage.py ingest_live --interval 3 \
  >> "$LOGS/ingest.log" 2>&1 < /dev/null &
echo $! > "$PIDS/ingest.pid"
echo "ingest reiniciado (pid $(cat "$PIDS/ingest.pid"))"

sleep 12
echo "=== conteo tras 12 s (deberia ser 1, no 4) ==="
./.venv/bin/python manage.py shell -c "
from core.models import SessionSnapshot, IngestionRun, ProviderStatus
print('snapshots:', SessionSnapshot.objects.count())
print('ingestion runs:', IngestionRun.objects.count())
print('provider status:', ProviderStatus.objects.count())
" 2>&1 | tail -5

sleep 20
echo "=== conteo tras 32 s (sigue siendo 1 si no cambian los datos) ==="
./.venv/bin/python manage.py shell -c "
from core.models import SessionSnapshot, IngestionRun, ProviderStatus
print('snapshots:', SessionSnapshot.objects.count())
print('ingestion runs:', IngestionRun.objects.count())
print('provider status:', ProviderStatus.objects.count())
" 2>&1 | tail -5
