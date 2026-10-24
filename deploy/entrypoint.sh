#!/usr/bin/env bash
# Entrypoint de Race Center en el contenedor.
#
# Orden importante:
#   1. Proteccion del sitio (htpasswd) y generacion del vhost de nginx.
#   2. Migraciones de Django, con el stack todavia detenido.
#   3. Espera a que el proveedor live se conecte al feed.
#   4. supervisor levanta los cuatro procesos.
set -euo pipefail

log() { echo "[entrypoint] $*"; }

: "${DJANGO_DB_PATH:=/data/db.sqlite3}"
export DJANGO_DB_PATH
log "base de datos: ${DJANGO_DB_PATH}"

# --------------------------------------------------------------------------- #
# 1. Proteccion con usuario (opcional)
# --------------------------------------------------------------------------- #
if [ -n "${RACE_CENTER_USER:-}" ] && [ -n "${RACE_CENTER_PASSWORD:-}" ]; then
    # La contraseña va por stdin (-i): asi no queda en la lista de procesos.
    printf '%s\n' "$RACE_CENTER_PASSWORD" \
        | htpasswd -B -c -i /etc/nginx/.htpasswd "$RACE_CENTER_USER"
    export RACE_CENTER_AUTH='auth_basic "Race Center"; auth_basic_user_file /etc/nginx/.htpasswd;'
    log "acceso protegido con usuario"
else
    export RACE_CENTER_AUTH=''
    log "sin proteccion con usuario (RACE_CENTER_USER/PASSWORD vacios)"
fi

envsubst '${RACE_CENTER_AUTH}' < /app/deploy/nginx-site.conf.template \
    > /etc/nginx/conf.d/site.conf

# --------------------------------------------------------------------------- #
# 2. Migraciones (antes de que arranque ningun proceso)
# --------------------------------------------------------------------------- #
cd /app/backend
log "aplicando migraciones..."
python manage.py migrate --noinput

# --------------------------------------------------------------------------- #
# 3. Todos los procesos
#
# El proveedor live y la ingesta los arranca supervisor. NO se espera aqui a
# que el proveedor conecte con el feed de la F1: el proveedor todavia no
# existe cuando corre este script, asi que esperarlo seria esperar en el
# vazio (40 s perdidos en cada arranque).
#
# La ingesta ya sabe esperar: mientras el proveedor no responde, el estado
# que publica es WAITING, no un error. En cuanto el proveedor conecta, el
# snapshot empieza a llegar solo.
# --------------------------------------------------------------------------- #
log "arrancando supervisor"
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
