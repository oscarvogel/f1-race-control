#!/usr/bin/env bash
# Race Center — bootstrap del toolchain en WSL (sin sudo, todo en $HOME)
set -u
export DEBIAN_FRONTEND=noninteractive
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center

echo "############ 1. uv (gestor de python/venv sin sudo) ############"
if ! command -v uv >/dev/null 2>&1 && [ ! -x "$HOME/.local/bin/uv" ]; then
  curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh 2>&1 | tail -2
  sh /tmp/uv-install.sh 2>&1 | tail -5
fi
export PATH="$HOME/.local/bin:$PATH"
uv --version 2>&1 || { echo "FALLO uv"; exit 1; }

echo "############ 2. Python 3.12 (standalone, sin sudo) ############"
uv python install 3.12 2>&1 | tail -3
uv python list 2>&1 | head -8

echo "############ 3. Node 22 LTS (tarball oficial, sin sudo) ############"
if [ ! -x "$HOME/.local/node/bin/node" ]; then
  NODE_VER=$(curl -fsSL https://nodejs.org/dist/index.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(next(r['version'] for r in d if r.get('lts') and r['version'].startswith('v22')))")
  echo "Node objetivo: $NODE_VER"
  mkdir -p "$HOME/.local"
  curl -fsSL "https://nodejs.org/dist/${NODE_VER}/node-${NODE_VER}-linux-x64.tar.xz" -o /tmp/node.tar.xz \
    || curl -fsSL "https://nodejs.org/dist/${NODE_VER}/node-${NODE_VER}-linux-x64.tar.gz" -o /tmp/node.tar.gz
  rm -rf "$HOME/.local/node"
  mkdir -p "$HOME/.local/node"
  if [ -f /tmp/node.tar.xz ]; then tar -xJf /tmp/node.tar.xz -C "$HOME/.local/node" --strip-components=1;
  else tar -xzf /tmp/node.tar.gz -C "$HOME/.local/node" --strip-components=1; fi
fi
export PATH="$HOME/.local/node/bin:$PATH"
node --version
npm --version

echo "############ 4. Persistir PATH en ~/.bashrc ############"
touch "$HOME/.bashrc"
grep -q 'race-center-toolchain' "$HOME/.bashrc" || cat >> "$HOME/.bashrc" <<'EOF'

# race-center-toolchain
export PATH="$HOME/.local/bin:$HOME/.local/node/bin:$PATH"
EOF
echo "PATH persistido"

echo "############ 5. Clone del proveedor f1-livetiming-api ############"
mkdir -p "$PROJ/services"
if [ ! -d "$PROJ/services/live-timing/.git" ]; then
  rm -rf "$PROJ/services/live-timing"
  git clone --depth 1 https://github.com/julesr0y/f1-livetiming-api.git "$PROJ/services/live-timing" 2>&1 | tail -3
fi
cd "$PROJ/services/live-timing"
echo "--- archivos ---"
ls -la
echo "--- package.json ---"
cat package.json
echo "--- licencia/notice ---"
ls | grep -iE 'licen|notice|copy' || echo "(sin LICENSE/NOTICE en raiz)"
for f in LICENSE NOTICE LICENSE.md NOTICE.md; do
  [ -f "$f" ] && { echo "===== $f ====="; head -40 "$f"; }
done

echo "############ 6. npm install del proveedor ############"
cd "$PROJ/services/live-timing"
npm install --omit=dev --no-audit --no-fund 2>&1 | tail -8

echo "############ BOOTSTRAP DONE ############"
