#!/usr/bin/env bash
# Entrypoint de Race Center en el contenedor.
#
# Orden importante:
#   1. Migraciones de Django, con el stack todavia detenido.
#   2. Espera a que el proveedor live se conecte al feed.
#   3. supervisor levanta los cuatro procesos.
#
# La proteccion del sitio no se configura aqui: la aplica nginx con
# `auth_request`, consultando a Django (/api/auth/check/). Si no hay
# credenciales en el entorno, el backend responde 200 siempre y la API queda
# abierta (modo desarrollo).
set -euo pipefail

log() { echo "[entrypoint] $*"; }

: "${DJANGO_DB_PATH:=/data/db.sqlite3}"
export DJANGO_DB_PATH
log "base de datos: ${DJANGO_DB_PATH}"

# --------------------------------------------------------------------------- #
# 1. Migraciones (antes de que arranque ningun proceso)
# --------------------------------------------------------------------------- #
cd /app/backend
log "aplicando migraciones..."
python manage.py migrate --noinput

# --------------------------------------------------------------------------- #
# 2. Todos los procesos
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
