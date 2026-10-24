# Proveedores de datos

Race Center habla con tres fuentes a través de adaptadores. Este documento
registra **qué se comprobó realmente**, con qué condiciones y con qué
limitaciones.

---

## 1. `FreeLiveTimingProvider` — cronometraje en vivo

### Qué es

El servicio Node local [`julesr0y/f1-livetiming-api`](https://github.com/julesr0y/f1-livetiming-api)
recibe el flujo SignalR de `livetiming.formula1.com` y mantiene el estado en
memoria, exponiéndolo por HTTP local.

- **Licencia:** Apache-2.0 (`LICENSE`).
- **NOTICE:** `ROY Jules (julesr0y) - F1 LiveTiming API / Copyright 2026`, con
  la aclaración de que el proyecto no está asociado a la Formula 1.
- Se usa como **servicio aislado**, no se copió su código al backend.
- Su lógica no se modificó. Solo se aplicó el parche de seguridad indicado
  abajo.

### Por qué funciona

El feed SignalR de cronometraje es un protocolo delta: el servidor envía solo
las propiedades modificadas. El servicio mantiene un *deep merge* en RAM y
sirve los endpoints desde memoria, sin volver a llamar a los servidores de la
F1 en cada lectura.

### Endpoints verificados (24/10/2026)

Todos respondieron `HTTP 200` con datos reales de Austin 2026:

| Endpoint | Contenido | Observación |
|---|---|---|
| `/api/status` | estado SignalR, `lastMessageAt`, uptime | `isConnected`, `lastMessageAt` |
| `/api/session` | GP, circuito, tipo de sesión, ID, estado | clave `Key` = ID real de sesión |
| `/api/standings` | clasificación ordenada | incluye `TimingData` completo |
| `/api/leaderboard` | clasificación + estrategia de neumáticos | incluye `TimingAppData` |
| `/api/drivers` | plantilla de pilotos con color de escudería | `TeamColour` en hex |
| `/api/tyres` | stints por piloto | alias `/api/stints` |
| `/api/weather` | clima del circuito | |
| `/api/race-control` | mensajes FIA | alias `/api/flags` |
| `/api/lap-count` | contador de vueltas | **vacío fuera de sesión activa** |
| `/api/radio` | radio de equipo | |

### Detalles del formato que condicionan el normalizador

- `Sectors` llega como **lista** de 3 elementos (índice 0 = S1), no como
  diccionario.
- `BestLapTimes` llega como diccionario con claves `"0"`, `"1"`, `"2"`
  → Q1, Q2, Q3. Solo aparece cuando la sesión es de clasificación.
- El marcador `_kf` aparece en `Leaderboard` y `Lines`. **No es un piloto** y
  se descarta.
- En clasificación los gaps vienen como `TimeDiffToFastest` y
  `TimeDiffToPositionAhead` (cadenas). En carrera se usan `GapToLeader` e
  `IntervalToPositionAhead` (objetos con `Value`).
- El líder no tiene gap: el feed manda `""`. Se normaliza a `None`, **nunca**
  a `0.000`, porque un gap de cero es un dato real.
- `Retired`, `InPit`, `Stopped` llegan como booleanos; `New` de los
  neumáticos llega como cadena `"true"`/`"false"`.
- **En clasificación los gaps vienen dentro de `Stats`**, no en el nivel
  superior. `Stats` llega como **dict** `{"0": {...}, "1": {...}}` o como
  **lista** de 3, y el valor útil **no siempre está en el índice 0**: un piloto
  que hizo su tiempo en Q2 lo tiene en el índice 1. Hay que recorrer todos los
  segmentos y quedarse con el último que tenga dato (el más reciente que
  publicó F1 para ese piloto).
- **Durante el knockout (Q3) el feed vacía `BestLapTime`**: pasa a
  `{"Value": "", "Lap": N, "_deleted": ["Lap"]}` porque ese campo sigue el
  segmento en curso, no la sesión. La mejor vuelta del piloto se calcula
  comparando ese valor con los mejores por segmento (`BestLapTimes`).
- **Para un piloto en pista**, el feed escribe el delta en vivo en el primer
  slot de `Stats` aunque su segmento actual sea el segundo. Por eso la
  etiqueta de segmento (Q1/Q2/Q3) de un gap solo se muestra si el piloto tiene
  una vuelta completada en ese segmento.

### Qué canales publica el feed (sondeado el 24/10/2026)

La suscripción incluye `CarData`, `Positions` y `TrackStatus` (añadidos con el
parche de ampliación). Lo que se comprobó **contra el feed real**, con la
clasificación de Austin 2026 en curso:

| Canal | ¿Llega? | Nota |
|---|---|---|
| `TimingData`, `TimingDataF1`, `TimingAppData` | sí | clasificación y stints |
| `WeatherData`, `TimingStats` | sí | |
| `DriverList`, `SessionInfo`, `RaceControlMessages`, `TeamRadio` | en el snapshot inicial | |
| `TrackStatus` | **sí** | `{"Status":"1","Message":"AllClear"}` |
| `ExtrapolatedClock`, `AudioStreams` | en el snapshot inicial | |
| `CarData`, `Positions`, `Position`, `CarStatus`, `Clock`, `LapCount` | **no** | suscripción válida, el feed no publica nada |

**Conclusión:** la suscripción es correcta (el propio `TrackStatus`, añadido por
el mismo parche, sí llega) pero **durante la clasificación el feed no publica
coordenadas**. No es un fallo del código: es lo que hace la fuente. Por eso el
mapa del circuito no puede mostrar los autos en vivo durante la quali, y la
interfaz lo dice en pantalla en lugar de dejar el panel vacío.

La forma de comprobarlo (sonda que replica el handshake real del cliente, en
`.run/probe_feed.js`):

```bash
cd /mnt/c/Programacion/proyectos/actives/f1-race-center
NODE_PATH=services/live-timing/node_modules node .run/probe_feed.js
```

> La primera versión de la sonda estaba rota: tomaba `frame.target` como
> nombre del canal, pero en SignalR Core el `target` siempre es `"feed"` y el
> canal va en `frame.arguments[0]`. Con ese error hasta el grupo de control
> parecía "sin mensajes" y la conclusión sobre `Positions` era falsa.

### Parche de seguridad aplicado

El upstream hace `app.listen(PORT)` **sin host**, o sea que escucha en
`0.0.0.0` y queda alcanzable desde la LAN. La especificación pide corregirlo.
El parche está en `scripts/patch_livetiming_provider.py` y aplica dos cambios
mínimos, reversibles y documentados:

```js
// [Race Center patch] Upstream calls app.listen(PORT) with no host, which binds 0.0.0.0.
const HOST = process.env.HOST || '127.0.0.1';
...
const server = app.listen(PORT, HOST, () => { ... });
```

```js
// [Race Center patch] Restrict CORS to loopback origins instead of cors().
const CORS_ORIGINS = (process.env.CORS_ORIGINS || 'http://127.0.0.1:5174,...')
```

Con `HOST=0.0.0.0` se recupera el comportamiento original.

### Limitaciones

- **Sin coordenadas GPS durante la clasificación.** Los canales `CarData` y
  `Positions` están suscrito y el feed acepta la suscripción, pero **no
  publica mensajes de esos canales** mientras la sesión es de clasificación
  (verificado el 24/10/2026 con la quali de Austin 2026 en curso). El mapa del
  circuito, entonces, no muestra autos en vivo: lo dice en pantalla. En
  carrera hay que volver a comprobarlo (queda como pendiente en la bitácora).
- **Telemetría de vehículo** (velocidad, RPM, marcha, acelerador, freno, DRS):
  llega en el mismo canal `CarData`, con la misma limitación anterior.
- Para histórico sí hay `car_data` y `location` en OpenF1: el replay guarda
  **una fila por piloto** (la última posición conocida), no las 403.062
  muestras GPS de la sesión.
- **Sin histórico de vueltas por piloto** en vivo: `/api/laps` es el contador
  de vueltas de la sesión, no el listado de vueltas. `get_laps()` del
  adaptador live no está soportado.
- El servicio **no se puede mantener conectado indefinidamente** con
  garantía: la reconexión la gestiona el propio servicio (watchdog de 20 s y
  reintento a los 5 s).
- La coloración del equipo viene del feed (`TeamColour`), no de una tabla
  propia.

---

## 2. `OpenF1Provider` — histórico

Documentación: <https://openf1.org/docs/>

- Histórico **gratis desde 2023**, sin autenticación.
- El acceso **en vivo requiere suscripción pagada**. Por eso
  `OPENF1_LIVE_ENABLED=false` por defecto y `live_enabled` es `False`:
  el proveedor no se usa nunca para clasificación en vivo.

### Comportamiento real observado (24/10/2026)

| Consulta | Resultado |
|---|---|
| `/v1/sessions?year=2026` | `200`, datos de 2026 |
| `/v1/sessions?meeting_key=1297` | `200`, sesiones de Austin 2026 |
| `/v1/sessions?session_key=9159` | `200` |
| `/v1/meetings?meeting_key=1297` | `200` |
| `/v1/drivers?session_key=…` | `200`, 22 pilotos |
| `/v1/laps?session_key=…` | `200` (423–589 vueltas) |
| `/v1/session_result?session_key=…` | `200` |
| `/v1/stints`, `/v1/weather`, `/v1/race_control`, `/v1/pit`, `/v1/car_data`, `/v1/location` | `200` |
| `/v1/intervals`, `/v1/overtakes`, `/v1/starting_grid`, `/v1/championship_*` | `404` (sin datos para esa sesión) |

### Trampas de la API

1. **Los operadores de filtro van crudos.** `?date_start>=2026-10-20` funciona;
   codificado como `%3E%3D` **no** filtra igual.
2. **Un filtro por atributo inexistente devuelve `404`, no error.** Por ejemplo
   `&limit=1` (que no es un atributo de `sessions`) responde
   `404 {"detail": "No results found."}`. Por eso el adaptador trata `404` como
   "sin resultados" y no como "endpoint caído".
3. `sessions` no tiene `year` para 2025/2026 con `limit`, pero sí sin `limit`.
4. `location` puede devolver `x=0, y=0, z=0` cuando el feed no trae GPS real.
5. **Limite de tasa por IP.** Una rafaga corta agota la cuota y la respuesta es
   `429` con la cabecera `retry-after: 60`. Medido: 2 s entre peticiones, 15/15
   correctos; 1 s, 20/20; 0.5 s, 25/25. El adaptador respeta ese `retry-after`,
   separa las peticiones 1 s y **no emite ninguna durante el cooldown**.
6. **Durante una sesion de F1 en curso se bloquea TODO**, incluidas las
   sesiones ya terminadas. Verificado el 24/10/2026 a las 20:44 UTC, al
   arrancar la clasificacion:

   ```
   {"detail": "Live F1 session in progress. Global API access (including past
   sessions) is restricted to authenticated users until the session ends.
   Get an API key here: https://buy.stripe.com/..."}
   ```

   Es un `401`, no un `429`. El efecto: durante la carrera no se puede
   consultar ni el catalogo ni una sesion que no se haya descargado antes.
   **Como lo resuelve Race Center:**

   - El catalogo de sesiones se guarda en la base (`scope = "catalog"`) y se
     usa como respaldo, marcado como `stale`.
   - El calendario sale de **Jolpica**, que no se bloquea.
   - Las claves de sesion se recuperan de la tabla `Session`, o sea de las que
     ya se habian descargado.
   - Los snapshots historicos ya descargados se sirven desde la base sin
     volver a preguntar.

   **Lo que queda fuera:** una sesion historica que nunca se haya descargado no
   es consultable durante una sesion en vivo sin clave de OpenF1
   (`OPENF1_API_KEY`).

### Austin 2026 en OpenF1

`meeting_key = 1297` — United States Grand Prix, Circuit of the Americas.

| session_key | Tipo | Inicio (UTC) |
|---|---|---|
| 11389 | Practice 1 | 2026-10-23 17:30 |
| 11390 | Practice 2 | 2026-10-23 21:00 |
| 11391 | Practice 3 | 2026-10-24 17:30 |
| **11392** | **Qualifying** | **2026-10-24 21:00** |
| 11396 | Race | 2026-10-25 20:00 |

21:00 UTC = **18:00 hora de Argentina**. Al momento de la instalación,
OpenF1 ya tenía `drivers` de la clasificación (la plantilla se conoce antes de
la sesión) pero **no** las vueltas ni el resultado, porque la sesión todavía
no se había corrido. Es el comportamiento correcto, no un fallo.

---

## 3. `JolpicaProvider` — metadatos

Documentación: <https://api.jolpi.ca/docs/>

Base: `https://api.jolpi.ca/ergast/f1` (verificada en pie: responde `200`).

Uso: calendario de la temporada, información de cada GP (circuito, país, fecha
de clasificación) y plantillas de pilotos.

**No es fuente de telemetría ni de cronometraje.** Sus capacidades de `live`,
`timing`, `laps`, `weather`, `race_control` y `telemetry` son `False`, así que
el `ProviderManager` nunca lo elige para datos en vivo.

Verificado el calendario 2026: la ronda 18 es el United States Grand Prix en
Austin, con clasificación el **2026-10-24 a las 21:00:00Z**.

### Papel actual: calendario de respaldo

Cuando OpenF1 bloquea el acceso (ver la limitacion 6 de la seccion 2), el
calendario de sesiones se construye desde Jolpica, que publica la hora de
inicio de cada sesion del fin de semana:

| Campo de la ronda | Ejemplo (ronda 18 de 2026) |
|---|---|
| `FirstPractice` | 2026-10-23 17:30:00Z |
| `SecondPractice` | 2026-10-23 21:00:00Z |
| `ThirdPractice` | 2026-10-24 17:30:00Z |
| `Qualifying` | 2026-10-24 21:00:00Z |
| `date` + `time` (carrera) | 2026-10-25 20:00:00Z |

Eso es lo que permite que la cuenta regresiva a la proxima sesion siga
funcionando durante la carrera. Jolpica no publica el fin de cada sesion: ese
campo queda vacio en vez de estimarse.

---

## Cómo elige el `ProviderManager`

1. Se determina el **ámbito semántico** de la capacidad pedida
   (`live`, `historical` o `metadata`).
2. Se filtran los proveedores que **declaran** esa capacidad.
3. Gana el proveedor **configurado** para ese ámbito; si no hay ninguno, gana
   el que esté conectado, con el dato más fresco y menor latencia.

**Regla dura:** un pedido `live` nunca se resuelve con un proveedor
histórico. Si la fuente en vivo no está, el resultado lo dice
(`data_state: OFFLINE` o `ERROR`) en lugar de servir un histórico disfrazado
de directo. Está cubierto por un test propio
(`test_no_hay_fallback_de_live_a_historico`).

---

## Incorporar una API nueva

1. **Heredá de `TimingProvider`** en `backend/providers/`. La clase base
   define el contrato: `connect`, `disconnect`, `health_check`,
   `get_capabilities` y los `get_*`.

2. **Declará las capacidades reales** en `get_capabilities()`. Lo que el
   proveedor no puede dar va en `False`. No declare una capacidad y después
   devuelva un fixture.

3. **Normalizá a los dataclasses de `providers/base.py`.** Nunca expongas el
   formato crudo de la API: el frontend consume el modelo normalizado. Cada
   entidad lleva `provider_id` y `source_timestamp`.

4. **Preservá el "sin dato".** `None` significa "no lo sé"; `0` significa
   "cero de verdad". `parse_lap_time`, `to_float` y `to_int` ya lo hacen.

5. **Levantá `UnsupportedCapability`** en las capacidades que no soportás.

6. **Registralo** en `core/ingest.py::build_manager()` y agregá el
   `provider_id` a las variables de entorno (`.env.example`).

7. **Escribí tests** en `backend/core/tests/` con fixtures sintéticos. Los
   fixtures no se usan fuera de los tests.

8. **Documentalo** en este archivo: qué aporta, qué no, y con qué
   condiciones.
