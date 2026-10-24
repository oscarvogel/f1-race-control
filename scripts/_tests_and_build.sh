#!/usr/bin/env bash
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
export VIRTUAL_ENV="$PROJ/backend/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

echo "############ PYTEST ############"
cd "$PROJ/backend"
./.venv/bin/python -m pytest 2>&1 | tail -25

echo ""
echo "############ BUILD FRONTEND ############"
cd "$PROJ/frontend"
npm run build 2>&1 | tail -12
