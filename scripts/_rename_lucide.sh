#!/usr/bin/env bash
# Renombra el import de iconos de lucide-vue-next a @lucide/vue
# (lucide-vue-next esta deprecado en favor de @lucide/vue).
set -euo pipefail
ROOT=/mnt/c/Programacion/proyectos/actives/f1-race-center/frontend/src
count=0
while IFS= read -r file; do
  python3 - "$file" <<'PY'
import io, sys
path = sys.argv[1]
with io.open(path, "r", encoding="utf-8", newline="") as fh:
    src = fh.read()
if "lucide-vue-next" not in src:
    sys.exit(0)
src = src.replace("lucide-vue-next", "@lucide/vue")
with io.open(path, "w", encoding="utf-8", newline="") as fh:
    fh.write(src)
print("actualizado:", path)
PY
  count=$((count + 1))
done < <(grep -rl "lucide-vue-next" "$ROOT" || true)
echo "archivos actualizados: $count"
