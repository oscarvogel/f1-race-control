/**
 * Prueba independiente: se suscribe al canal CarData del feed SignalR de la F1
 * y reporta que canales devuelven datos. No forma parte de la aplicacion;
 * sirve para verificar que el nombre del canal y el formato son correctos.
 */
const WebSocket = require('ws');

const F1_HTTP_URL = 'https://livetiming.formula1.com/signalrcore';
const F1_WS_URL = 'wss://livetiming.formula1.com/signalrcore';
const RECORD_SEP = '\x1e';
const HANDSHAKE = `{"protocol":"json","version":1}${RECORD_SEP}`;

const CHANNELS = [
  'SessionInfo',
  'TimingData',
  'TimingAppData',
  'DriverList',
  'CarData',
  'TrackStatus',
  'Position',
  'LapCount',
  'Heartbeat',
];

async function main() {
  const pre = await fetch(`${F1_HTTP_URL}/negotiate`, {
    method: 'OPTIONS',
    headers: { 'User-Agent': 'BestHTTP', Origin: 'https://www.formula1.com' },
  });
  const raw = pre.headers.get('set-cookie') || '';
  const m = raw.match(/AWSALBCORS=([^;]+)/);
  const cookie = m ? `AWSALBCORS=${m[1]}` : '';

  const headers = { 'User-Agent': 'BestHTTP', Origin: 'https://www.formula1.com' };
  if (cookie) headers.Cookie = cookie;

  const res = await fetch(`${F1_HTTP_URL}/negotiate?negotiateVersion=1`, {
    method: 'POST',
    headers: { ...headers, 'Content-Type': 'text/plain' },
  });
  const data = await res.json();
  const ws = new WebSocket(`${F1_WS_URL}?id=${encodeURIComponent(data.connectionToken)}`, {
    headers,
  });

  const seen = {};
  let handshakeDone = false;

  ws.on('open', () => ws.send(HANDSHAKE));

  ws.on('message', (raw) => {
    for (const segment of raw.toString('utf-8').split(RECORD_SEP)) {
      if (!segment) continue;
      let frame;
      try {
        frame = JSON.parse(segment);
      } catch {
        continue;
      }
      if (!handshakeDone) {
        if (frame.error) {
          console.log('ERROR de handshake:', JSON.stringify(frame.error));
          process.exit(1);
        }
        handshakeDone = true;
        console.log('handshake OK. suscribiendo a:', CHANNELS.join(', '));
        ws.send(
          JSON.stringify({
            type: 1,
            invocationId: '0',
            target: 'Subscribe',
            arguments: [CHANNELS],
          }) + RECORD_SEP,
        );
        continue;
      }
      if (frame.type === 3 && frame.invocationId === '0') {
        console.log('respuesta de Suscribe:', JSON.stringify(frame).slice(0, 600));
        const result = frame.result || {};
        console.log('canales en el snapshot inicial:', Object.keys(result).join(', '));
        for (const [k, v] of Object.entries(result)) {
          seen[k] = JSON.stringify(v).length;
        }
        console.log('tamanos:', JSON.stringify(seen));
        if (result.CarData) {
          console.log('CARData snapshot:', JSON.stringify(result.CarData).slice(0, 900));
        }
        continue;
      }
      if (frame.type === 1 && frame.target === 'feed') {
        const channel = frame.arguments?.[0];
        const payload = frame.arguments?.[1];
        const size = JSON.stringify(payload).length;
        if (!seen[channel]) {
          seen[channel] = 0;
          console.log(`CANAL EN VIVO -> ${channel} (${size} bytes)`);
          if (channel === 'CarData') {
            console.log('  CarData:', JSON.stringify(payload).slice(0, 900));
          }
        }
        seen[channel] = (seen[channel] || 0) + size;
      }
    }
  });

  ws.on('error', (e) => console.log('error ws:', e.message));

  const seconds = Number(process.argv[2] || 90);
  setTimeout(() => {
    console.log(`\n--- resumen tras ${seconds}s ---`);
    console.log('bytes recibidos por canal:', JSON.stringify(seen, null, 1));
    ws.close();
    process.exit(0);
  }, seconds * 1000);
}

main();
