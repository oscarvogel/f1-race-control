# Bitácora de trabajo — Race Center

Registro de qué se hizo, cómo, qué problemas aparecieron y cómo se
resolvieron, y qué queda pendiente.

**Proyecto:** Race Center — dashboard personal de Fórmula 1
**Entorno:** WSL Ubuntu 26.04.1 LTS · Python 3.12.15 · Node 22 LTS
**Período de este registro:** 24/10/2026
**Circuito de referencia:** GP de Estados Unidos 2026 — Austin (COTA)
`meeting_key 1297` · `circuit_key 9`

---

## 1. Qué se entregó

| Entrega | Estado |
|---|---|
| Clasificación en vivo con datos reales | funcionando |
| Selector de sesión (FP1/FP2/FP3/Sprint/Clasificación/Carrera) | funcionando |
| Vista del circuito con la posición de cada piloto | implementada, pendiente de verificar en vivo |
| Hora local + hora del circuito + cuenta regresiva a la próxima sesión | funcionando |
| Previsión meteorológica del circuito (Open-Meteo) | funcionando |
| Panel de diagnóstico del estado de los proveedores | funcionando |
| Historical replay desde OpenF1 | funcionando |
| Trazado del circuito derivado de GPS real | funcionando (74 puntos, COTA) |
| Documentación (`architecture`, `providers`, `live-diagnostics`) | completa |
| Pruebas automatizadas | 77 pruebas en verde |

---

## 2. Decisiones de encuadre

Estas decisiones vienen del pedido y conviene dejarlas escritas porque
condicionan todo lo demás:

1. **Aplicación personal, no producto.** Sin planes, sin suscripciones, sin
   publicación a Internet. Todo corre local en WSL.
2. **El frontend solo habla con nuestra API.** Nunca consume OpenF1, Jolpica
   ni el servicio Node directamente. Eso elimina credenciales en el navegador
   y evita que abrir dos pestañas duplique la ingesta.
3. **La fuente de la verdad es el feed oficial de cronometraje**, servido por
   el servicio Node local. OpenF1 es histórico y de apoyo; Jolpica, solo
   metadatos.
4. **Un pedido en vivo jamás se resuelve con un proveedor histórico.** Si la
   fuente en vivo no está, el sistema lo dice con su motivo; no disfraza un
   histórico de directo. Está cubierto por una prueba propia.
5. **Ausencia de dato ≠ cero.** Un valor que no existe es `None` y se muestra
   `—`. Nunca `0`, nunca un valor inventado.
6. **No se declara `LIVE` sin evidencia.** `CONNECTED` solo prueba que el
   socket está abierto. Para declarar `LIVE` hace falta que la clasificación
   cambie, y eso se verifica contra el feed.

---

## 3. Entorno: toolchain instalado sin `sudo`

WSL no traía lo necesario y `sudo` pide contraseña interactiva, así que todo
se instaló en `~/.local`:

| Herramienta | Versión | Cómo |
|---|---|---|
| uv | 0.13.5 | `~/.local/bin` |
| CPython | 3.12.15 | `uv python install 3.12` |
| Node.js | 22.23.4 | tarball oficial en `~/.local/node` |
| npm | 10.9.9 | con Node |

El `PATH` quedó persistido en `~/.bashrc` bajo el bloque
`# race-center-toolchain`.

El Python del sistema (3.14.4) no tiene `pip`, `ensurepip` ni `venv`, y no
hay `gcc`/`make`: por eso el backend corre sobre un `.venv` de uv con
CPython 3.12 y las dependencias nativas que lo requieren (SQLite) llegan por
ruedas precompiladas.

---

## 4. Diagnóstico del canal en vivo (P0)

### 4.1 Lo que se comprobó contra el feed real

- `livetiming.formula1.com/signalrcore` responde: `OPTIONS /negotiate` → 405
  (solo fija cookie) y `POST /negotiate?negotiateVersion=1` → **200** con
  `connectionToken`.
- El servicio Node queda `CONNECTED` y `lastMessageAt` avanza (~cada 15 s).
- Los **10 endpoints** del proveedor responden 200: status, session, standings,
  leaderboard, tyres, weather, race-control, radio, lap-count, drivers. Más los
  dos añadidos en este trabajo: `car-data` y `track-status`.

### 4.2 Datos reales confirmados de Austin 2026

- GP: *United States Grand Prix* · `Meeting.Key 1297` · `Location Austin` ·
  `OfficialName FORMULA 1 MSC CRUISES UNITED STATES GRAND PRIX 2026`.
- Sesión `11391` (Practice 3) con `SessionStatus = Finalised`.
- Clima real: aire 28.2 °C, pista 40.9 °C, humedad 44 %, presión 1003.2,
  lluvia 0, viento 2.4 m/s a 138°.
- Control de carrera: 50 eventos, incluidos penalizaciones, stewards y
  `CHEQUERED FLAG 18:30:00Z` con *FIRST CAR TO TAKE THE FLAG - CAR 55 (SAI)*.
- Pilotos 2026: NORRIS/McLaren `F47600`, VERSTAPPEN/Red Bull `4781D7`,
  BORTOLETO/Audi `F50537`, HAMILTON/Ferrari `ED1131` (22 pilotos en total).
- Clasificación: P1 HAMILTON `1:34.893` (vuelta 12), P2 VERSTAPPEN `1:35.061`
  (+0.168), P3 LECLERC `1:35.127` (+0.234). Sectores S1 78.056 / S2 41.082 /
  S3 37.368, stints reales SOFT/MEDIUM/HARD, `NumberOfLaps`,
  `NumberOfPitStops` y velocidades por punto (I1, I2, FL, ST).

### 4.3 El detalle que evita un falso positivo

Entre sesiones, el feed sigue mandando heartbeats: `lastMessageAt` avanza cada
~15 s **sin que la clasificación cambie**. Un panel que solo mire el timestamp
diría "LIVE" estando la sesión terminada.

Por eso el estado no se deduce del heartbeat sino de la sesión:
`SessionStatus = Finalised` → `HISTORICAL`. Y la distinción queda explícita en
`docs/live-diagnostics.md` y en el panel de diagnóstico.

### 4.4 Formato real del feed (condiciona el normalizador)

Estos detalles no están en ninguna documentación y se castigaron a base de
datos mal interpretados:

