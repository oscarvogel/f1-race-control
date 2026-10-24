#!/usr/bin/env bash
export PATH="$HOME/.local/node/bin:$PATH"
echo "=== PID 1 ==="
ps -p 1 -o comm= 2>&1
echo "=== systemd? ==="
[ -d /run/systemd/system ] && echo "systemd ACTIVO" || echo "systemd NO activo"
echo "=== negotiate OPTIONS (como lo hace f1-client) ==="
curl -s -o /tmp/neg.json -w "http_code=%{http_code} time=%{time_total}\n" --max-time 20 \
  -X OPTIONS 'https://livetiming.formula1.com/signalrcore/negotiate' \
  -H 'User-Agent: BestHTTP' -H 'Origin: https://www.formula1.com' 2>&1
echo "--- body/headers ---"
curl -s -i --max-time 20 -X OPTIONS 'https://livetiming.formula1.com/signalrcore/negotiate' \
  -H 'User-Agent: BestHTTP' -H 'Origin: https://www.formula1.com' 2>&1 | head -25
echo ""
echo "=== negotiate POST ==="
curl -s -i --max-time 20 -X POST \
  'https://livetiming.formula1.com/signalrcore/negotiate?negotiateVersion=1' \
  -H 'User-Agent: BestHTTP' -H 'Origin: https://www.formula1.com' \
  -H 'Content-Type: text/plain' 2>&1 | head -25
