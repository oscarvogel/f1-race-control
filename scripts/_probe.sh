#!/usr/bin/env bash
echo "=== OS ==="
head -3 /etc/os-release
echo "=== PYTHON ==="
python3 --version 2>&1
command -v python3
python3 -m pip --version 2>&1 | head -1
python3 -c "import venv; print('venv OK')" 2>&1
echo "=== NODE ==="
node --version 2>&1
command -v node
npm --version 2>&1
command -v npm
echo "=== GIT ==="
git --version 2>&1
echo "=== BUILD TOOLS ==="
gcc --version 2>&1 | head -1
make --version 2>&1 | head -1
echo "=== LISTENING PORTS ==="
(ss -ltnp 2>/dev/null || netstat -ltnp 2>/dev/null) | grep -E ':3000|:8000|:5173' || echo "none of 3000/8000/5173 in use"
echo "=== NETWORK: livetiming.formula1.com ==="
getent hosts livetiming.formula1.com || echo "DNS FAIL"
curl -s -o /dev/null -w "http_code=%{http_code} time=%{time_total}\n" --max-time 15 \
  "https://livetiming.formula1.com/signalr/connect?client_id=probe&connectionData=%5B%5D" || echo "curl failed rc=$?"
echo "=== NETWORK: api.openf1.org ==="
curl -s -o /dev/null -w "http_code=%{http_code}\n" --max-time 15 "https://api.openf1.org/v1/meetings?year=2025&limit=1" || echo "curl failed rc=$?"
echo "=== NETWORK: api.jolpi.ca ==="
curl -s -o /dev/null -w "http_code=%{http_code}\n" --max-time 15 "https://api.jolpi.ca/ergast/f1/current.json" || echo "curl failed rc=$?"
echo "=== NPM REGISTRY ==="
npm ping 2>&1 | tail -3
echo "=== DISK ==="
df -h / /mnt/c 2>/dev/null | head -5
echo "=== PROBE DONE ==="
