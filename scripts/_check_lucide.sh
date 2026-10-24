#!/usr/bin/env bash
export PATH="$HOME/.local/node/bin:$PATH"
cd /mnt/c/Programacion/proyectos/actives/f1-race-center/frontend
echo "--- @lucide/vue ---"
npm view @lucide/vue version 2>&1 | head -3
echo "--- peer deps ---"
npm view @lucide/vue peerDependencies 2>&1 | head -6
echo "--- lucide-vue-next ---"
npm view lucide-vue-next version 2>&1 | head -3