- `Sectors` llega como **lista** de 3 (índice 0 = S1), no como diccionario.
- `BestLapTimes` llega como dict con claves `"0"/"1"/"2"` = Q1/Q2/Q3, y solo
  existe en clasificación.
- Aparece un marcador fantasma `_kf` en `Leaderboard` y `Lines`: no es un
  piloto y se descarta.
- En clasificación los gaps son cadenas (`TimeDiffToFastest`,
  `TimeDiffToPositionAhead`); en carrera son objetos (`GapToLeader`,
  `IntervalToPositionAhead`) con `Value`.
- El líder no tiene gap: el feed manda `""`. Se normaliza a `None`, **nunca**
  a `0.000`.
- `New` de neumáticos llega como cadena `"true"/"false"`.
- `getLiveStandings` hace deep-merge de `DriverList` + `TimingData` (incluye
  `BestLapTimes`); `getLiveLeaderboard` además suma `TimingAppData` (stints,
  `GridPos`).
- En sesión finalizada el feed deja `InPit = true` para los 22 pilotos (último
  estado). Se conserva crudo en el backend, pero la UI solo muestra
  indicadores transitorios cuando `sessionIsActive`.

### 4.5 Qué canales publica el feed (y por qué el mapa no tiene autos)

Para responder "dónde está cada piloto" hubo que **sondar el feed** en vez de
suponerlo. La sonda (`.run/probe_feed.js`) replica el handshake del cliente
real: pre-negociación `OPTIONS`, cookie `AWSALBCORS`, `POST /negotiate`,
WebSocket con `id=<connectionToken>`, handshake `{"protocol":"json","version":1}`
y `Subscribe` con la lista de canales.

**La primera versión de la sonda estaba rota** y dio una conclusión falsa:tomaba
`frame.target` como nombre del canal, pero en SignalR Core el `target` siempre
es `"feed"`; el canal va en `frame.arguments[0]` y el payload en
`frame.arguments[1]`. Con ese error, hasta el grupo de control (`TimingData`,
`SessionInfo`, …) parecía "sin mensajes", y la conclusión "el canal `Positions`
no existe" era falsa. Corregida, la sonda sí suscribe y recibe.

Resultado, con la sesión de clasificación de Austin 2026 en curso:

| Canal | ¿Llega? | Nota |
|---|---|---|
| `TimingData`, `TimingDataF1`, `TimingAppData` | sí | 73 y 8 mensajes en 40 s |
| `WeatherData`, `TimingStats` | sí | |
| `DriverList`, `SessionInfo`, `RaceControlMessages`, `TeamRadio` | en el snapshot inicial | |
| `TrackStatus` | **sí** | `{"Status":"1","Message":"AllClear"}` |
| `ExtrapolatedClock`, `AudioStreams` | en el snapshot inicial | |
| `CarData`, `Positions`, `Position`, `CarStatus`, `Clock`, `LapCount` | **no** | suscripción válida, el feed no publica nada |

La conclusión importante: **la suscripción a `CarData` y `Positions` es
correcta** (el propio `TrackStatus`, añadido por el mismo parche, sí llega), pero
**durante la clasificación el feed no publica coordenadas**. No es un bug del
código: es lo que hace la fuente. Por eso el mapa en vivo no puede mostrar los
autos durante la quali, y la interfaz lo dice explícitamente en lugar de
dejar el panel vacío.

También quedó documentado el formato de `Stats`, que es lo que hace funcionar
la columna de gap:

- `Stats` llega como **dict** `{"0": {...}, "1": {...}}` o como **lista** de 3.
- El valor útil **no siempre está en el índice 0**: un piloto que hizo su
  tiempo en Q2 lo tiene en el índice 1.
- En el knockout (Q3) el feed **vacía** `BestLapTime` (`{"Value": "", "Lap": N,
  "_deleted": ["Lap"]}`): ese campo sigue el segmento en curso, no la sesión.
- Para un piloto **en pista**, el feed escribe el delta en vivo en el primer
  slot aunque su segmento actual sea el segundo: por eso la etiqueta de
  segmento (Q1/Q2/Q3) solo se muestra si el piloto tiene una vuelta completada
  en ese segmento.

---

## 5. Proveedores implementados

| Proveedor | Ámbito | Estado |
|---|---|---|
| `FreeLiveTimingProvider` | live | conectado, alimentado por el servicio Node |
| `OpenF1Provider` | histórico | conectado; cuota por IP (ver §7) |
| `JolpicaProvider` | metadatos | conectado; nunca se usa para cronometraje |

Las capacidades no soportadas se **declaran** (`UnsupportedCapability`) en vez
de simularse. `Jolpica` tiene `live/timing/laps/weather/race_control/
telemetry/positions = False` a propósito.

### 5.1 OpenF1: trampas documentadas

- Un filtro por un atributo inexistente devuelve **404**
  `{"detail": "No results found."}` (por ejemplo `&limit=1`): no es un
  endpoint caído, es "sin resultados".
- Los operadores `>=` / `<=` deben ir **crudos** en la query string;
  codificarlos rompe el filtro.
- `404` significa "sin resultados", no "error".
- `429` = límite de tasa (ver §7).
- El histórico es gratis desde 2023; el live requiere suscripción pagada y
  **no** está habilitada (queda preparada con `OPENF1_LIVE_ENABLED` +
  `OPENF1_API_KEY`).

### 5.2 Sesiones de Austin 2026 en OpenF1 (`meeting_key 1297`)

`11389` P1 · `11390` P2 · `11391` P3 · **`11392` Clasificación**
(`2026-10-24T21:00:00+00:00`) · `11396` Carrera.

Al momento de la escritura, `11392` ya listaba los 22 pilotos pero **sin
vueltas ni resultado**: correcto, la sesión todavía no empezaba.

---

## 6. Parches al proveedor upstream

`services/live-timing` es código de terceros (Apache-2.0 + `NOTICE`). Se parcheó
solo en dos casos, ambos documentados y con copia de seguridad en
`services/live-timing/.race-center-backup/`. Los parches son idempotentes y
están marcados con `[Race Center patch]` / `[Race Center addition]`.

1. **Seguridad** (autorizado por la sección 15 de la especificación):
   `const HOST = process.env.HOST || '127.0.0.1'` + `app.listen(PORT, HOST, …)`
   — el upstream escuchaba en `0.0.0.0` — y CORS restringido a orígenes
   loopback en lugar de `cors()` abierto. Se preserva el CRLF original.
