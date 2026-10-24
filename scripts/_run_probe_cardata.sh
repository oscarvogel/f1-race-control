#!/usr/bin/env bash
export PATH="$HOME/.local/node/bin:$PATH"
cd /mnt/c/Programacion/proyectos/actives/f1-race-center/services/live-timing
node probe-cardata.js "${1:-90}"
