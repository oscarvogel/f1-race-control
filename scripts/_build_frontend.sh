#!/usr/bin/env bash
export PATH="$HOME/.local/node/bin:$HOME/.local/bin:$PATH"
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
cd "$PROJ/frontend"
echo "node=$(node --version) npm=$(npm --version)"
npm install --no-audit --no-fund 2>&1 | tail -15
echo "=== BUILD ==="
npm run build 2>&1 | tail -25
echo "=== DIST ==="
ls -la dist 2>/dev/null || echo "sin dist"