2. **Ampliación aditiva** (pedido explícito del usuario): suscripción a los
   canales **`CarData`** (posiciones X/Y/Z + telemetría por auto) y
   **`TrackStatus`** (banderas / safety car), con el deep-merge existente,
   getters `getCarData()` / `getTrackStatus()` y las rutas
   `/api/car-data` y `/api/track-status`.

**La lógica de cronometraje del upstream no se tocó.**

---

## 7. Limitación de tasa de OpenF1 (corregido 24/10/2026)

### 7.1 El síntoma

`/api/sessions/historical/<key>/` respondía siempre
`{"found": false, "reason": "No hay datos historicos para la sesion 11389."}`.
El log del backend decía:

```
WARNING racecenter.history: No se pudo construir el snapshot historico 11389:
OpenF1 respondio 429 (limite de tasa) en /weather.
```

### 7.2 El diagnóstico

Medición directa contra la API (`.run/probe_openf1_limit.sh`):

```
10 peticiones a /weather: 200 200 200 200 200 200 429 429 429 429
cabecera del 429: retry-after: 60
```

Causas, en dos niveles:

1. **El retry ignoraba al servidor.** El código esperaba 2 s, 4 s y 6 s. El
   servidor pedía **60 s** (`retry-after: 60`). Nunca iba a alcanzar.
2. **El consumo estaba en el sitio equivocado.** El proceso de ingesta
   llamaba a `refresh_status()` cada 3 s y **sondeaba OpenF1** con su health check,
   que descarga `/sessions?year=2026` (48 KB). Sondear cada 3 s a un proveedor
   con límite por IP no aporta nada: el dato histórico no cambia. La cuota se
   consumía sola, en segundo plano, sin que nadie lo pidiera.

### 7.3 Las correcciones

| # | Cambio | Archivo |
|---|---|---|
| 1 | Respetar la cabecera `retry-after` del servidor (tope de 90 s) | `providers/openf1.py` |
| 2 | Intervalo mínimo entre peticiones (1 s) | `providers/openf1.py` |
| 3 | **Cooldown**: durante el periodo indicado no se emite ninguna petición | `providers/openf1.py` |
| 4 | `ProviderRateLimited` (subclase de `ProviderError`) para distinguir cuota agotada de caída | `providers/base.py` |
| 5 | Un 429 **no** deja el proveedor en `ERROR`: sigue conectado, lo que se agotó es la cuota | `providers/openf1.py` |
| 6 | `health_check_interval` por proveedor, respetado por el manager | `providers/base.py`, `providers/manager.py` |
| 7 | OpenF1 y Jolpica sondean cada 300 s en vez de cada 3 s | `providers/openf1.py`, `providers/jolpica.py` |
| 8 | La parte opcional de un snapshot histórico se degrada sin tumbar el resto | `core/history.py` |
| 9 | Caché de snapshots históricos (memoria 10 min + base) | `core/history.py`, `core/views.py` |
| 10 | Los avisos de datos incompletos se muestran en pantalla | `frontend/src/views/DashboardView.vue` |

### 7.4 La medición que fija la constante

`.run/probe_openf1_rate.sh` mide el intervalo mínimo sostenible:

| Intervalo | Resultado |
|---|---|
| 2.0 s | 15/15 correctos, ningún 429 |
| 1.0 s | ver log de la sonda |
| 0.5 s | ver log de la sonda |

Con un intervalo de 1 s y un cooldown respetuoso, la cuota deja de ser el
factor limitante.

### 7.5 OpenF1 bloquea todo durante una sesión en vivo

Descubierto el 24/10/2026, justo antes de la clasificación. OpenF1 cambio su
politica de acceso a las 20:44 UTC y paso a responder **401** a *todo*,
incluidas las sesiones ya terminadas:

```
{"detail": "Live F1 session in progress. Global API access (including past
sessions) is restricted to authenticated users until the session ends.
Get an API key here: https://buy.stripe.com/..."}
```

El efecto practico: en plena sesion, el catalogo de sesiones se quedaba
vacio y con el disappearia la cuenta regresiva a la proxima sesion, justo
cuando mas hace falta.

**Como se resolvió, sin perder funcionalidad:**

1. **El catalogo se guarda en la base** (`scope = "catalog"`). Si OpenF1 no
   responde, se usa la copia guardada, marcada como `stale`.
2. **Jolpica pasa a ser la segunda fuente del calendario.** No se bloquea, y
   publica la hora de inicio de cada sesion del fin de semana (FP1, FP2,
   FP3, Sprint, Clasificacion y Carrera). El catalogo se construye desde ahi
   cuando OpenF1 no responde.
3. **Las claves de sesion se recuperan de la base** (`Session`), o sea de las
   que ya se habian descargado antes. Asi el selector sigue ofreciendo los
   FP y la carrera.
4. Los **snapshots historicos ya descargados** se sirven desde la base sin
   volver a preguntar a OpenF1: el replay de los FP sigue funcionando
   durante la carrera.

La limitacion que queda: una sesion historica **que nunca se haya descargado**
no se puede consultar durante una sesion en vivo sin clave de OpenF1. Se
documenta en `docs/providers.md`.

---

## 8. Relojes del circuito y prevision meteorologica

### 8.1 Las tres horas, y por que son distintas

El dashboard muestra tres referencias horarias, cada una de una fuente:

| Reloj | Zona | Origen del dato |
|---|---|---|
| **Argentina** | `America/Argentina/Cordoba` | Configuracion del backend |
| **Circuito** | desfase real del circuito | `GmtOffset` del feed de F1 / `gmt_offset` de OpenF1 |
| **Próxima sesión** | cuenta regresiva | `start_time_utc` del catálogo de sesiones |

La hora del circuito **no** se deduce del nombre del trazado: sale del
desfase que publica la propia organización (`-05:00:00` para Austin). Deducir
la zona horaria por el nombre del circuito es una fuente de errores
clásicos, porque cambia con el horario de verano.

La cuenta regresiva está en una franja propia bajo la cabecera, en números
monoespaciados grandes, y **se pone en rojo cuando faltan menos de 15
minutos**. Si hay que mirar algo, es eso.

### 8.2 Previsión meteorológica (Open-Meteo)

