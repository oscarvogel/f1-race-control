# Diagnóstico en vivo

Cómo saber si lo que se ve en pantalla es realmente "en vivo", y no un
histórico con la etiqueta equivocada.

---

## La regla

> `CONNECTED` por sí solo **no** demuestra que estamos recibiendo información
> actual de clasificación.

Durante los intervalos entre sesiones, el feed de cronometraje sigue
mandando mensajes (cambios de `ArchiveStatus`, latidos). El `lastMessageAt`
avanza, el proveedor dice `CONNECTED`, y sin embargo **la clasificación no se
mueve**. Por eso el estado que ve el usuario no se deriva del estado de la
conexión, sino de tres datos juntos:

| Dato | De dónde sale |
|---|---|
| Estado de la sesión | `SessionInfo.SessionStatus` (`Started` / `Finalised`) |
| Estado de la conexión | `/api/status` del servicio Node |
| Edad del último dato | `lastMessageAt` del feed, contra la hora actual |

La combinación define `LIVE` / `DELAYED` / `HISTORICAL` / `WAITING` /
`OFFLINE` / `ERROR`. Ver `docs/architecture.md`.

---

## Comprobación manual

### 1. El servicio Node

```bash
curl -s http://127.0.0.1:3000/api/status
```

```json
{
  "service": "f1-livetiming-api",
  "status": "CONNECTED",
  "isConnected": true,
  "lastMessageAt": "2026-10-24T19:20:35.255Z",
  "uptimeSeconds": 3840,
  "timestamp": "2026-10-24T19:20:35.300Z"
}
```

`lastMessageAt` debe ir avanzando. Si se congela, el WebSocket está caído
(el servicio tiene un watchdog de 20 s que fuerza la reconexión).

### 2. La sesión detectada

```bash
curl -s http://127.0.0.1:3000/api/session
```

Claves que importan: `Session.Key` (ID real), `Session.Type`
(`Practice` / `Qualifying` / `Race`), `Session.SessionStatus`,
`Session.Meeting.Name`.

### 3. Que la clasificación se mueve

```bash
watch -n 2 "curl -s http://127.0.0.1:3000/api/standings \
  | python3 -c 'import sys,json; d=json.load(sys.stdin); l=d[\"Leaderboard\"][0]; \
      x=d[\"Lines\"][l]; print(l, (x.get(\"BestLapTime\") or {}).get(\"Value\"), x.get(\"NumberOfLaps\"))'"
```

Si el mejor tiempo del líder o el número de vueltas cambian, **hay datos en
vivo de verdad**.

### 4. El grabador de evidencia

`scripts/_evidence_recorder.sh` sondea cada 5 s y deja un registro en
`.run/logs/live-evidence.log` con:

```
[2026-10-24T19:20:39Z] lastMessageAt=2026-10-24T19:20:35.255Z | sesion=United States Grand Prix|Austin|Practice|11391|Finalised | lider=44|1:34.893|23 | (sin cambio)
```

Cuando empieza la sesión, las líneas pasan a `*** CAMBIO DETECTADO ***` y la
columna `lider` cambia de valor. Ese archivo es la evidencia objetiva.

---

## Diagnóstico completo

```bash
./scripts/doctor.sh
```

Imprime datos concretos, no "OK" genéricos:

- Versiones de Python, Node, npm, uv, kernel, SO.
- Estado HTTP real de los tres servicios.
- PID de cada proceso y si sigue vivo.
- Estado del feed, `lastMessageAt` y **la edad del dato en segundos**.
- GP, circuito, país, ronda, sesión, **ID real de sesión** y estado.
- Los **diez** endpoints del proveedor con su código HTTP y su tamaño.
- Verificación de que el proveedor escucha **solo en loopback**.
- Estado de la API interna, del último ciclo de ingesta y de sus errores.
- Estado de cada proveedor con su latencia real.
- Comprobación de OpenF1 y Jolpica contra la API pública.
- IP de la LAN y aviso si `ENABLE_PUBLIC_ACCESS` está activo.
- Filas de cada tabla de la base.

---

## Problemas frecuentes

### "El proveedor se desconecta a los pocos minutos"

El proceso se muere cuando **termina la sesión de WSL** que lo lanzó. WSL
mata a los procesos en background cuando la invocación que los creó acaba.

Solución: arrancarlo **desacoplado** con `setsid` (que es lo que hacen
`start-dev.sh` y `scripts/_start_live2.sh`):

