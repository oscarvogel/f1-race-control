# Race Center

Dashboard **personal** de Fórmula 1 para uso familiar. Corre localmente en
WSL Ubuntu y muestra la clasificación en vivo de la sesión actual, con la
fuente y la antigüedad de cada dato siempre visibles.

No es un producto comercial, no se publica a Internet y no tiene
suscripciones ni planes de usuario.

---

## Qué hace

- Detecta la sesión en curso (GP, circuito, tipo, ID real de sesión).
- Muestra la clasificación con posiciones, mejores vueltas, sectores por
  segmento (Q1/Q2/Q3), gaps, vueltas y neumáticos.
- Muestra eventos de control de carrera, clima y estado de la pista.
- Indica en todo momento el **estado** de los datos: `LIVE`, `DELAYED`,
  `HISTORICAL`, `REPLAY`, `WAITING`, `OFFLINE` o `ERROR`.
- Muestra las tres horas que importan: la **hora local**, la **hora del
  circuito** (con el desfase que publica la propia organización) y la
  **cuenta regresiva a la próxima sesión**, en grande y en rojo cuando faltan
  menos de 15 minutos.
- Muestra la **previsión meteorológica del circuito** (Open-Meteo) y las
  condiciones previstas para la próxima sesión, separada del clima observado.
- Permite elegir cualquier sesión del Gran Premio (FP1, FP2, FP3, Sprint,
  Clasificación, Carrera) y ver sus estadísticas completas.
- **Panel de análisis**: la mejor vuelta de cada piloto con sus tres sectores,
  el Δ contra el más rápido y el Δ sector por sector contra el piloto que se
  elija; además, el Δ de la vuelta contra otra sesión (por ejemplo, FP3).
- **Panel de evolución de posiciones**: un gráfico con la posición que tenía
  cada piloto al final de cada vuelta (quién pasó a quién y en qué vuelta).
- **Panel de estrategia de neumáticos**: los tramos de vueltas de cada piloto,
  con el compuesto, cuántas vueltas, la edad del neumático y su mejor vuelta
  de carrera en cada tramo.
- **Panel de campeonato**: la tabla de pilotos y de constructores de la
  temporada, con puntos, victorias y rezago, indicando en qué ronda está.
- Panel de diagnóstico con el estado real de cada proveedor: conexión,
  latencia, edad del último dato, último error y reconexiones.
- Vista del circuito con la posición de cada auto, sobre el trazado real
  derivado de las posiciones GPS del propio circuito.
- **Acceso propio**: si hay credenciales configuradas, el sitio pide usuario
  y contraseña con una pantalla de la propia aplicación (no el diálogo del
  navegador) y la API exige una sesión válida.

## Stack

