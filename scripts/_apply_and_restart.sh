#!/usr/bin/env bash
export PATH="$HOME/.local/node/bin:$PATH"
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
cd "$PROJ"
echo "=== aplicar parche ==="
python3 scripts/patch_livetiming_provider.py
echo "=== validar sintaxis JS ==="
cd "$PROJ/services/live-timing"
node --check src/f1-client.js && echo "f1-client.js OK"
node --check src/server.js && echo "server.js OK"
node --check src/routes/car-data.js && echo "car-data.js OK"
echo "=== reiniciar proveedor ==="
bash "$PROJ/scripts/_restart_live.sh"
