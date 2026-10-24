# Arquitectura

Race Center es una aplicación **personal** de tres piezas que corren todas en
la misma máquina (WSL Ubuntu) y se comunican solo por loopback.

```
┌───────────────────────── WSL Ubuntu ─────────────────────────────┐
│                                                                  │
│  livetiming.formula1.com  (SignalR, internet)                   │
│          │  WebSocket                                           │
│          ▼                                                       │
│  ┌────────────────────────┐                                      │
│  │ services/live-timing   │  Express + ws                       │
│  │ (Apache-2.0, upstream) │  estado en RAM                      │
│  └───────────┬────────────┘                                      │
│              │ HTTP 127.0.0.1:3000                              │
│              ▼                                                    │
│  ┌────────────────────────┐      ┌────────────────────────────┐  │
│  │ backend/providers      │─────►│ backend/core/ingest.py     │  │
│  │  base / manager        │      │  proceso unico de ingesta  │  │
│  │  free_live / openf1    │      └──────────────┬─────────────┘  │
│  │  jolpica               │                     │ escribe         │
│  └────────────────────────┘                     ▼                │
│                                    ┌───────────────────────────┐ │
│                                    │ SQLite (SessionSnapshot)   │ │
│                                    │   cache compartida         │ │
│                                    └──────────────┬────────────┘ │
│                                                   │ lee          │
│                                    ┌──────────────▼────────────┐ │
│                                    │ API interna Django/DRF    │ │
│                                    │ 127.0.0.1:8000/api/       │ │
│                                    └──────────────┬────────────┘ │
│                                                   │ /api proxy  │
│                                    ┌──────────────▼────────────┐ │
│                                    │ frontend Vue 3 (Vite)     │ │
│                                    │ 127.0.0.1:5173            │ │
│                                    └───────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

## Decisiones y por qué

### 1. Un solo proceso de ingesta

`manage.py ingest_live` es el **único** que llama a los proveedores. El
frontend nunca genera tráfico hacia las APIs externas ni hacia el servicio
Node. Consecuencias:

- Abrir dos navegadores (o tres) no multiplica las peticiones al feed.
- Los reintentos, el backoff y la reconexión están en un solo lugar.
- El diagnóstico de "llegó algo nuevo" no depende de cuántos navegadores haya.

El frontend consulta nuestra API cada 2 s (`usePolling`), que es una lectura
de SQLite en local: barata.

### 2. La caché compartida es la base de datos

El proceso de ingesta y el proceso de la API son **procesos distintos**. Por
eso la caché compartida no puede ser memoria: es la tabla
`core_sessionsnapshot`.

Cada snapshot lleva una **huella SHA-256** de su contenido normalizado. Si la
huella no cambió, no se escribe una fila nueva (constraint única
`uniq_snapshot_fingerprint`). Así se cumple "no guardar cada snapshot completo
como una fila nueva si no existen cambios".

### 3. Todo dato normalizado lleva su procedencia

Cada entidad (`Session`, `Driver`, `TimingEntry`, ...) tiene `provider_id` y
`source_timestamp`. El frontend muestra el proveedor activo y la edad del
último dato. Nunca hay una cifra en pantalla sin saber de dónde salió.

### 4. Ausencia de dato ≠ cero

`None` significa "no lo sé". `0` significa "cero de verdad". Los helpers
`parse_lap_time`, `to_float` y `to_int` preservan esa distinción, y el
normalizador convierte el gap vacío del líder en `None`, no en `0.000`.

### 5. Sin fallback silencioso de LIVE a HISTORICAL

El `ProviderManager` filtra los proveedores **por ámbito semántico** antes de
elegir. Un pedido `live` solo puede satisfied con un proveedor que declare
`live=True`. Si no hay ninguno, el resultado lo dice (`data_state: OFFLINE` o
`ERROR`) en vez de servir un histórico. Está cubierto por
`test_no_hay_fallback_de_live_a_historico`.

### 6. El frontend solo conoce nuestra API

Todas las peticiones son relativas (`/api/...`). En desarrollo el proxy de
Vite las reenvía al backend. Consecuencias:

- Ninguna URL externa ni credencial llega al navegador.
- Cambiar de proveedor no toca la interfaz.
- El CORS puede ser estricto: solo el frontend local.

## Estados de los datos

Se calculan en `ProviderManager.classify_state()` a partir de tres cosas: el
estado de la sesión, el estado de conexión del proveedor y la edad del último
dato.

| Estado | Condición |
|---|---|
| `LIVE` | Sesión activa, proveedor conectado, dato con menos de `LIVE_MAX_AGE_SECONDS` (90 s). |
| `DELAYED` | Igual, pero el dato tiene entre 90 s y 300 s. |
| `HISTORICAL` | La sesión está finalizada. |
| `REPLAY` | Reproducción de una sesión histórica (reproducción manual). |
| `WAITING` | Sesión identificada pero sin registros actuales, o sin sesión detectada. |
| `OFFLINE` | Proveedor desconectado, o el dato es demasiado viejo. |
| `ERROR` | Fallo conocido de la ingesta. |

Los umbrales son configurables (`.env`) y están documentados como
**dependientes de la frecuencia real del proveedor**: el feed de cronometraje
no emite con una cadencia fija.

## Estructura del repositorio

```
race-center/
├── backend/
│   ├── config/          settings, urls, wsgi, asgi
│   ├── core/            modelos, ingesta, API, tests
│   │   └── management/commands/ingest_live.py
│   ├── providers/       base.py, manager.py, free_live.py, openf1.py, jolpica.py
│   ├── manage.py
│   ├── pytest.ini
│   └── requirements.txt
├── frontend/
│   └── src/
│       ├── components/  tabla, paneles, gráfico, diagnóstico
│       ├── composables/ usePolling
│       ├── services/    api.ts
│       ├── stores/      race.ts (Pinia)
│       ├── types/       contratos del dominio
│       └── views/       DashboardView.vue
├── services/live-timing/   f1-livetiming-api (Apache-2.0, upstream)
├── scripts/                 setup / start-dev / stop-dev / doctor / test
├── docs/                    arquitectura, proveedores, diagnóstico, bitácora
├── .env.example
└── README.md
```

## Qué queda preparado para después

- **WebSockets**: la arquitectura ya separa "obtener datos" (ingesta) de
  "entregar datos" (API). Migrar a Django Channels + Redis significa
  publicar el snapshot a un canal; el frontend ya es reactivo al estado.
- **MySQL**: `DATABASE_ENGINE=mysql` ya está soportado en `settings.py` con
  las variables `MYSQL_*`.
- **Replay**: el modelo ya distingue `HISTORICAL` de `REPLAY` y OpenF1
  expone las vueltas por sesión.
- **Telemetría**: OpenF1 tiene `car_data` con velocidad, RPM, marcha,
  acelerador, freno y DRS; ya está implementado en
  `OpenF1Provider.get_telemetry()` y expuesto en
  `/api/sessions/{id}/telemetry/`. Falta la visualisation en el frontend.
- **Mapa**: OpenF1 expone `location`, pero devuelve `x=0, y=0, z=0` cuando el
  feed no trae GPS real. Hay que comprobar si Austin 2026 tiene coordenadas
  antes de prometer un mapa.