| Capa | Tecnología |
|---|---|
| Backend | Python 3.12, Django 6, Django REST Framework, httpx, SQLite |
| Frontend | Vue 3, TypeScript, Vite, Pinia, Tailwind CSS 4, Apache ECharts, Lucide |
| Proveedor live | Node.js 22 LTS + [`f1-livetiming-api`](https://github.com/julesr0y/f1-livetiming-api) (Apache-2.0) |
| Histórico | [OpenF1](https://openf1.org/docs/) (histórico gratuito desde 2023) |
| Metadatos | [Jolpica / Ergast](https://api.jolpi.ca/docs/) |
| Previsión | [Open-Meteo](https://open-meteo.com) (público, sin clave) |

## Puesta en marcha (WSL Ubuntu)

```bash
cd /mnt/c/Programacion/proyectos/actives/f1-race-center

./scripts/setup.sh      # instala toolchain, dependencias, base de datos
./scripts/start-dev.sh  # arranca proveedor live + ingesta + API + frontend
```

Luego abrir **http://127.0.0.1:5174**.

| Servicio | URL |
|---|---|
| Frontend | http://127.0.0.1:5174 |
| API interna | http://127.0.0.1:8000/api/ |
| Proveedor live | http://127.0.0.1:3000/api/ |

## Despliegue en contenedor (Coolify)

La misma app corre como **un solo contenedor** con cuatro procesos:

| Proceso | Qué hace | Escucha en |
|---|---|---|
| `nginx` | sirve el SPA y hace proxy de `/api` | `0.0.0.0:80` (único puerto) |
| `backend` | Django con gunicorn | `127.0.0.1:8000` |
| `ingest` | `manage.py ingest_live --interval 3` | — |
| `live` | proveedor Node de cronometraje | `127.0.0.1:3000` |

El proveedor del feed de la F1 **no** queda expuesto: escucha en loopback
dentro del contenedor, igual que en local.

```bash
docker build -t race-center:local .
docker run -d --name race-center -p 8080:80 -v race-center-data:/data \
  -e DJANGO_SECRET_KEY=cambiar \
  -e RACE_CENTER_USER=piloto -e RACE_CENTER_PASSWORD=cambiar \
  race-center:local
```

En Coolify, la aplicación debe usar el build pack **`Dockerfile`**: con
Nixpacks, Coolify genera su propio Dockerfile e ignora el del repositorio, y
el contenedor levantaría sin el proveedor de cronometraje.

Variables de entorno (los valores exactos están en `docs/BITACORA.md` §13):

| Variable | Para qué |
|---|---|
| `DJANGO_SECRET_KEY` | clave de Django |
| `DJANGO_DB_PATH` | ruta del SQLite (en el contenedor, el volumen `/data`) |
| `APP_DEBUG` | `false` |
| `ENABLE_LAN_ACCESS` / `LAN_ALLOWED_HOSTS` / `LAN_ALLOWED_ORIGINS` | hosts y orígenes del dominio |
| `TRUST_PROXY_SSL` | `true` detrás del proxy que termina TLS |
| `F1_LIVETIMING_URL` | `http://127.0.0.1:3000` (el proveedor, dentro del contenedor) |
| `RACE_CENTER_USER` / `RACE_CENTER_PASSWORD` | protección del sitio: sin ellos se sirve **sin** contraseña (modo desarrollo) |
| `RACE_CENTER_SESSION_DAYS` | duración de la cookie de sesión (30 días) |

### Acceso al sitio

La protección la aplica **nginx** con `auth_request`: antes de dejar pasar una
petición a la API, le pregunta a Django (`/api/auth/check/`) si la cookie de
sesión es válida. El backend tiene además su propio filtro
(`core.auth.SessionAuthMiddleware`), por si el borde se configura mal.

El 401 **no** lleva `WWW-Authenticate`: si lo llevara, el navegador abriría su
diálogo nativo. Sin ese encabezado, la pantalla de acceso es un panel de la
propia aplicación, en español y con el tema oscuro, y el botón "Salir" de la
cabecera cierra la sesión.

Detalle completo en [`docs/BITACORA.md`](docs/BITACORA.md) §14.

> El puerto del frontend es **5174** y no 5173 porque en esta máquina el 5173
> ya lo ocupa otro proyecto (`0.0.0.0:5173` en Windows). Se cambia en
> `.env` (`FRONTEND_PORT`) y en `scripts/start-dev.sh`. La API (8000) y el
> proveedor live (3000) no tienen conflicto.

Otros scripts:

```bash
./scripts/doctor.sh   # diagnóstico con datos concretos
./scripts/test.sh     # pytest + compilación del frontend + smoke test
./scripts/stop-dev.sh # detener solo los procesos de Race Center
```

## Configuración

Todo se configura en `.env` (copiado de `.env.example` por `setup.sh`).
Nunca se versionan secretos.

| Variable | Por defecto | Para qué |
|---|---|---|
| `DATA_PROVIDER` | `auto` | `auto` / `live` / `historical` / `metadata` |
| `LIVE_PROVIDER` | `free_livetiming` | Proveedor de cronometraje en vivo |
| `HISTORICAL_PROVIDER` | `openf1` | Proveedor de datos históricos |
| `METADATA_PROVIDER` | `jolpica` | Calendario y metadatos |
| `F1_LIVETIMING_URL` | `http://127.0.0.1:3000` | Servicio Node local |
| `OPENF1_BASE_URL` | `https://api.openf1.org/v1` | API histórica |
| `OPENF1_LIVE_ENABLED` | `false` | Acceso live de OpenF1 (requiere suscripción propia) |
| `ENABLE_PUBLIC_ACCESS` | `false` | Publicar en Internet (no hacerlo) |
| `ENABLE_LAN_ACCESS` | `false` | Acceso desde la LAN |
| `ENABLE_MOCK_DATA` | `false` | Datos sintéticos (desactivados a propósito) |
| `LIVE_MAX_AGE_SECONDS` | `90` | Umbral para considerar el dato `LIVE` |
| `DELAYED_MAX_AGE_SECONDS` | `300` | Umbral para considerar el dato `DELAYED` |

## Arquitectura en una línea

```
livetiming.formula1.com (SignalR)
        │
        ▼
  servicio Node local  ──127.0.0.1:3000──►  FreeLiveTimingProvider
                                                 │
                                                 ▼
                                          ProviderManager
                                                 │  (normaliza + elige fuente)
                                                 ▼
                                        proceso de ingesta  ──►  SQLite (SessionSnapshot)
                                                 │
                                                 ▼
                                          API interna Django  ──127.0.0.1:8000/api──►  Vue 3
```

El frontend consume **solo** nuestra API. Nunca habla con las APIs externas
ni con el servicio Node: por eso no hay credenciales en el navegador y abrir
dos pestañas no duplica la ingesta.

Detalles en [`docs/architecture.md`](docs/architecture.md),
[`docs/providers.md`](docs/providers.md) y
[`docs/live-diagnostics.md`](docs/live-diagnostics.md).

## Estructura del repositorio

| Ruta | Qué hay |
|---|---|
| `backend/` | Django: `config/`, `core/` (modelos, ingesta, comandos) y `providers/` |
| `frontend/` | Vue 3 + Vite: componentes, vistas, stores y servicios |
| `services/live-timing/` | Proveedor live **vendorizado** (Apache-2.0, ver abajo) |
| `docs/` | Documentación técnica y bitácora de trabajo |
| `scripts/` | Setup, arranque, diagnóstico, pruebas y parche del proveedor |

No se versiona nada de esto: `.env` (secretos), `backend/.venv/`,
`backend/db.sqlite3`, `node_modules/`, `frontend/dist/` y `.run/` (PIDs y
logs). La plantilla `.env.example` sí está versionada.

### El proveedor live está vendorizado

`services/live-timing/` es un clon de
[`julesr0y/f1-livetiming-api`](https://github.com/julesr0y/f1-livetiming-api)
(versionado **dentro** de este repo, no como submódulo) por una razón concreta:
el proveedor necesita parches locales que no existen en el upstream —

1. `bind` en `127.0.0.1` en lugar de `0.0.0.0`.
2. CORS restringido a orígenes de loopback en vez de abierto.
3. Suscripción al canal `CarData` de SignalR y la ruta de solo lectura
   `/api/car-data`, que alimenta la vista del circuito.

Un submódulo no puede versionar esos parches: quedaría la versión original del
upstream y el proyecto dejaría de funcionar al clonar. Por eso el clon de git
del proveedor queda renombrado como `services/live-timing/.git-upstream-backup/`
(no se versiona) para poder comparar contra el upstream, y el parche se puede
reaplicar de forma idempotente con `scripts/patch_livetiming_provider.py`.

## Seguridad

- Backend, frontend y proveedor live escuchan **solo en loopback**.
- El proveedor Node se parcheó para que haga `bind` en `127.0.0.1` (el
  upstream escucha en `0.0.0.0`) y para restringir CORS a orígenes locales.
  El parche está documentado en `docs/providers.md`.
- CORS del backend limitado al frontend local; nunca abierto.
- Sin secretos en Git: `.env` está en `.gitignore`.
- El modo LAN es opcional y está documentado en
  `docs/providers.md`; no abre puertos del router.

## Licencias y términos

- `services/live-timing` es código de terceros con licencia **Apache-2.0** y
  su `NOTICE` correspondiente, vendorizado dentro de este repo. Se usa como
  servicio local aislado y su lógica de cronometraje no se modifica: los
  cambios son parches acotados, marcados en el código con
  `[Race Center patch]` y aplicados por `scripts/patch_livetiming_provider.py`.
- OpenF1: histórico gratuito desde 2023; el acceso en vivo requiere una
  suscripción pagada y **no** está habilitado.
- Jolpica: API abierta de metadatos.
- Open-Meteo: previsión meteorológica pública, sin clave ni suscripción. Sus
  coordenadas de circuito se toman de Jolpica, no se estiman.
- El feed de cronometraje corresponde a la Formula 1. Este proyecto es
  personal y privado; la distribución de los datos no está contemplada.

## Estado

Ver [`docs/BITACORA.md`](docs/BITACORA.md) para el registro de trabajo, los
problemas encontrados y qué queda pendiente.
