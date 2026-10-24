#!/usr/bin/env bash
# Race Center - instalacion (WSL Ubuntu)
#
# Idempotente: se puede volver a ejecutar sin romper nada.
# No sobrescribe un .env existente.
set -euo pipefail

PROJ="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJ"

BLUE='\033[0;34m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "${GREEN}[OK]${NC}   $*"; }
warn() { echo -e "${YELLOW}[AVISO]${NC} $*"; }
die()  { echo -e "${RED}[ERROR]${NC} $*" >&2; exit 1; }
step() { echo; echo -e "${BLUE}== $* ==${NC}"; }

# --------------------------------------------------------------------------- #
step "1. Entorno"
# --------------------------------------------------------------------------- #
[ "$(uname -s)" = "Linux" ] || die "Este script debe ejecutarse dentro de WSL (Linux)."

# uv: gestor de Python/venv sin necesidad de sudo.
export PATH="$HOME/.local/bin:$HOME/.local/node/bin:$PATH"

if ! command -v uv >/dev/null 2>&1; then
  ok "Instalando uv (gestor de Python sin sudo)"
  curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh
  sh /tmp/uv-install.sh >/dev/null
  export PATH="$HOME/.local/bin:$PATH"
fi
ok "uv $(uv --version | awk '{print $2}')"

if ! command -v node >/dev/null 2>&1; then
  ok "Instalando Node.js 22 LTS en ~/.local/node (sin sudo)"
  NODE_VER="$(curl -fsSL https://nodejs.org/dist/index.json \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(next(r['version'] for r in d if r.get('lts') and r['version'].startswith('v22')))")"
  mkdir -p "$HOME/.local/node"
  curl -fsSL "https://nodejs.org/dist/${NODE_VER}/node-${NODE_VER}-linux-x64.tar.xz" -o /tmp/node.tar.xz
  tar -xJf /tmp/node.tar.xz -C "$HOME/.local/node" --strip-components=1
  export PATH="$HOME/.local/node/bin:$PATH"
fi
ok "node $(node --version) / npm $(npm --version)"

# --------------------------------------------------------------------------- #
step "2. Configuracion"
# --------------------------------------------------------------------------- #
if [ -f "$PROJ/.env" ]; then
  warn ".env ya existe: no se toca (usar 'cp .env.example .env' para regenerar)"
else
  cp "$PROJ/.env.example" "$PROJ/.env"
  ok ".env creado desde .env.example"
fi

# --------------------------------------------------------------------------- #
step "3. Backend (entorno virtual + dependencias)"
# --------------------------------------------------------------------------- #
cd "$PROJ/backend"
export VIRTUAL_ENV="$PROJ/backend/.venv"
export PATH="$VIRTUAL_ENV/bin:$PATH"

uv venv --python 3.12 .venv >/dev/null 2>&1 || true
ok "venv con $(.venv/bin/python --version)"
uv pip install -r requirements.txt 2>&1 | tail -2

# --------------------------------------------------------------------------- #
step "4. Base de datos"
# --------------------------------------------------------------------------- #
.venv/bin/python manage.py makemigrations core 2>&1 | tail -3
.venv/bin/python manage.py migrate 2>&1 | tail -3
ok "migraciones aplicadas"

# --------------------------------------------------------------------------- #
step "5. Proveedor live timing (servicio Node local)"
# --------------------------------------------------------------------------- #
cd "$PROJ/services/live-timing"
if [ ! -d node_modules ]; then
  npm install --omit=dev --no-audit --no-fund 2>&1 | tail -2
else
  ok "dependencias del proveedor ya instaladas"
fi

# El proveedor upstream escucha en 0.0.0.0 por defecto. Se aplica el parche
# minimo de seguridad (loopback + CORS restringido) solo si falta.
if ! grep -q 'Race Center patch' src/server.js; then
  warn "Aplicando parche de seguridad al proveedor (loopback + CORS)"
  python3 "$PROJ/scripts/patch_livetiming_provider.py" || \
    warn "No se pudo aplicar el parche: revisar services/live-timing/src/server.js"
else
  ok "Parche de seguridad ya aplicado"
fi

# --------------------------------------------------------------------------- #
step "6. Frontend"
# --------------------------------------------------------------------------- #
cd "$PROJ/frontend"
if [ ! -d node_modules ]; then
  npm install --no-audit --no-fund 2>&1 | tail -3
else
  ok "dependencias del frontend ya instaladas"
fi

# --------------------------------------------------------------------------- #
echo
ok "Instalacion completa."
echo
echo "  Siguiente paso:   ./scripts/start-dev.sh"
echo "  Diagnostico:      ./scripts/doctor.sh"
echo "  Detener:          ./scripts/stop-dev.sh"
