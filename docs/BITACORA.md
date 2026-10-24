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

**77 pruebas en verde.** Reparto:

| Archivo | Qué cubre |
|---|---|
| `test_normalization.py` | Formato real del feed: sectores, gaps,ploreads, `None` vs `0` |
| `test_manager.py` | Selección por semántica, prioridad, fallback |
| `test_api.py` | Endpoints de la API interna |
| `test_persistence.py` | Modelos, deduplicación, fingerprint, ámbito del snapshot |
| `test_rate_limit.py` | Cadencia de health check, `retry-after`, cooldown, degradación |
| `test_weather.py` | Previsión: coordenadas, códigos de tiempo, ventana de sesión |

Las tres reglas duras tienen prueba propia: **un pedido live no se resuelve
con un proveedor histórico**, **ausencia ≠ cero**, y **un snapshot incompleto
no es un fallo**.

---

## 12. Pendientes

### Prioridad alta

1. **Verificar el LIVE de la clasificación** (GP US 2026, `session_key 11392`).
   La clasificación arranca **21:00 UTC = 18:00 Argentina**. Hasta entonces
   el veredicto honesto es: feed conectado, datos reales confirmados de
   sesión finalizada, `LIVE` **no verificado**. Grabador de evidencia en
   `.run/logs/live-evidence.log`.
2. **Confirmar que `CarData` entrega posiciones** durante una sesión activa.
   El canal está suscrito y el feed lo acepta, pero `positions` llega vacío
   porque solo fluye con sesión en curso. De esto depende que el mapa del
   circuito muestre los autos en movimiento.

### Prioridad media

3. Ampliar el mapa de coordenadas de `backend/core/weather.py` al resto de
   circuitos de la temporada. Hoy solo esta Austin (circuit_key 9); para
   cualquier otro trazado **no hay prevision**, a proposito.
4. Medir el tamaño del snapshot histórico completo: `location` son 403.062
   muestras GPS; decidir si el replay necesita posiciones o si conviene
   quedarse con un subconjunto.
5. Documentar en `docs/providers.md` la Incorporación de una API nueva como
   guía práctica (ya está el esqueleto del adaptador).

### Resuelto en esta sesion

- `/api/sessions/historical/<key>/` **vuelve a funcionar** (ver seccion 7).
  Primera consulta 10 s (snapshot completo desde OpenF1); segunda 0.026 s
  (cache en base de datos).
- La columna de neumático del historico muestra el compuesto real.
- "Ultimo dato" en modo historico muestra la edad del snapshot, no la del
  proveedor en vivo.

### Fuera de alcance (decidido)

- Publicación a Internet, Docker, MySQL/Redis/Channels: **preparados en la
  arquitectura, no instalados**.
- Suscripción de OpenF1 para live.
- Distribución de los datos del feed.

---

## 13. Cómo seguir

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