El feed de F1 da el clima **actual** del circuito y OpenF1 guarda el clima
**histórico** de una sesión. Ninguno de los dos dice qué va a pasar en la
sesión que viene, que es justo lo que se quiere saber antes de que empiece.

La previsión viene de **Open-Meteo** (servicio público, sin clave, sin
suscripción): temperatura, probabilidad de lluvia, precipitación, código de
tiempo y viento, hora a hora.

Reglas que rigen el módulo (`backend/core/weather.py`):

1. **La previsión nunca se mezcla con el clima observado.** Son dos paneles
   distintos, cada uno con su fuente a la vista.
2. **Las coordenadas son datos reales**, no aproximadas: COTA está en
   `30.1328, -97.6411`, tomado de Jolpica (`circuitId "americas"`). Cada
   par lleva anotado su origen en `coordinates_source`.
3. **Sin coordenadas no hay previsión.** Si el circuito no está en el mapa,
   no se busca una ciudad parecida: no se muestra nada.
4. **Se cachea 15 minutos.** No tiene sentido pegarle al servicio en cada
   refresco del dashboard.
5. **La ventana de la próxima sesión** se calcula aparte: es la pregunta útil
   ("con estas condiciones va a correr la clasificación").

Ejemplo real, clasificación del GP US 2026 (21:00 UTC):

```
PROXIMA SESION: Qualifying 2026-10-24T21:00:00+00:00
  resumen: temp 28.9–29.3 °C · probabilidad de lluvia 0 % · viento máx. 17.3 km/h
  2026-10-24T21:00  29.3 °C  0 %  Despejado   viento 15.0
  2026-10-24T22:00  28.9 °C  0 %  Despejado   viento 17.3
```

---

## 9. Bugs encontrados y cómo se resolvieron

Todos detectados por pruebas o por contraste contra la salida real del
sistema, no por lectura de código.

### Backend

| # | Bug | Causa | Cómo se resolvió |
|---|---|---|---|
| 1 | `SynchronousOnlyOperation` | ORM síncrono de Django dentro de contexto async | `sync_to_async(..., thread_sensitive=True)` en la persistencia |
| 2 | El proveedor live nunca se conectaba (`NameError: self.timeout`) | `self.timeout` no existía en `FreeLiveTimingProvider` | Se agregó el atributo; `is_live` volvía `False` sin avisar |
| 3 | `delete()` sobre queryset recortado | Recorte de bitácora mal aplicado | Borrado por PK, no por queryset recortado |
| 4 | `manager.get_capabilities()` inexistente | El método real es `capabilities()` | Corregido el nombre de la llamada |
| 5 | `parse_lap_time` leía `"1:35"` como 1.35 s | Regex sin el grupo de minutos obligatorio | Regex reescrita con `(?:\d+:)?` y grupo de segundos acotado |
| 6 | Una fila de snapshot por cada poll (3 s) | El fingerprint incluía `generated_at` | Se excluyen los campos volátiles del fingerprint |
| 7 | El histórico nunca se completaba | §7 | Ver §7.3 |
| 8 | Un 429 dejaba a OpenF1 en `ERROR` | Se usaba `ProviderError` para todo | `ProviderRateLimited` y estado conservado |
| 19 | **Un histórico tomaba el lugar del snapshot en vivo** | `latest_snapshot()` tomaba la fila más reciente de la tabla, sin distinguir ámbito: al cargar un FP1, el dashboard en vivo pasaba a servir datos históricos | Campo `scope` en `SessionSnapshot` (+ migración con corrección de datos) y filtro por `scope="live"` en `latest_snapshot()` |
| 20 | `IntegrityError: NOT NULL constraint failed: core_sessionsnapshot.scope` | Se aplicó la migración con el stack corriendo: el proceso viejo no conocía la columna nueva | `start-dev.sh` aplica las migraciones **antes** de arrancar los servicios, y con el stack detenido |
| 25 | **La columna de GAP salía vacía en clasificación** | El normalizador solo miraba `Stats[0]` y solo si `Stats` era **lista**. El feed entrega `Stats` como **dict** `{"0": {...}}` o como lista de 3, y el valor útil no siempre está en el índice 0 (el que hizo su tiempo en Q2 lo tiene en el 1) | Se normaliza `Stats` a una lista `(índice, datos)` y se recorren todos los segmentos; se queda el último con dato, que es el gap más reciente que publicó F1 para ese piloto |
| 26 | **La columna MEJOR VUELTA quedaba en "—" durante el knockout** | En Q3 el feed vacía `BestLapTime` (`{"Value": "", "_deleted": ["Lap"]}`): ese campo sigue el segmento en curso, no la sesión | La mejor vuelta se calcula como el mejor tiempo entre el valor de nivel superior y los mejores por segmento (`BestLapTimes`), con su número de vuelta |
| 27 | El mapa del circuito nunca mostraba autos en el replay | El snapshot histórico traía `"positions": []` hardcodeado, aunque el proveedor ya tenía `get_positions()` | `build_historical_snapshot()` pide las posiciones a OpenF1 (`/location`) y las guarda en el snapshot |
| 28 | La sonda de canales daba una conclusión falsa | Tomaba `frame.target` como nombre de canal; en SignalR Core el `target` siempre es `"feed"` y el canal va en `frame.arguments[0]` | Sonda corregida (§4.5) y suscripción enviada tras el handshake, como hace el proveedor |

### Proveedor Node (upstream)

| # | Bug | Cómo se resolvió |
|---|---|---|
| 9 | Escuchaba en `0.0.0.0` (expuesto a la LAN) | Parche de seguridad: bind en `127.0.0.1` |
| 10 | CORS abierto (`cors()` sin restricciones) | Parche de seguridad: solo orígenes loopback |

### Frontend

