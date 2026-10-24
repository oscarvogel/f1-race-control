#!/usr/bin/env bash
export PATH="$HOME/.local/bin:$HOME/.local/node/bin:$PATH"
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
cd "$PROJ/backend"
export VIRTUAL_ENV="$PROJ/backend/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

if [ ! -f "$PROJ/.env" ]; then
  cp "$PROJ/.env.example" "$PROJ/.env"
  echo ".env creado desde .env.example"
else
  echo ".env ya existe: no se toca"
fi

echo "=== makemigrations ==="
python manage.py makemigrations core 2>&1 | tail -20
echo "=== migrate ==="
python manage.py migrate 2>&1 | tail -20
echo "=== check ==="
python manage.py check 2>&1 | tail -20
echo "=== ingest una vez ==="
python manage.py ingest_live --once 2>&1 | tail -30
echo "=== estado ==="
python manage.py shell -c "
from core.models import SessionSnapshot, Session, IngestionRun
print('snapshots:', SessionSnapshot.objects.count())
print('sesiones:', list(Session.objects.values_list('provider_id','provider_session_id','name','session_type','state')))
s = SessionSnapshot.objects.order_by('-created_at').first()
if s:
    p = s.payload
    print('data_state:', p.get('data_state'))
    print('sources:', p.get('sources'))
    print('session:', (p.get('session') or {}).get('meeting_name'), (p.get('session') or {}).get('session_name'), (p.get('session') or {}).get('provider_session_id'))
    print('pilotos en timing:', len(p.get('timing') or []))
    print('drivers:', len(p.get('drivers') or []))
    print('race_control:', len(p.get('race_control') or []))
    for ps in p.get('provider_status') or []:
        print('  provider', ps['provider_id'], ps['state'], 'age=', ps.get('data_age_seconds'), 'lat=', ps.get('latency_ms'), 'err=', ps.get('last_error'))
" 2>&1 | tail -40
