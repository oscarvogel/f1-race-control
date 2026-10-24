#!/usr/bin/env bash
export PATH="$HOME/.local/bin:$HOME/.local/node/bin:$PATH"
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
cd "$PROJ/backend"

echo "=== crear venv (python 3.12) ==="
uv venv --python 3.12 .venv 2>&1 | tail -3
export VIRTUAL_ENV="$PROJ/backend/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

echo "=== instalar dependencias ==="
uv pip install -r requirements.txt 2>&1 | tail -12

echo "=== versiones ==="
.venv/bin/python --version
.venv/bin/python -c "import django, rest_framework, httpx; print('django', django.get_version()); print('drf', rest_framework.VERSION); print('httpx', httpx.__version__)"

echo "=== npm frontend (en paralelo, se hace aqui) ==="
cd "$PROJ/frontend" 2>/dev/null && npm install 2>&1 | tail -5 || echo "(frontend aun no existe)"
echo "=== VENV DONE ==="