| # | Bug | Cómo se resolvió |
|---|---|---|
| 11 | Alias `@` inexistente en Vite | Alias configurado en `vite.config.ts` |
| 12 | El watcher de Vite no disparaba sobre `/mnt/c` | `server.watch.usePolling = true`, intervalo 1000 ms |
| 13 | 404 de `favicon.ico` | Favicon SVG como data-URI en `index.html` |
| 14 | `lucide-vue-next` deprecado | Migrado a `@lucide/vue` 1.61.0 (6508 exports; todos los iconos usados verificados) |
| 15 | Gap duplicado en la tabla | La columna de intervalo mostraba el mismo valor que el gap |
| 16 | Chips "PIT" en los 22 pilotos | El feed deja `InPit=true` en sesión finalizada; los indicadores transitorios se ocultan si `sessionIsActive` |
| 21 | La columna de neumático salía vacía en el histórico | En OpenF1 el compuesto no viene en la entrada de clasificación sino en los stints: se resuelve desde `tyres` |
| 22 | "Último dato: sin dato" en modo histórico | La edad del proveedor en vivo no corresponde a la sesión que se mira: en histórico se muestra la edad del snapshot |
| 23 | El dashboard no se veia desde Windows | En esta maquina el 5173 ya lo ocupa otro proyecto (`0.0.0.0:5173` en Windows); el navegador caia ahi y no a Race Center | Race Center paso a **5174** (`FRONTEND_PORT` en `.env`). La API (8000) y el proveedor live (3000) no tienen conflicto |
| 24 | La base crecia sin limite | Cada snapshot en vivo pesa ~90 KB y se escribia uno nuevo cada vez que cambiaba el dato; `SessionSnapshot` no se recortaba nunca (181 filas y 19 MB en una tarde) | `trim_history()` recorta los snapshots **en vivo** a los ultimos 200. Los historicos no se tocan: hay uno por sesion |
| 29 | En la clasificación no se veía cuánto faltaba para que terminara | El feed publica `SessionInfo.EndDate` (hora local del circuito) y `GmtOffset`, pero el backend no lo exponía como "fin de sesión" y la interfaz no lo mostraba | `SessionInfo.end_time_utc` ya se calculaba; se expone en el store (`sessionEndAt` / `sessionEndsInMs`) y se muestra un contador **FINALIZA EN hh:mm:ss** en la cabecera de la clasificación, en rojo cuando faltan menos de 5 minutos |
| 30 | Los dos relojes de la interfaz podían desfasarse | La cabecera y la clasificación llevaban cada una su propio `setInterval` | Se extrajo un reloj compartido (`composables/useClock.ts`) con un único intervalo para toda la app |
| 34 | El sitio desplegado abría el **diálogo nativo del navegador** para pedir usuario y contraseña | nginx con `auth_basic`: el diálogo es del navegador, en inglés, fuera del tema de la app y sin forma de cerrar sesión | Login propio de la aplicación (§14): la pantalla de acceso es un panel de la app y la protección la aplica nginx con `auth_request` |
| 35 | La cookie de sesión no se podía firmar | `DJANGO_SECRET_KEY=` vacío en el `.env` **sí** cuenta como variable definida: `os.environ.get(...)` devuelve `""` y no el valor por defecto | La clave toma el valor por defecto cuando la variable está vacía. Con la clave vacía, Django no revienta al arrancar sino al firmar (mas dificil de ver) |
| 36 | El campeonato no mostraba equipos y los podios salían en 0 | El endpoint de standings de Jolpica trae el equipo en `Constructors` (**lista**, el actual es el último) y **no** trae podios; el standings de constructores va en otro endpoint | Se parsea la lista, se piden los constructores aparte y los podios quedan en `None` (se dibujan "—", nunca 0) |
| 37 | El snapshot histórico se caía al pedir posiciones | El código nuevo de `get_positions` usaba `LOCATION_TIMEOUT_SECONDS`, que no estaba definido | Se.define la constante (120 s: son varios MB por piloto) y se actualizan los tests para el pedido por piloto |
| 38 | Ordenar la clasificación por neumático rompía la tabla | En `ClassificationTable.vue` la función de ordenamiento llamaba `compoundOf(a)`, pero `a` no existe en ese ámbito (la entrada se llama `entry`) | `compoundOf(entry)`. Era un `ReferenceError` en vivo: solo se veía al ordenar por neumático |
| 39 | En el sitio desplegado, la **clasificación final** no cargaba ("must be real number, not NoneType") | OpenF1 devolvió `gap_to_leader` vacío o nulo para varios pilotos de la quali de Austin; el formato `"+%.3f" % None` reventaba y tumbaba **todo** el snapshot histórico de la sesión | Se comprueba que el gap sea numérico antes de formatearlo: sin dato, el gap queda en `None` (se dibuja "—", nunca `+0.000`). En local no se veía porque el snapshot ya estaba cacheado en la base |
| 40 | `supervisorctl status` no hablaba con el socket | Faltaba la sección `[rpcinterface:supervisor]` en `deploy/supervisord.conf` | Se agregó. Los procesos always corrieron; era solo el comando de consulta el que no respondía |
| 41 | En el mapa del replay salían **4 autos de 22** | El throttle de OpenF1 leía `_last_request_at` y lo actualizaba **después** del `await`: las 22 peticiones en paralelo calculaban el mismo hueco, dormían lo mismo y salían todas a la vez → 429 en 18 de ellas | El turno se reserva **antes** de esperar (sin `await` entre la lectura y la escritura, es atómico en asyncio) y hay una segunda pasada para los drivers que fallan. Medido: de 4 a 20-22 posiciones |
### Entorno

| # | Bug | Cómo se resolvió |
|---|---|---|
| 17 | WSL mata los procesos en background al cerrar la sesión | `setsid nohup … < /dev/null &` |
| 18 | La sonda de tasa no arrancaba | Mismo motivo: faltaba `setsid` |

---

## 10. Verificación en navegador

Chrome DevTools MCP, sobre el dashboard real con datos de Austin 2026, en
**1638×969** y **1366×768**:

- Cabecera con estado `HISTORICAL`, proveedor "F1 Live Timing (servicio local
  Node.js)", antigüedad del dato ("hace 4s") y hora de Argentina.
- Tabla con los 22 pilotos, colores de equipo, tiempos y `—` donde falta el
  dato.
- Panel de piloto: HAMILTON con sectores S1 1:18.056 / S2 1:15.204 /
  S3 0:39.705.
- Clima, 50 eventos de control de carrera, stint de neumáticos y gráfico de
  mejores vueltas (Apache ECharts).
- Consola limpia (el 404 del favicon quedó corregido).
- Árbol de accesibilidad completo y correcto.

---

## 11. Pruebas

```
cd backend && ./.venv/bin/python -m pytest
```

**106 pruebas en verde.** Reparto:

