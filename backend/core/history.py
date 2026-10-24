"""Sesiones historicas: catalogo y snapshot completo de una sesion.

Permite elegir FP1, FP2, FP3, Sprint, Clasificacion o Carrera de un Gran
Premio y ver sus estadisticas reales, con la misma API normalizada que usa el
dashboard en vivo.

La fuente es OpenF1 (historico gratuito). Los datos llevan su
``provider_id`` y su ``source_timestamp`` como todo lo demas: el frontend
sabe siempre de donde viene cada cifra.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

from django.conf import settings

from providers.base import ProviderError
from providers.free_live import FreeLiveTimingProvider
from providers.openf1 import OpenF1Provider

from .models import Session, SessionSnapshot, payload_fingerprint

logger = logging.getLogger("racecenter.history")

# OpenF1 limita la tasa por IP. El catalogo se cachea para no repetir las
# consultas en cada refresco del frontend.
_CATALOG_CACHE: dict[str, Any] = {"key": None, "expires": 0.0, "data": []}

# Nombre del Gran Premio en curso: lo publica el proveedor en vivo.
_LIVE_MEETING_NAME: list[str | None] = [None]
CATALOG_TTL_SECONDS = 3600.0

# Snapshots historicos ya resueltos. El historico de un GP no cambia, asi que
# reconsultarlo a OpenF1 cada vez que el usuario cambia de sesion solo sirve
# para agotar la cuota por IP.
_SNAPSHOT_CACHE: dict[str, dict[str, Any]] = {}
SNAPSHOT_TTL_SECONDS = 600.0


def _catalog_session_id(meeting_key: int | None) -> str:
    """Identificador de la sesion donde se guarda el catalogo."""
    return "catalog:%s" % (meeting_key if meeting_key is not None else "all")


async def stored_catalog(meeting_key: int | None) -> list[dict[str, Any]] | None:
    """Catalogo guardado en la base por una consulta anterior.

    Hace falta porque **OpenF1 bloquea todo el acceso, incluso a sesiones
    pasadas, mientras hay una sesion de F1 en curso** (responde 401 con
    "Live F1 session in progress"). Sin esta copia, durante la carrera el
    selector de sesiones se quedaria vacio justo cuando mas hace falta.
    """
    import asyncio

    def _consultar() -> list[dict[str, Any]] | None:
        session, _ = Session.objects.get_or_create(
            provider_id="openf1",
            provider_session_id=_catalog_session_id(meeting_key),
            defaults={"name": "Catalogo de sesiones"},
        )
        stored = (
            SessionSnapshot.objects.filter(session=session, scope="catalog")
            .order_by("-created_at")
            .first()
        )
        if stored is None:
            return None
        results = (stored.payload or {}).get("results")
        return results if isinstance(results, list) else None

    return await asyncio.to_thread(_consultar)


async def store_catalog(meeting_key: int | None, results: list[dict[str, Any]]) -> None:
    """Guarda el catalogo para poder usarlo aunque OpenF1 se bloquee."""
    import asyncio

    def _guardar() -> None:
        session, _ = Session.objects.get_or_create(
            provider_id="openf1",
            provider_session_id=_catalog_session_id(meeting_key),
            defaults={"name": "Catalogo de sesiones"},
        )
        payload = {
            "results": results,
            "fetched_at": _stamp(),
            "meeting_key": meeting_key,
        }
        fingerprint = payload_fingerprint(payload)
        existing = (
            SessionSnapshot.objects.filter(session=session, scope="catalog")
            .order_by("-created_at")
            .first()
        )
        if existing is not None and existing.fingerprint == fingerprint:
            return
        SessionSnapshot.objects.create(
            session=session,
            provider_id="openf1",
            scope="catalog",
            data_state="METADATA",
            fingerprint=fingerprint,
            payload=payload,
        )

    await asyncio.to_thread(_guardar)


def _openf1_provider() -> OpenF1Provider:
    return OpenF1Provider(
        base_url=settings.OPENF1_BASE_URL,
        api_key=settings.OPENF1_API_KEY,
        live_enabled=settings.OPENF1_LIVE_ENABLED,
    )


def _live_provider() -> FreeLiveTimingProvider:
    return FreeLiveTimingProvider(
        base_url=settings.F1_LIVETIMING_URL,
        timeout=settings.INGEST_HTTP_TIMEOUT,
    )


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


async def build_catalog(meeting_key: int | None = None) -> list[dict[str, Any]]:
    """Catalogo de sesiones de un meeting (o de toda la temporada).

    Si el proveedor esta bloqueado (OpenF1 no deja consultar nada, ni
    siquiera del pasado, mientras hay una sesion de F1 en curso) se devuelve
    la copia guardada en la base, marcada como ``stale``: es informacion
    real, solo que de una consulta anterior. No se inventa nada.
    """
    cache_key = str(meeting_key or "all")
    now = time.monotonic()
    if (
        _CATALOG_CACHE["key"] == cache_key
        and _CATALOG_CACHE["expires"] > now
    ):
        return _CATALOG_CACHE["data"]

    try:
        catalog = await _fetch_catalog(meeting_key)
    except Exception as exc:
        logger.warning("No se pudo refrescar el catalogo con OpenF1: %s", exc)
        # OpenF1 bloquea todo el acceso mientras hay una sesion de F1 en
        # curso. Jolpica no se bloquea: el calendario sale de ahi.
        try:
            catalog = await _catalog_from_jolpica(meeting_key)
        except Exception as exc_jolpica:
            logger.warning("Tampoco se pudo leer el calendario en Jolpica: %s", exc_jolpica)
            stored = await stored_catalog(meeting_key)
            if stored is not None:
                for entry in stored:
                    entry["stale"] = True
                return stored
            raise
        for entry in catalog:
            entry["stale"] = True

    await store_catalog(meeting_key, catalog)
    _CATALOG_CACHE["key"] = cache_key
    _CATALOG_CACHE["expires"] = time.monotonic() + CATALOG_TTL_SECONDS
    _CATALOG_CACHE["data"] = catalog
    return catalog


async def _fetch_catalog(meeting_key: int | None) -> list[dict[str, Any]]:
    """Consulta el catalogo al proveedor de metadatos."""
    provider = _openf1_provider()
    await provider.connect()
    try:
        filters: dict[str, Any] = {}
        if meeting_key is not None:
            filters["meeting_key"] = meeting_key
        sessions = await provider.get_sessions(**filters)

        # El endpoint de sesiones no trae el nombre del Gran Premio: se
        # completa con el endpoint de meetings.
        meetings = await provider._get_json("/meetings", {"meeting_key": meeting_key} if meeting_key else None)
        meeting_names = {
            str(row.get("meeting_key")): row.get("meeting_name") for row in meetings
        }
        # Desfase horario del circuito (dato real: p.ej. "-05:00:00" en Austin).
        meeting_offsets = {
            str(row.get("meeting_key")): row.get("gmt_offset") for row in meetings
        }
    finally:
        await provider.disconnect()

    # La sesion que el proveedor live esta mostrando ahora mismo.
    live_key: str | None = None
    live = _live_provider()
    try:
        await live.connect()
        session = await live.get_session()
        if session is not None:
            live_key = session.provider_session_id
    except Exception as exc:  # pragma: no cover - defensivo
        logger.debug("No se pudo determinar la sesion live: %s", exc)
    finally:
        await live.disconnect()

    catalog: list[dict[str, Any]] = []
    for item in sessions:
        catalog.append(
            {
                "provider_id": item.provider_id,
                "session_key": item.provider_session_id,
                "session_type": item.session_type,
                "session_name": item.session_name,
                "start_time_utc": item.start_time_utc.isoformat() if item.start_time_utc else None,
                "end_time_utc": item.end_time_utc.isoformat() if item.end_time_utc else None,
                "meeting_name": item.meeting_name or meeting_names.get(str(item.meeting_key)),
                "circuit_name": item.circuit_name,
                "meeting_key": item.meeting_key,
                "gmt_offset": item.gmt_offset or meeting_offsets.get(str(item.meeting_key)),
                "is_live": str(item.provider_session_id) == str(live_key),
                "stale": False,
            }
        )
    # Dejar la sesion en vivo primera.
    catalog.sort(key=lambda entry: (not entry["is_live"], entry["start_time_utc"] or ""))
    return catalog


def _jolpica_provider():
    """Proveedor de metadatos (Jolpica), para el calendario."""
    from providers.jolpica import JolpicaProvider

    return JolpicaProvider(base_url=settings.JOLPICA_BASE_URL)


async def _session_keys_by_name() -> dict[str, str]:
    """Claves de sesion conocidas, por nombre de sesion.

    Se recuperan de la base: son las que ya se descargaron antes. Sirven
    para que el selector siga ofreciendo los FP y la carrera aunque el
    proveedor principal este bloqueado.

    La consulta al ORM es sincronica y esta funcion es asincrona: se ejecuta
    en otro hilo (Django no permite consultar el ORM desde un contexto
    async).
    """
    import asyncio

    from .models import Session as SessionModel

    def _consultar() -> list[tuple[str, str]]:
        return [
            (fila.name, fila.provider_session_id)
            for fila in SessionModel.objects.filter(provider_id="openf1")
            if fila.name
        ]

    claves: dict[str, str] = {}
    for nombre, clave in await asyncio.to_thread(_consultar):
        claves.setdefault(nombre, clave)
    return claves


async def _catalog_from_jolpica(meeting_key: int | None) -> list[dict[str, Any]]:
    """Catalogo de sesiones construido con el calendario de Jolpica.

    Jolpica publica la hora de inicio de cada sesion del fin de semana. No
    publica las claves de sesion de OpenF1, asi que se recuperan de la base
    de datos para las sesiones ya conocidas.
    """
    provider = _jolpica_provider()
    await provider.connect()
    try:
        # El nombre del Gran Premio viene del proveedor en vivo: es lo que
        # permite encontrar la ronda dentro del calendario de la temporada.
        nombre = await _live_meeting_name()
        if not nombre:
            raise ProviderError("No se conoce el nombre del Gran Premio en curso.")

        temporada = datetime.now(timezone.utc).year
        ronda = await provider.find_round_by_name(temporada, nombre)
        if ronda is None:
            raise ProviderError(
                "No se encontro la ronda '%s' en el calendario de %d." % (nombre, temporada)
            )

        sesiones = await provider.get_round_schedule(temporada, ronda)
    finally:
        await provider.disconnect()

    claves = await _session_keys_by_name()

    # El desfase horario del circuito lo publica el feed de F1 (GmtOffset).
    # Jolpica no lo da, pero es el mismo para todas las sesiones del Gran
    # Premio, asi que se toma de la sesion en vivo.
    desfase = await _live_gmt_offset()

    catalogo: list[dict[str, Any]] = []
    for sesion in sesiones:
        clave = claves.get(sesion["session_name"])
        catalogo.append(
            {
                "provider_id": "jolpica",
                "session_key": clave,
                "session_type": sesion["session_type"],
                "session_name": sesion["session_name"],
                "start_time_utc": sesion["start_time_utc"],
                "end_time_utc": sesion["end_time_utc"],
                "meeting_name": sesion.get("meeting_name"),
                "circuit_name": sesion.get("circuit_name"),
                "location": sesion.get("location"),
                "meeting_key": meeting_key,
                "gmt_offset": desfase,
                "is_live": False,
                "stale": True,
            }
        )
    catalogo.sort(key=lambda entry: entry["start_time_utc"] or "")
    return catalogo


async def _live_gmt_offset() -> str | None:
    """Desfase horario del circuito, segun el proveedor en vivo."""
    provider = _live_provider()
    try:
        await provider.connect()
        session = await provider.get_session()
        return session.gmt_offset if session is not None else None
    except Exception:
        return None
    finally:
        try:
            await provider.disconnect()
        except Exception:
            pass


async def _live_meeting_name() -> str | None:
    """Nombre del Gran Premio en curso, segun el proveedor en vivo."""
    provider = _live_provider()
    try:
        await provider.connect()
        session = await provider.get_session()
        return session.meeting_name if session is not None else None
    except Exception:
        return None
    finally:
        try:
            await provider.disconnect()
        except Exception:
            pass


async def _fetch_optional(
    label: str,
    call: Callable[[], Awaitable[Any]],
    default: Any,
    warnings: list[str],
) -> Any:
    """Ejecuta una consulta opcional.

    Si falla (por ejemplo, por limite de tasa de OpenF1) la parte opcional
    se degrada a ``default`` y el motivo queda anotado en ``warnings``. Un
    clima que no se pudo leer no puede tumbar la clasificacion de la sesion.
    """
    try:
        return await call()
    except ProviderError as exc:
        warnings.append("%s: %s" % (label, exc))
        logger.warning("Snapshot historico sin '%s': %s", label, exc)
        return default


async def build_historical_snapshot(session_key: str) -> dict[str, Any] | None:
    """Snapshot normalizado completo de una sesion historica."""
    provider = _openf1_provider()
    warnings: list[str] = []
    await provider.connect()
    try:
        try:
            session = await provider.get_session(session_key)
        except ProviderError as exc:
            logger.warning("No se pudo leer la sesion historica %s: %s", session_key, exc)
            return None
        if session is None:
            return None

        # Las consultas se hacen de a una: el propio proveedor OpenF1 las
        # separa con un intervalo minimo, porque limita la tasa por IP.
        drivers = await _fetch_optional(
            "pilotos", lambda: provider.get_drivers(session_key), [], warnings
        )
        timing = await _fetch_optional(
            "clasificacion", lambda: provider.get_timing(session_key), [], warnings
        )
        stints = await _fetch_optional(
            "neumaticos", lambda: provider.get_stints(session_key), [], warnings
        )
        weather = await _fetch_optional(
            "clima", lambda: provider.get_weather(session_key), None, warnings
        )
        race_control = await _fetch_optional(
            "control de carrera", lambda: provider.get_race_control(session_key), [], warnings
        )
        positions = await _fetch_optional(
            "posiciones en pista", lambda: provider.get_positions(session_key), [], warnings
        )
    finally:
        await provider.disconnect()

    return {
        "generated_at": _stamp(),
        "data_state": "HISTORICAL",
        "scope": "historical",
        "session": session.as_dict(),
        "drivers": [driver.as_dict() for driver in drivers],
        "timing": [entry.as_dict() for entry in timing],
        "weather": weather.as_dict() if weather else None,
        "race_control": [event.as_dict() for event in race_control],
        "tyres": [stint.as_dict() for stint in stints],
        "positions": [dict(position) for position in positions],
        "track_status": None,
        "warnings": warnings,
        "sources": {
            "session": provider.provider_id,
            "timing": provider.provider_id,
            "drivers": provider.provider_id,
            "weather": provider.provider_id,
            "race_control": provider.provider_id,
            "tyres": provider.provider_id,
            "positions": provider.provider_id if positions else None,
            "track_status": None,
        },
        "provider_status": [],
        "diagnostics": {
            "mode": "historical",
            "live_provider": settings.LIVE_PROVIDER,
            "historical_provider": settings.HISTORICAL_PROVIDER,
            "metadata_provider": settings.METADATA_PROVIDER,
            "thresholds": {
                "live_max_age_seconds": settings.LIVE_MAX_AGE_SECONDS,
                "delayed_max_age_seconds": settings.DELAYED_MAX_AGE_SECONDS,
            },
            "providers": [],
            "last_error": {},
        },
    }


def cached_historical_snapshot(session_key: str) -> dict[str, Any] | None:
    """Snapshot historico ya resuelto, si lo hay.

    Primero la memoria del proceso; despues la base de datos, para que el
    historico siga disponible despues de reiniciar el backend. Solo se
    devuelven snapshots **completos**: uno degradado se vuelve a pedir.
    """
    key = str(session_key)
    now = time.monotonic()
    entry = _SNAPSHOT_CACHE.get(key)
    if entry is not None and entry["expires"] > now:
        return dict(entry["payload"])

    session = Session.objects.filter(
        provider_id="openf1", provider_session_id=key
    ).first()
    if session is not None:
        stored = (
            SessionSnapshot.objects.filter(session=session).order_by("-created_at").first()
        )
        if stored is not None:
            payload = dict(stored.payload)
            if not payload.get("warnings"):
                payload["found"] = True
                payload["_snapshot_id"] = stored.id
                payload["_session_pk"] = stored.session_id
                payload["_from_cache"] = "db"
                _SNAPSHOT_CACHE[key] = {
                    "payload": payload,
                    "expires": now + SNAPSHOT_TTL_SECONDS,
                }
                return payload
    return None


def store_historical_snapshot(payload: dict[str, Any]) -> SessionSnapshot | None:
    """Guarda el snapshot historico para poder consultarlo por id."""
    session_data = payload.get("session") or {}
    provider_session_id = str(session_data.get("provider_session_id") or "")
    if not provider_session_id:
        return None

    session, _ = Session.objects.get_or_create(
        provider_id=session_data.get("provider_id") or "openf1",
        provider_session_id=provider_session_id,
        defaults={
            "name": session_data.get("session_name") or session_data.get("meeting_name") or "",
            "session_type": session_data.get("session_type") or "",
            "start_time_utc": _parse(session_data.get("start_time_utc")),
            "end_time_utc": _parse(session_data.get("end_time_utc")),
            "state": session_data.get("state") or "Finalised",
        },
    )

    fingerprint = payload_fingerprint(payload)
    existing = (
        SessionSnapshot.objects.filter(session=session).order_by("-created_at").first()
    )
    if existing is not None and existing.fingerprint == fingerprint:
        return existing
    return SessionSnapshot.objects.create(
        session=session,
        provider_id=session_data.get("provider_id") or "openf1",
        scope=payload.get("scope") or "historical",
        data_state=payload.get("data_state") or "HISTORICAL",
        fingerprint=fingerprint,
        payload=payload,
    )


def _parse(value: Any):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
