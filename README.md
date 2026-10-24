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
- Panel de diagnóstico con el estado real de cada proveedor: conexión,
  latencia, edad del último dato, último error y reconexiones.
- Vista del circuito con la posición de cada auto, sobre el trazado real
  derivado de las posiciones GPS del propio circuito.

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