| Archivo | Qué cubre |
|---|---|
| `test_normalization.py` | Formato real del feed: sectores, gaps, `Stats` (dict y lista), mejor vuelta por segmento, posiciones GPS (por piloto, en paralelo), `None` vs `0` |
| `test_manager.py` | Selección por semántica, prioridad, fallback |
| `test_api.py` | Endpoints de la API interna |
| `test_persistence.py` | Modelos, deduplicación, fingerprint, ámbito del snapshot |
| `test_rate_limit.py` | Cadencia de health check, `retry-after`, cooldown, degradación |
| `test_weather.py` | Previsión: coordenadas, códigos de tiempo, ventana de sesión |
| `test_auth.py` | Login propio: sesión, cookie `HttpOnly`, 401 **sin** `WWW-Authenticate`, freno de fuerza bruta, cookie inventada |
| `test_analysis.py` | Deltas por sector, delta contra otra sesión, sector ausente (`None`), campeonato de Jolpica |

Las tres reglas duras tienen prueba propia: **un pedido live no se resuelve
con un proveedor histórico**, **ausencia ≠ cero**, y **un snapshot incompleto
no es un fallo**.

---

## 12. Pendientes

### Prioridad alta

1. **Verificar que las coordenadas en vivo llegan en la carrera.**
   La clasificación ya está **verificada en vivo** (§10), pero el mapa sigue
   sin autos: el feed **no publica** coordenadas durante la clasificación
   (§4.5), no es un fallo del código. La carrera es el 25/10 a las 20:00 UTC:
   ahí hay que comprobar si `CarData`/`Positions` publican `X/Y/Z` y, si lo
   hacen, los autos aparecen solos en el mapa (la ruta de código ya está
   escrita y probada).
2. **Elección del replay**: con las posiciones por piloto ya guardadas, la
   sesión de clasificación se puede ver "en crudo" (dónde terminó cada uno)
   o con una línea de tiempo que mueva los autos. Hoy es la primera.

### Prioridad media

3. Ampliar el mapa de coordenadas de `backend/core/weather.py` al resto de
   circuitos de la temporada. Hoy solo esta Austin (circuit_key 9); para
   cualquier otro trazado **no hay prevision**, a proposito.
4. Medir el tamaño del snapshot histórico completo: `location` son 403.062
   muestras GPS. Se resolvió guardando **una fila por piloto** (la última),
   pero queda medir el tiempo de descarga del endpoint completo.
5. Documentar en `docs/providers.md` la Incorporación de una API nueva como
   guía práctica (ya está el esqueleto del adaptador).
6. **Rotar los secretos que quedaron a la vista**: el token de la API de
   Coolify y la contraseña del sitio se imprimieron en el chat durante el
   despliegue. El token se regenera en Coolify; la contraseña se cambia en las
   variables de entorno de la aplicación.
7. **Evolución de posiciones por vuelta**: OpenF1 tiene `/position` (70 filas
   en la quali de Austin), con lo que se puede ver el cambio de posición de
   cada piloto vuelta a vuelta. Queda fuera de esta entrega.

### Resuelto en esta sesion

- `/api/sessions/historical/<key>/` **vuelve a funcionar** (ver seccion 7).
  Primera consulta 10 s (snapshot completo desde OpenF1); segunda 0.026 s
  (cache en base de datos).
- La columna de neumático del historico muestra el compuesto real.
- "Ultimo dato" en modo historico muestra la edad del snapshot, no la del
  proveedor en vivo.
- **LIVE verificado**: la clasificación de la quali de Austin 2026 se movió de
  verdad durante la sesión (22 entradas, mejores vueltas reales, Q1/Q2/Q3
  completándose, vueltas contadas).
- **Contador de fin de sesión** en la clasificación ("FINALIZA EN hh:mm:ss").
- **Columna de GAP** con los valores reales que publica la F1, con la etiqueta
  del segmento (Q1/Q2/Q3) del que salen.
- **Columna MEJOR VUELTA** con el mejor tiempo real de cada piloto (incluido
  el knockout de Q3, donde el feed vacía el valor global).
- **Neumáticos**: los 22 pilotos con compuesto y edad de stint.
- **Mapa del circuito** con la posición real de cada piloto en el replay
  histórico (última posición conocida de cada uno).
- **Mensaje honesto** en el mapa cuando la fuente no entrega coordenadas.

### Fuera de alcance (decidido)

- Publicación a Internet, Docker, MySQL/Redis/Channels: **preparados en la
  arquitectura, no instalados**.
- Suscripción de OpenF1 para live.
- Distribución de los datos del feed.

---

## 13. Despliegue en contenedor (Coolify)

### Un solo contenedor, cuatro procesos

La app son cuatro cosas que tienen que vivir juntas: el SPA, la API, el
proceso de ingesta y el proveedor de cronometraje. En Coolify lo más simple
es **una sola aplicación** (build pack `Dockerfile`) con un supervisor adentro:

| Proceso | Qué hace | Escucha en |
|---|---|---|
| `nginx` | sirve el SPA y hace proxy de `/api` | `0.0.0.0:80` (el único puerto) |
| `backend` | Django con gunicorn | `127.0.0.1:8000` |
| `ingest` | `manage.py ingest_live --interval 3` | — |
| `live` | proveedor Node de cronometraje | `127.0.0.1:3000` |

Lo único que sale a la red es el puerto 80 de nginx: el proveedor del feed de
la F1 y la API siguen en loopback, igual que en la instalación local. El SPA
y la API comparten origen, así que el navegador **no** necesita CORS ni
credenciales de terceros.

### OJO: el build pack tiene que ser `Dockerfile`

Con **Nixpacks**, Coolify genera su propio Dockerfile e ignora el del
repositorio: el contenedor levantaría sin el proveedor de cronometraje. En
esta instancia hay una app (`vogel-gestion-servicios-production-backend`) con
nixpacks, así que el aviso no es teórico.

### Archivos

| Archivo | Qué hace |
|---|---|
| `Dockerfile` | Build multi-etapa: frontend (node) + dependencias del proveedor (node) + runtime (Python 3.12 + Node 22 + nginx + supervisor) |
| `deploy/nginx.conf` | Configuración principal de nginx |
| `deploy/nginx-site.conf` | El vhost: SPA + proxy de `/api` + comprobación de sesión con `auth_request` |
| `deploy/supervisord.conf` | Los cuatro procesos |
| `deploy/entrypoint.sh` | Migraciones y arranque (ya no genera el `.htpasswd`: el login es de la app) |
| `.dockerignore` | Excluye `.run/` (donde vive el token de Coolify), `.env`, `node_modules` y la base local |

