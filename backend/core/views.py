"""API interna de Race Center.

El frontend consume **solo** esta API. Nunca habla directo con las APIs
externas ni con el servicio Node de cronometraje: asi se puede cambiar el
proveedor sin tocar la interfaz, y ningun secreto llega al navegador.

Todas las respuestas incluyen la fuente y la antiguedad del dato.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from django.conf import settings
from django.http import Http404, JsonResponse
from django.views.decorators.http import require_GET

from providers.base import DATA_STATES

from .ingest import build_manager, latest_snapshot, snapshot_for_session
from .models import (
    IngestionRun,
    Lap,
    ProviderStatus as ProviderStatusModel,
    RaceControlEvent,
    Session,
    SessionEntry,
)

logger = logging.getLogger("racecenter.api")


def _json(payload: Any, status: int = 200) -> JsonResponse:
    return JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --------------------------------------------------------------------------- #
# Salud y proveedores
# --------------------------------------------------------------------------- #


@require_GET
def ping(request):
    """Respuesta minima para el health check del orquestador.

    A diferencia de ``/api/health/``, no dice nada del estado de los
    proveedores ni de la ingesta: solo confirma que la app responde. Se
    deja accesible sin proteccion con usuario para que el health check
    externo (Coolify) pueda consultarlo sin credenciales.
    """
    return _json({"status": "ok"})


def health(request):
    """Estado de la aplicacion y del proceso de ingesta."""
    snapshot = latest_snapshot()
    last_run = IngestionRun.objects.order_by("-started_at").first()
    provider_states = []
    if snapshot:
        provider_states = snapshot.get("provider_status") or []

    return _json(
        {
            "status": "ok",
            "app": settings.APP_NAME,
            "mode": settings.APP_MODE,
            "server_time_utc": _now_iso(),
            "timezone": settings.TIME_ZONE,
            "has_snapshot": snapshot is not None,
            "data_state": (snapshot or {}).get("data_state"),
            "last_ingestion": {
                "started_at": last_run.started_at.isoformat() if last_run else None,
                "ok": last_run.ok if last_run else None,
                "duration_ms": last_run.duration_ms if last_run else None,
                "entries_count": last_run.entries_count if last_run else None,
                "changed": last_run.changed if last_run else None,
                "error": last_run.error if last_run else None,
            },
            "providers": [
                {
                    "provider_id": item.get("provider_id"),
                    "state": item.get("state"),
                    "is_connected": item.get("is_connected"),
                }
                for item in provider_states
            ],
        }
    )


@require_GET
def providers(request):
    """Catalogo de proveedores y sus capacidades reales."""
    import asyncio

    manager = build_manager()
    capabilities = asyncio.run(manager.capabilities())
    return _json(
        {
            "count": len(capabilities),
            "providers": [caps.as_dict() for caps in capabilities],
            "selection": {
                "mode": settings.DATA_PROVIDER,
                "live_provider": settings.LIVE_PROVIDER,
                "historical_provider": settings.HISTORICAL_PROVIDER,
                "metadata_provider": settings.METADATA_PROVIDER,
            },
        }
    )


@require_GET
def providers_status(request):
    """Estado operativo de cada proveedor: conexion, latencia, edad del dato."""
    snapshot = latest_snapshot()
    statuses = (snapshot or {}).get("provider_status") or []
    if not statuses:
        # Sin snapshot todavia: se consulta en vivo para no mostrar una pantalla vacia.
        import asyncio

        manager = build_manager()
        statuses = [status.as_dict() for status in asyncio.run(manager.refresh_status())]

    history = ProviderStatusModel.objects.order_by("-recorded_at")[:60]
    return _json(
        {
            "generated_at": _now_iso(),
            "count": len(statuses),
            "providers": statuses,
            "diagnostics": (snapshot or {}).get("diagnostics") or {},
            "history": [
                {
                    "provider_id": item.provider_id,
                    "state": item.state,
                    "is_connected": item.is_connected,
                    "data_age_seconds": item.data_age_seconds,
                    "latency_ms": item.latency_ms,
                    "recorded_at": item.recorded_at.isoformat(),
                }
                for item in history
            ],
        }
    )


# --------------------------------------------------------------------------- #
# Sesiones
# --------------------------------------------------------------------------- #


@require_GET
def sessions(request):
    """Sesiones conocidas, de la mas reciente a la mas antigua.

    Las filas internas de cache (el analisis de sectores y el campeonato se
    guardan en la misma tabla) no son sesiones de carrera: no se listan.
    """
    from .analysis import DERIVED_PROVIDER

    queryset = Session.objects.exclude(provider_id=DERIVED_PROVIDER)
    session_type = request.GET.get("type")
    if session_type:
        queryset = queryset.filter(session_type__iexact=session_type)
    limit = min(int(request.GET.get("limit", 50)), 200)

    data = []
    for item in queryset[:limit]:
        data.append(
            {
                "id": item.id,
                "provider_id": item.provider_id,
                "provider_session_id": item.provider_session_id,
                "name": item.name,
                "session_type": item.session_type,
                "session_number": item.session_number,
                "start_time_utc": item.start_time_utc.isoformat() if item.start_time_utc else None,
                "end_time_utc": item.end_time_utc.isoformat() if item.end_time_utc else None,
                "state": item.state,
                "source_timestamp": item.source_timestamp.isoformat() if item.source_timestamp else None,
            }
        )
    return _json({"count": len(data), "results": data})


@require_GET
def sessions_current(request):
    """La sesion en curso segun el proveedor live.

    Devuelve el snapshot completo porque es lo que el dashboard necesita para
    pintar de una sola vez, sin una cascadea de peticiones.
    """
    snapshot = latest_snapshot()
    if snapshot is None:
        return _json(
            {
                "found": False,
                "reason": (
                    "Todavia no hay ningun snapshot. El proceso de ingesta "
                    "(manage.py ingest_live) tiene que estar corriendo."
                ),
                "data_states": list(DATA_STATES),
            },
            status=200,
        )
    snapshot["found"] = True
    return _json(snapshot)


@require_GET
def meetings(request):
    """Reuniones (Grandes Premios) conocidas,via metadatos de Jolpica."""
    import asyncio

    from providers.jolpica import JolpicaProvider

    provider = JolpicaProvider(base_url=settings.JOLPICA_BASE_URL)
    try:
        races = asyncio.run(provider.get_calendar())
    except Exception as exc:
        return _json({"count": 0, "results": [], "error": str(exc)})

    limit = min(int(request.GET.get("limit", 30)), 100)
    results = []
    for race in races[:limit]:
        circuit = race.get("Circuit") or {}
        location = circuit.get("Location") or {}
        qualifying = race.get("Qualifying") or {}
        results.append(
            {
                "season": race.get("season"),
                "round": race.get("round"),
                "race_name": race.get("raceName"),
                "circuit_name": circuit.get("circuitName"),
                "location": location.get("locality"),
                "country": location.get("country"),
                "date": race.get("date"),
                "time": race.get("time"),
                "qualifying_date": qualifying.get("date"),
                "qualifying_time": qualifying.get("time"),
                "url": race.get("url"),
            }
        )
    return _json({"count": len(results), "results": results})


def _get_session_or_404(session_id: int) -> Session:
    try:
        return Session.objects.get(pk=session_id)
    except Session.DoesNotExist as exc:
        raise Http404("La sesion %s no existe." % session_id) from exc


@require_GET
def session_snapshot(request, session_id: int):
    snapshot = snapshot_for_session(session_id)
    if snapshot is None:
        raise Http404("No hay snapshot para la sesion %s." % session_id)
    snapshot["found"] = True
    return _json(snapshot)


@require_GET
def session_timing(request, session_id: int):
    session = _get_session_or_404(session_id)
    snapshot = snapshot_for_session(session_id) or {}
    entries = snapshot.get("timing") or []
    driver_filter = request.GET.get("driver")
    if driver_filter:
        entries = [e for e in entries if str(e.get("driver_number")) == driver_filter]
    return _json(
        {
            "session_id": session.id,
            "provider_id": session.provider_id,
            "data_state": snapshot.get("data_state"),
            "source_timestamp": snapshot.get("generated_at"),
            "count": len(entries),
            "results": entries,
        }
    )


@require_GET
def session_drivers(request, session_id: int):
    session = _get_session_or_404(session_id)
    snapshot = snapshot_for_session(session_id) or {}
    drivers = snapshot.get("drivers") or []
    return _json(
        {
            "session_id": session.id,
            "provider_id": session.provider_id,
            "count": len(drivers),
            "results": drivers,
        }
    )


@require_GET
def session_laps(request, session_id: int):
    session = _get_session_or_404(session_id)
    queryset = Lap.objects.filter(session=session)
    driver_filter = request.GET.get("driver")
    if driver_filter:
        queryset = queryset.filter(driver__number=driver_filter)
    limit = min(int(request.GET.get("limit", 500)), 5000)

    results = [
        {
            "provider_id": lap.provider_id,
            "driver_number": lap.driver.number if lap.driver else None,
            "lap_number": lap.lap_number,
            "lap_duration": lap.lap_duration,
            "sector_1": lap.sector_1,
            "sector_2": lap.sector_2,
            "sector_3": lap.sector_3,
            "compound": lap.compound,
            "tyre_age_at_start": lap.tyre_age_at_start,
            "is_pit_out_lap": lap.is_pit_out_lap,
            "stint_number": lap.stint_number,
            "position": lap.position,
            "deleted": lap.deleted,
            "date": lap.date.isoformat() if lap.date else None,
        }
        for lap in queryset[:limit]
    ]
    return _json({"session_id": session.id, "count": len(results), "results": results})


@require_GET
def session_weather(request, session_id: int):
    _get_session_or_404(session_id)
    snapshot = snapshot_for_session(session_id) or {}
    weather = snapshot.get("weather")
    return _json(
        {
            "session_id": session_id,
            "found": weather is not None,
            "weather": weather,
            "source": (snapshot.get("sources") or {}).get("weather"),
        }
    )


@require_GET
def session_race_control(request, session_id: int):
    session = _get_session_or_404(session_id)
    snapshot = snapshot_for_session(session_id) or {}
    events = snapshot.get("race_control") or []
    limit = min(int(request.GET.get("limit", 100)), 500)
    return _json(
        {
            "session_id": session.id,
            "provider_id": session.provider_id,
            "count": len(events),
            "results": events[-limit:][::-1],
        }
    )


@require_GET
def session_telemetry(request, session_id: int):
    """Telemetria de la sesion.

    Nunca se envia como parte del snapshot principal: es voluminosa. Si el
    proveedor activo no ofrece telemetria, se responde con el motivo.

    En una sesion **en vivo** la telemetria viene del proveedor live (canal
    `CarData.z` del feed de cronometraje, que exige una cuenta de F1
    autenticada). Para una sesion ya terminada se sigue leyendo de OpenF1,
    que es el unico que conserva el historico.
    """
    session = _get_session_or_404(session_id)
    snapshot = snapshot_for_session(session_id) or {}
    sources = snapshot.get("sources") or {}

    import asyncio

    from .ingest import build_manager

    # Sesion en vivo: primero el proveedor live.
    manager = build_manager()
    scope = "live" if (sources.get("timing") == "free_livetiming") else "historical"
    if scope == "live":
        try:
            samples = asyncio.run(manager.get_telemetry(scope="live"))
        except Exception:
            samples = []
        if samples:
            limit = min(int(request.GET.get("limit", 1000)), 20000)
            driver_filter = request.GET.get("driver")
            if driver_filter:
                samples = [s for s in samples if s.driver_number == driver_filter]
            return _json(
                {
                    "session_id": session.id,
                    "found": True,
                    "count": len(samples[:limit]),
                    "results": [sample.as_dict() for sample in samples[:limit]],
                    "source": "free_livetiming",
                    "note": "Telemetria en vivo del feed de cronometraje.",
                }
            )

    from providers.openf1 import OpenF1Provider

    provider = OpenF1Provider(
        base_url=settings.OPENF1_BASE_URL,
        api_key=settings.OPENF1_API_KEY,
        live_enabled=settings.OPENF1_LIVE_ENABLED,
    )

    try:
        samples = asyncio.run(provider.get_telemetry(session.provider_session_id))
    except Exception as exc:
        return _json(
            {
                "session_id": session.id,
                "found": False,
                "count": 0,
                "results": [],
                "error": str(exc),
                "source": settings.HISTORICAL_PROVIDER,
            }
        )

    limit = min(int(request.GET.get("limit", 1000)), 20000)
    driver_filter = request.GET.get("driver")
    if driver_filter:
        samples = [s for s in samples if s.driver_number == driver_filter]

    return _json(
        {
            "session_id": session.id,
            "found": bool(samples),
            "count": len(samples[:limit]),
            "results": [sample.as_dict() for sample in samples[:limit]],
            "source": settings.HISTORICAL_PROVIDER,
            "note": (
                "La telemetria es historica. El feed live no expone telemetria "
                "de vehiculo."
            ),
        }
    )


@require_GET
def session_entries(request, session_id: int):
    """Estado persistido de cada piloto (util para auditoria)."""
    session = _get_session_or_404(session_id)
    entries = SessionEntry.objects.filter(session=session).select_related("driver")
    return _json(
        {
            "session_id": session.id,
            "count": entries.count(),
            "results": [
                {
                    "driver_number": entry.driver.number if entry.driver else None,
                    "position": entry.position,
                    "best_lap_time": entry.best_lap_time,
                    "number_of_laps": entry.number_of_laps,
                    "tyre_compound": entry.tyre_compound,
                    "updated_at": entry.updated_at.isoformat(),
                }
                for entry in entries
            ],
        }
    )


# --------------------------------------------------------------------------- #
# Trazado del circuito
# --------------------------------------------------------------------------- #


@require_GET
def track_outlines(request):
    """Catalogo de circuitos con trazado disponible."""
    from .tracks import outline_catalog

    catalog = outline_catalog()
    return _json({"count": len(catalog), "results": catalog})


@require_GET
def track_outline(request, circuit_key: int):
    """Trazado de un circuito, derivado de posiciones GPS reales."""
    from .tracks import get_outline

    outline = get_outline(circuit_key)
    if outline is None:
        raise Http404(
            "No hay trazado para el circuito %s. "
            "Se genera con: manage.py build_track_outline --circuit-key %s"
            % (circuit_key, circuit_key)
        )
    return _json(outline)


# --------------------------------------------------------------------------- #
# Sesiones historicas (FP1/FP2/FP3/Sprint/Clasificacion/Carrera)
# --------------------------------------------------------------------------- #


@require_GET
def session_catalog(request):
    """Catalogo de sesiones de un Gran Premio, con la sesion en vivo marcada."""
    import asyncio

    from .history import build_catalog

    meeting_key = request.GET.get("meeting_key")
    try:
        key = int(meeting_key) if meeting_key else None
    except ValueError:
        key = None

    try:
        catalog = asyncio.run(build_catalog(key))
    except Exception as exc:
        return _json({"count": 0, "results": [], "error": str(exc)})

    return _json({"count": len(catalog), "results": catalog})


# --------------------------------------------------------------------------- #
# Prevision meteorologica del circuito
# --------------------------------------------------------------------------- #


@require_GET
def weather_forecast(request):
    """Prevision horaria del circuito (Open-Meteo) y ventana de la proxima sesion.

    El feed de F1 da el clima **actual**; esta prevision es la del **futuro**
    proximo. Son cosas distintas y se muestran separadas: el panel de clima
    conserva el dato observado y la prevision va aparte, con su fuente.
    """
    import asyncio
    from datetime import datetime, timezone

    from .weather import circuit_coordinates, fetch_forecast, forecast_window

    raw_circuit = request.GET.get("circuit_key")
    try:
        circuit_key = int(raw_circuit) if raw_circuit else None
    except ValueError:
        circuit_key = None

    try:
        hours = int(request.GET.get("hours", 48))
    except ValueError:
        hours = 48
    hours = max(1, min(hours, 96))

    if circuit_key is None:
        # Sin parametro: se usa el circuito de la sesion en curso.
        snapshot = latest_snapshot()
        session = (snapshot or {}).get("session") or {}
        circuit_key = session.get("circuit_key")

    forecast = asyncio.run(fetch_forecast(circuit_key, hours=hours))

    if forecast is None:
        coordinates = circuit_coordinates(circuit_key)
        return _json(
            {
                "found": False,
                "reason": (
                    "No hay coordenadas conocidas para el circuito %s, asi que no hay "
                    "prevision." % circuit_key
                    if coordinates is None
                    else "No se pudo obtener la prevision."
                ),
                "circuit_key": circuit_key,
            }
        )

    # Ventana de la proxima sesion: lo que de verdad se pregunta.
    session_window = None
    catalog = []
    try:
        from .history import build_catalog

        snapshot = latest_snapshot()
        meeting_key = ((snapshot or {}).get("session") or {}).get("meeting_key")
        catalog = asyncio.run(build_catalog(meeting_key))
    except Exception:
        catalog = []

    now = datetime.now(timezone.utc)
    upcoming = [
        item
        for item in catalog
        if item.get("start_time_utc")
        and datetime.fromisoformat(item["start_time_utc"]).replace(tzinfo=timezone.utc) > now
    ]
    upcoming.sort(key=lambda item: item["start_time_utc"])
    if upcoming:
        first = upcoming[0]
        start = datetime.fromisoformat(first["start_time_utc"])
        end = (
            datetime.fromisoformat(first["end_time_utc"])
            if first.get("end_time_utc")
            else None
        )
        window = forecast_window(forecast, start, end)
        if window is not None:
            session_window = {
                "session_key": first.get("session_key"),
                "session_name": first.get("session_name"),
                "session_type": first.get("session_type"),
                "start_time_utc": first.get("start_time_utc"),
                "end_time_utc": first.get("end_time_utc"),
                **window,
            }

    return _json(
        {
            "found": True,
            "forecast": forecast,
            "next_session_window": session_window,
            "upcoming_sessions": [
                {
                    "session_key": item.get("session_key"),
                    "session_name": item.get("session_name"),
                    "start_time_utc": item.get("start_time_utc"),
                }
                for item in upcoming[:5]
            ],
        }
    )


@require_GET
def historical_snapshot(request, session_key: str):
    """Snapshot normalizado de una sesion historica."""
    import asyncio

    from .history import (
        build_historical_snapshot,
        cached_historical_snapshot,
        store_historical_snapshot,
    )

    # El historico de una sesion no cambia: si ya se resolvio, se sirve desde
    # la cache (memoria o base) sin volver a consumir cuota de OpenF1.
    cached = cached_historical_snapshot(session_key)
    if cached is not None:
        return _json(cached)

    try:
        payload = asyncio.run(build_historical_snapshot(str(session_key)))
    except Exception as exc:
        return _json(
            {"found": False, "reason": str(exc), "session_key": str(session_key)},
            status=200,
        )

    if payload is None:
        return _json(
            {
                "found": False,
                "reason": "No hay datos historicos para la sesion %s." % session_key,
                "session_key": str(session_key),
            },
            status=200,
        )

    # Un snapshot degradado (por ejemplo, sin clima por limite de tasa) no se
    # guarda: se vuelve a pedir para no cachear una respuesta incompleta.
    if not payload.get("warnings"):
        snapshot = store_historical_snapshot(payload)
        if snapshot is not None:
            payload["_snapshot_id"] = snapshot.id
            payload["_session_pk"] = snapshot.session_id
    payload["found"] = True
    return _json(payload)


# --------------------------------------------------------------------------- #
# Analisis post-sesion: sectores y campeonato
# --------------------------------------------------------------------------- #


@require_GET
def analysis_sectors(request, session_key: str):
    """Analisis por sectores de una sesion.

    Devuelve la mejor vuelta de cada piloto con sus tres sectores, el delta
    contra el mas rapido y el delta sector por sector contra el piloto de
    referencia. Con ``compare`` se agrega la diferencia contra la mejor vuelta
    de la otra sesion (por ejemplo, FP3 contra Clasificacion).

    Los datos vienen de OpenF1 (``/laps``), que es la unica fuente donde los
    sectores **suman** la vuelta: el feed en vivo solo publica los sectores de
    la ultima vuelta de cada piloto.
    """
    from providers.base import ProviderError

    from .analysis import build_sector_analysis

    reference = request.GET.get("reference") or None
    compare = request.GET.get("compare") or None

    try:
        payload = build_sector_analysis(str(session_key), reference, compare)
    except ProviderError as exc:
        return _json(
            {
                "found": False,
                "session_key": str(session_key),
                "rows": [],
                "error": str(exc),
                "source": settings.HISTORICAL_PROVIDER,
            }
        )
    except Exception as exc:
        logger.warning("Fallo el analisis de sectores de %s: %s", session_key, exc)
        return _json(
            {
                "found": False,
                "session_key": str(session_key),
                "rows": [],
                "error": str(exc),
                "source": settings.HISTORICAL_PROVIDER,
            }
        )
    return _json(payload)


@require_GET
def analysis_positions(request, session_key: str):
    """Evolucion de posiciones: la posicion de cada piloto al final de cada vuelta.

    Fuente OpenF1: ``/position`` (los cambios de posicion, con su instante) y
    ``/laps`` (a que vuelta pertenece cada cambio).
    """
    from providers.base import ProviderError

    from .analysis import build_position_history

    try:
        payload = build_position_history(str(session_key))
    except ProviderError as exc:
        return _json(
            {
                "found": False,
                "session_key": str(session_key),
                "rows": [],
                "error": str(exc),
                "source": settings.HISTORICAL_PROVIDER,
            }
        )
    except Exception as exc:
        logger.warning("Fallo la evolucion de posiciones de %s: %s", session_key, exc)
        return _json(
            {
                "found": False,
                "session_key": str(session_key),
                "rows": [],
                "error": str(exc),
                "source": settings.HISTORICAL_PROVIDER,
            }
        )
    return _json(payload)


@require_GET
def analysis_strategy(request, session_key: str):
    """Estrategia de neumaticos: stints, paradas y mejor vuelta de cada stint.

    Fuente OpenF1: ``/stints`` (compuesto y edad) y ``/laps`` (los tiempos).
    """
    from providers.base import ProviderError

    from .analysis import build_strategy

    try:
        payload = build_strategy(str(session_key))
    except ProviderError as exc:
        return _json(
            {
                "found": False,
                "session_key": str(session_key),
                "rows": [],
                "error": str(exc),
                "source": settings.HISTORICAL_PROVIDER,
            }
        )
    except Exception as exc:
        logger.warning("Fallo la estrategia de %s: %s", session_key, exc)
        return _json(
            {
                "found": False,
                "session_key": str(session_key),
                "rows": [],
                "error": str(exc),
                "source": settings.HISTORICAL_PROVIDER,
            }
        )
    return _json(payload)


@require_GET
def championship(request):
    """Clasificacion del campeonato de pilotos y de constructores.

    Fuente Jolpica: OpenF1 no publica campeonato. El payload dice en que
    ronda esta la tabla, para no hacer creer que ya sumo Austin.
    """
    from providers.base import ProviderError

    from .analysis import build_championship

    raw_season = request.GET.get("season")
    try:
        season = int(raw_season) if raw_season else None
    except ValueError:
        season = None

    try:
        payload = build_championship(season)
    except ProviderError as exc:
        return _json({"found": False, "drivers": [], "teams": [], "error": str(exc)})
    except Exception as exc:
        logger.warning("Fallo la consulta del campeonato: %s", exc)
        return _json({"found": False, "drivers": [], "teams": [], "error": str(exc)})
    return _json(payload)
