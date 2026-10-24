#!/usr/bin/env bash
echo "=== SUDO ==="
sudo -n true 2>&1 && echo "SUDO PASSWORDLESS OK" || echo "sudo needs password or unavailable"
echo "=== APT NODE CANDIDATE ==="
apt-cache policy nodejs 2>/dev/null | head -6
echo "=== PYTHON VERSIONS ==="
ls /usr/bin/python3* 2>/dev/null
echo "=== ENSUREPIP ==="
python3 -m ensurepip --version 2>&1 | head -3
echo "=== VENV CREATE TEST ==="
rm -rf /tmp/_vtest && python3 -m venv /tmp/_vtest 2>&1 | head -5 && ls /tmp/_vtest/bin 2>/dev/null | head
echo "=== PIP IN VENV ==="
/tmp/_vtest/bin/python -m pip --version 2>&1 | head -2
echo "=== NODEJS.ORG REACHABLE ==="
curl -s -o /dev/null -w "http_code=%{http_code}\n" --max-time 20 https://nodejs.org/dist/latest-v22.x/ || echo "fail"
echo "=== NODE DIST INDEX ==="
curl -s --max-time 20 https://nodejs.org/dist/index.json | head -c 400
echo ""
echo "=== PROBE2 DONE ==="