```bash
cd services/live-timing
setsid nohup env PORT=3000 HOST=127.0.0.1 node src/server.js \
  >> /ruta/.run/logs/live-timing.log 2>&1 < /dev/null &
```

Comprobación: `pgrep -af "node src/server.js"` desde **otra** invocación de
WSL. Si el proceso sigue ahí, quedó bien desacoplado.

### "El proveedor responde pero no llegan datos"

Revisar el log:

```bash
tail -40 .run/logs/live-timing.log
```

- `Handshake rejected` → el servidor rechazó la suscripción. Es un problema
  del lado del feed, no del código.
- `Watchdog timeout: No data received for 20s` → el WebSocket se cortó. El
  servicio reconecta solo.
- Sin errores pero sin datos → probablemente no hay sesión activa. Verificar
  `/api/session`.

### "Todos los pilotos aparecen 'En boxes' en una sesión terminada"

Comportamiento **correcto** del feed: al terminar la sesión, `TimingData`
conserva el último estado de cada auto y `InPit` queda en `true` para todos.
El backend guarda el valor crudo (es el dato real), pero la interfaz solo
muestra los indicadores transitorios (`En boxes`, `Parado`) mientras la sesión
está en curso. Ver `sessionIsActive` en `frontend/src/stores/race.ts`.

### "OpenF1 devuelve 404"

No es un error. La API de OpenF1 filtra por cualquier atributo, y un filtro
por un atributo inexistente devuelve `404 {"detail": "No results found."}`.
Por ejemplo `&limit=1` no es un atributo de `sessions` y por eso rompe la
consulta. Los operadores de filtro (`>=`, `<=`) van **crudos** en la query
string.

### "El frontend no carga datos"

1. ¿Está corriendo el proceso de ingesta? `pgrep -f ingest_live`.
2. ¿Hay snapshot? `curl -s http://127.0.0.1:8000/api/health/`.
3. ¿Responde el backend? `curl -s http://127.0.0.1:8000/api/sessions/current/`.
4. Revisar `.run/logs/backend.log` y `.run/logs/ingest.log`.

### "CORS"

El backend solo acepta el origen del frontend local. Si se abre el frontend
desde otra IP de la LAN, hay que poner `ENABLE_LAN_ACCESS=true` y declarar
`LAN_ALLOWED_HOSTS` / `LAN_ALLOWED_ORIGINS` en `.env`.

---

## Acceso desde la LAN (modo opcional y protegido)

Objetivo: que el hijo pueda abrir el dashboard desde otro equipo de la casa,
**sin** abrir puertos del router.

1. En `.env`:
   ```env
   ENABLE_LAN_ACCESS=true
   LAN_ALLOWED_HOSTS=192.168.0.50
   LAN_ALLOWED_ORIGINS=http://192.168.0.50:5173
   ```
2. Levantar el frontend y el backend escuchando en la IP de la LAN en vez de
   `127.0.0.1` (`FRONTEND_HOST` / `BACKEND_HOST`), o usar un proxy inverso
   local que los publique en la LAN.
3. **Firewall**: permitir el tráfico de la LAN solo hacia los puertos 5173 y
   8000, y **solo** desde la red privada. Nunca abrir esos puertos en el
   router (eso es NAT/port-forwarding, no hace falta).
4. El servicio de cronometraje (puerto 3000) **no** se expone: el backend lo
   consume en local.

Recomendación práctica: un proxy inverso local (Caddy o nginx) en la LAN con
HTTPS y autenticación básica, apuntando al frontend y a la API, y el firewall
permitiendo solo ese puerto desde la red privada.

---

## Lista de verificación antes de declarar `LIVE`

1. `/api/status` del proveedor: `isConnected: true`.
2. `lastMessageAt` **avanzando** (no congelado).
3. `/api/session`: `SessionStatus: "Started"` y `Type` de la sesión esperada.
4. La sesión del proveedor es la **misma** que la del evento (GP, circuito, ID).
5. La mejor vuelta o el número de vueltas **cambian** entre dos consultas.
6. El snapshot del backend cambia de huella (columna `changed` en
   `core_ingestionrun`).
7. El navegador muestra la insignia `LIVE` y la edad del dato baja de 90 s.

Si falla el punto 5, el estado **no** es `LIVE` aunque los demás pasen.
