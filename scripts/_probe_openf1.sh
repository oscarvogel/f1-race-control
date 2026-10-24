#!/usr/bin/env bash
echo "=== A) curl simple, ver body completo ==="
curl -s -i --max-time 25 'https://api.openf1.org/v1/sessions?year=2025&limit=1' | head -40
echo ""
echo "=== B) con User-Agent de navegador ==="
curl -s -i --max-time 25 -A 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36' \
  'https://api.openf1.org/v1/sessions?year=2025&limit=1' | head -25
echo ""
echo "=== C) endpoint de la doc (car_data) ==="
curl -s -o /dev/null -w "http_code=%{http_code}\n" --max-time 25 'https://api.openf1.org/v1/car_data?driver_number=55&session_key=9159&speed>=315'
echo "=== D) meetings ==="
curl -s -o /dev/null -w "http_code=%{http_code}\n" --max-time 25 'https://api.openf1.org/v1/meetings?year=2025&limit=1'
echo "=== E) raiz y docs ==="
curl -s -o /dev/null -w "root=%{http_code}\n" --max-time 20 'https://api.openf1.org/'
curl -s -o /dev/null -w "auth=%{http_code}\n" --max-time 20 'https://openf1.org/auth.html'
echo "=== F) status abierto ==="
curl -s -o /dev/null -w "status=%{http_code}\n" --max-time 20 'https://status.openf1.org/api/v2/status.json'
echo "=== G) con header Authorization vacio ==="
curl -s -o /dev/null -w "http_code=%{http_code}\n" --max-time 20 -H 'Authorization: ' 'https://api.openf1.org/v1/meetings'
echo "=== H) API key de la doc (formato Authorization: Bearer) ==="
curl -s -o /dev/null -w "http_code=%{http_code}\n" --max-time 20 -H 'Authorization: Bearer INVALID' 'https://api.openf1.org/v1/meetings'
echo "=== I) desde WSL -> mismo resultado? ==="
curl -s -o /dev/null -w "http_code=%{http_code}\n" --max-time 20 'https://api.openf1.org/v1/meetings?year=2025&limit=1'