### Variables de entorno en Coolify

| Variable | Valor | Por qué |
|---|---|---|
| `DJANGO_SECRET_KEY` | (generado) | Django lo exige fuera de desarrollo |
| `DJANGO_DB_PATH` | `/data/db.sqlite3` | La base vive en el volumen persistente, no en el código |
| `APP_DEBUG` | `false` | |
| `ENABLE_LAN_ACCESS` | `true` | Suma el dominio a los hosts permitidos |
| `LAN_ALLOWED_HOSTS` | `<dominio>` | `ALLOWED_HOSTS` quedan acotados al dominio |
| `LAN_ALLOWED_ORIGINS` | `https://<dominio>` | Orígenes CORS |
| `TRUST_PROXY_SSL` | `true` | Detrás del proxy que termina TLS |
| `F1_LIVETIMING_URL` | `http://127.0.0.1:3000` | El proveedor, dentro del contenedor |
| `RACE_CENTER_USER` / `RACE_CENTER_PASSWORD` | (definidos) | Con ellos la API pide sesión: el login es de la app (§15). Si están vacíos, el sitio se sirve **sin** protección |
| `RACE_CENTER_SESSION_DAYS` | `30` | Duración de la cookie de sesión |
| `OPENF1_API_KEY` | (vacío) | El live de OpenF1 es de pago |

El dominio: `https://race-center.186-5-245-12.sslip.io`. Comprobado que
**no hay wildcard DNS** para `vogelconsultoria.com.ar` (cada subdominio tiene
su registro A), pero `sslip.io` sí resuelve nombres con el IP embebido, y
esta instancia de Coolify **ya emite certificados Let's Encrypt** para
dominios `sslip.io` (probado en `freellmapi`).

### Verificación local del contenedor (antes de subir nada)

```
docker build -t race-center:local .
docker run -d --name race-center-test -p 8080:80 -v race-center-data:/data \
  -e DJANGO_SECRET_KEY=... -e RACE_CENTER_USER=piloto -e RACE_CENTER_PASSWORD=... \
  race-center:local
```

Resultado: los cuatro procesos `RUNNING`, `GET /` → **401** sin credenciales y
**200** con ellas (SPA y assets), `/api/health/` con datos reales detrás del
proxy de nginx, y la base en `/data` (con sus archivos WAL).

### Bugs del contenedor (encontrados probando, no leyendo)

| # | Bug | Causa | Cómo se resolvió |
|---|---|---|---|
| 31 | El contenedor no arrancaba (exit 2) | `htpasswd -q` no existe en Debian (solo tiene `-c`, `-b`, `-i`...) | La contraseña va por stdin: `printf ... \| htpasswd -B -c -i` (así tampoco queda en la lista de procesos) |
| 32 | nginx no arrancaba: `"types" directive is not allowed here in /etc/nginx/mime.types` | El `include mime.types` estaba en el nivel principal de nginx | Se movió dentro del bloque `http {}` |
| 33 | 40 s perdidos en cada arranque | El entrypoint esperaba a que el proveedor respondiera en el puerto 3000, pero **ese proceso lo arranca supervisor, después** | El entrypoint no espera: la ingesta ya sabe esperar (estado `WAITING` hasta que el proveedor conecta) |

### La API de Coolify 4.5: cinco cosas que no se deducen

Todo esto se descubrió probando y leyendo los errores de validación (que son
útiles: enumeran los campos no permitidos).

| Qué | Cómo es en realidad |
|---|---|
| Crear la aplicación | `POST /api/v1/applications` **no existe** (404). El que funciona es `POST /api/v1/applications/public` (repo público) |
| El repositorio | En `/public`, `git_repository` va como **texto** (`"https://github.com/oscarvogel/f1-race-control"`), no como objeto. Con el objeto, la validación pasa y después la API revienta con **500** |
| Los dominios | El campo es `domains` (o `fqdn`); `fqdn` en el alta da error: *"Use the domains field to set application URLs"* |
| El servidor | `server_uuid` (no `server_id`), y además `project_uuid` y `environment_name` son obligatorios |
| Las variables | El payload mínimo es `{"key": "...", "value": "..."}`. `is_build_time`, `is_required`, `is_shared`... **no están permitidos** en el alta (sí en el PATCH) |
| El volumen | `mounts` **no se acepta** en el PATCH de la app. El endpoint correcto es `POST /api/v1/applications/{uuid}/storages` con `{"name": ..., "mount_path": "/data", "type": "persistent"}` |
| El health check | Con `health_check_host: localhost`, Traefik no enruta la comprobación (responde 404) y la app queda `exited:unhealthy`. Con el **dominio** como host, funciona |

Los errores de validación de la API son la herramienta: cada 422 dice
exactamente qué campo sobra o falta.

### Lo que quedó desplegado

- **URL**: <https://race-center.186-5-245-12.sslip.io> (certificado Let's
  Encrypt válido; el proxy de Coolify ya emitía certificados para dominios
  `sslip.io` en esta instancia).
- **Protección**: login propio de la aplicación (§15). La API exige una
  cookie de sesión válida; sin ella responde **401**. El diálogo nativo del
  navegador (HTTP basic) se eliminó: se veía fuera del tema de la app.
- **Datos**: 11 variables de entorno (secrets en Coolify, nunca en el repo).
- **Volumen**: `/data` persistente para el SQLite, para que el histórico y el
  catálogo no se pierdan al redesplegar.
- **Verificado**: los cuatro procesos `RUNNING` en el servidor, el proveedor
  conectado al feed de la F1 desde el contenedor, la ingesta escribiendo
  snapshots (22 pilotos) y el dashboard sirviendo la clasificación final de
  la quali con gaps y neumáticos.

> El repositorio de GitHub es **público**: el código se ve, los datos no
> (el feed de la F1 no se redistribuye y el sitio está con contraseña).

### Lo que NO se puede pedir por API

El **volumen persistente** sí se pudo crear por API (endpoint `storages`), pero
en general hay cosas que en Coolify solo se tocan desde la UI. Si alguna vez
hace falta, la vía es: iniciar sesión en la interfaz y cargar el campo desde
la sesión del navegador (el token de API no alcanza para eso).

---

