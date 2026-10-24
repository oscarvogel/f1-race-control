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
const CORS_ORIGINS = (process.env.CORS_ORIGINS || 'http://127.0.0.1:5173,...')
```

Con `HOST=0.0.0.0` se recupera el comportamiento original.

### Limitaciones

- **Sin telemetría de vehículo** (velocidad, RPM, marcha, acelerador, freno,
  DRS) y **sin coordenadas GPS**. El feed de cronometraje no las trae.
  `get_telemetry()` y `get_positions()` lanzan `UnsupportedCapability` en vez
  de inventar datos. Para histórico sí hay `car_data` y `location` en
  OpenF1.
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
