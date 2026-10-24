# syntax=docker/dockerfile:1
#
# Race Center - imagen de produccion (Coolify / Docker).
#
# Un solo contenedor, cuatro procesos:
#
#   nginx     -> sirve el SPA compilado y hace proxy de /api (unico puerto
#                 expuesto: 80)
#   backend   -> Django con gunicorn en 127.0.0.1:8000
#   ingest    -> manage.py ingest_live (escribe los snapshots)
#   live      -> proveedor Node de cronometraje en 127.0.0.1:3000
#
# El proveedor del feed de F1 y la API **no** se exponen: quedan en loopback
# dentro del contenedor, igual que en la instalacion local. Lo unico que
# sale a la red es el puerto 80 de nginx.
#
# OJO (Coolify): el build pack tiene que ser **Dockerfile**. Con Nixpacks,
# Coolify genera su propio Dockerfile e ignora este archivo, y el contenedor
# se levanta sin el proveedor de cronometraje.

# --------------------------------------------------------------------------- #
# 1. Frontend: compilacion
# --------------------------------------------------------------------------- #
FROM node:22-bookworm-slim AS frontend

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build


# --------------------------------------------------------------------------- #
# 2. Proveedor live: dependencias de Node
# --------------------------------------------------------------------------- #
FROM node:22-bookworm-slim AS live

WORKDIR /app/services/live-timing
COPY services/live-timing/package.json services/live-timing/package-lock.json* ./
RUN npm ci --omit=dev


# --------------------------------------------------------------------------- #
# 3. Runtime: Python + Node + nginx + supervisor
# --------------------------------------------------------------------------- #
FROM python:3.12-slim-bookworm AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    NODE_VERSION=22.23.4

# Node 22 (NodeSource) + nginx + supervisor + utilidades de htpasswd/envsubst.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg nginx supervisor gettext-base apache2-utils \
    && mkdir -p /etc/apt/keyrings \
    && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
        | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
    && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_22.x nodistro main" \
        > /etc/apt/sources.list.d/nodesource.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /etc/nginx/sites-enabled/default

WORKDIR /app

# Dependencias del backend (capa aparte para que el cache de Docker sirva).
COPY backend/requirements.txt /tmp/requirements.txt
RUN pip install -r /tmp/requirements.txt

# Codigo.
COPY backend/ /app/backend/
COPY scripts/ /app/scripts/
COPY deploy/entrypoint.sh /app/entrypoint.sh
COPY deploy/nginx.conf /etc/nginx/nginx.conf
COPY deploy/nginx-site.conf.template /app/deploy/nginx-site.conf.template
COPY deploy/supervisord.conf /etc/supervisor/supervisord.conf
COPY services/live-timing/ /app/services/live-timing/

# node_modules del proveedor live (de la etapa 2).
COPY --from=live /app/services/live-timing/node_modules /app/services/live-timing/node_modules

# Frontend compilado (de la etapa 1).
COPY --from=frontend /build/frontend/dist /app/frontend/dist

RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /data /app/backend/staticfiles /etc/nginx/conf.d \
    && rm -f /etc/nginx/conf.d/default.conf

# El volumen de datos (base SQLite) sobrevive a los redespliegues.
VOLUME ["/data"]

EXPOSE 80

ENTRYPOINT ["/app/entrypoint.sh"]