## 14. Acceso al sitio: login propio de la aplicación

### El problema

El sitio estaba protegido con HTTP basic de nginx. Funcionaba, pero al abrirlo
el navegador sacaba **su propio diálogo**: en inglés, con los controles del
navegador, fuera del tema de la app y sin forma de cerrar sesión. Para una
aplicación que tiene su propio diseño, era un remiendo visible.

### La solución

El login pasó a ser de la aplicación y la protección siguió estando en el
borde:

| Capa | Qué hace |
|---|---|
| `frontend/src/components/LoginScreen.vue` | La pantalla de acceso: panel oscuro, en español, con mostrar/ocultar contraseña y botón "Salir" en la cabecera |
| `backend/core/auth.py` | Verifica la credencial contra el entorno, firma la cookie de sesión y expone `/api/auth/{login,logout,session,check}` |
| `deploy/nginx-site.conf` | `auth_request` contra `/api/auth/check/`: antes de dejar pasar una petición a la API, nginx pregunta si la sesión es válida |
| `core.auth.SessionAuthMiddleware` | Defensa en profundidad: el backend tampoco confía en que el filtro del borde esté bien puesto |

El detalle que hace que desaparezca el diálogo del navegador: **el 401 no
lleva `WWW-Authenticate`**. Si lo llevara, el navegador abriría su ventana
nativa; sin ese encabezado, el 401 viaja al JavaScript de la app, que pinta su
propia pantalla de acceso.

Con esto el sitio se ve como el resto de la aplicación, con HTTPS, y la API
sigue sin quedar expuesta: sin cookie válida, `/api/...` responde 401.

### Details que importan

- **La credencial no se guarda**: se compara en tiempo constante
  (`secrets.compare_digest`) con `RACE_CENTER_USER` / `RACE_CENTER_PASSWORD`.
  No hay tabla de usuarios en la base.
- **La sesión es una cookie firmada** con el `SECRET_KEY` de Django, con
  vencimiento (30 días por defecto), `HttpOnly` y `SameSite=Lax`. El
  atributo `Secure` se pone solo si la petición llegó por HTTPS: puesto
  siempre, entrar por HTTP "funciona" pero la API responde 401 después.
- **Freno de fuerza bruta**: 8 intentos fallidos por IP en 5 minutos; a partir
  de ahí, 429.
- **Sin credenciales configuradas** (desarrollo local) no se pide nada: la
  API queda abierta, igual que antes.

### Verificación

Con el contenedor local (`bash .run/docker_test.sh`):

- `GET /` → **200** (el SPA se sirve; el que decide es la cookie).
- `GET /api/health/` sin cookie → **401**, y **sin** `WWW-Authenticate` (se
  comprueba en el propio script: es el requisito que evita el diálogo).
- Login con contraseña incorrecta → **401**.
- Login correcto → cookie de sesión; con ella, la API responde **200**.
- `/api/ping/` (health check de Coolify) → **200** sin cookie.
- Logout → la cookie se borra y la API vuelve a pedir sesión.

---

## 15. Comparaciones: análisis por sectores y campeonato

### Qué se construyó y por qué

La pregunta era qué se puede comparar **con datos reales** una vez terminada
la sesión. La respuesta corta: el feed en vivo no alcanza para comparar
vueltas, pero OpenF1 sí.

| Panel | Qué muestra | De dónde sale |
|---|---|---|
| **Análisis** | La mejor vuelta de cada piloto con sus tres sectores, el Δ contra el más rápido y el Δ **sector por sector** contra el piloto que se elija; además, el Δ de la vuelta contra otra sesión (por ejemplo, FP3) | OpenF1 `/laps` + `/stints` |
| **Campeonato** | La tabla de pilotos y de constructores de la temporada, con puntos, victorias y rezago | Jolpica `/driverstandings.json` y `/constructorstandings.json` |

### Por qué el feed en vivo no sirve para el análisis

El feed publica `Sectors` de la **última vuelta** de cada piloto, y esos
sectores **no suman** su mejor vuelta. En OpenF1, los sectores de la mejor
vuelta sí suman **exactamente** el tiempo de esa vuelta (comprobado: ANTONELLI
25.310 + 37.297 + 31.428 = 94.035 = 1:34.035). Sin esa propiedad, comparar
sectores entre pilotos no significa nada.

### Decisiones de alcance

- **El delta se calcula en el backend**, no en el navegador: el frontend
  elige el piloto de referencia y recibe los deltas ya calculados. Cambiar la
  referencia no vuelve a golpear OpenF1 (los datos crudos están cacheados).
- **Los combos de la sesión y del piloto son con búsqueda** (`SearchSelect`):
  se escribe, se filtra y se elige una opción real. Si el texto no coincide
  con ninguna opción, no se guarda nada.
- **El campeonato se etiqueta honestamente**: "Clasificación tras la ronda 17:
  la ronda 18 (Austin) todavía no suma puntos hasta que se disputa la
  carrera". Austin es la ronda 18 de 2026 y no hay puntos de ella hasta el
  domingo.
- **Lo que NO se construyó** (y por qué): el análisis de estrategia de
  neumáticos en la clasificación (una sola parada por piloto, no hay nada que
  comparar) y la evolución de posiciones por vuelta (los datos están en
  OpenF1 `/position`, queda como opción).

### Endpoints

```
GET /api/analysis/sectors/<session_key>/?reference=<piloto>&compare=<sesion>
GET /api/championship/?season=<año>
```

Los datos crudos de cada sesión (mejor vuelta por piloto + ficha de pilotos) y
el campeonato se cachean **en memoria y en la base** (una sesión terminada no
cambia). La clave de la cache lleva una versión (`v2`): al cambiar el formato
del payload, la base no sigue sirviendo el viejo.

---

## 16. Cómo seguir

```bash
cd /mnt/c/Programacion/proyectos/actives/f1-race-center

./scripts/start-dev.sh   # proveedor live + ingesta + API + frontend
./scripts/doctor.sh      # diagnóstico con datos concretos
./scripts/test.sh        # pytest + build del frontend + smoke test
./scripts/stop-dev.sh    # detener solo los procesos de Race Center
```

Evidencia de la sesión en curso:

```bash
tail -f .run/logs/live-evidence.log
```

Ver el detalle del diagnóstico del canal y del límite de tasa de OpenF1 en
`docs/live-diagnostics.md`.
