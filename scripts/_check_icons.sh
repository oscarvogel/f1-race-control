#!/usr/bin/env bash
export PATH="$HOME/.local/node/bin:$PATH"
PROJ=/mnt/c/Programacion/proyectos/actives/f1-race-center
cd "$PROJ/frontend"
npm install --no-audit --no-fund 2>&1 | tail -6

echo "=== exports de @lucide/vue ==="
node -e "
const icons = ['Activity','Radio','Settings2','Wifi','WifiOff','ChevronDown','ChevronUp','CircleDot','Clock','Database','Plug','Server','X','Flag','Gauge','Timer','TriangleAlert','MessageSquareWarning','CloudRain','Droplets','Thermometer','Wind','AlertCircle','CircleAlert','RefreshCw'];
import('@lucide/vue').then((m) => {
  const missing = icons.filter((n) => !(n in m));
  console.log('total exports:', Object.keys(m).length);
  console.log('FALTAN:', missing.length ? missing.join(', ') : '(ninguno)');
  const alt = ['CircleAlert','TriangleAlert','AlertTriangle','CircleDot','Dot'];
  console.log('alternativas presentes:', alt.filter((n) => n in m).join(', '));
}).catch((e) => { console.error('ERROR import:', e.message); process.exit(1); });
"
