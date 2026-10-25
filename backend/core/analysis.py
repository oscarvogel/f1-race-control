"""Analisis post-sesion: comparacion por sectores y campeonato.

Que se puede comparar con datos reales, y de donde sale cada cosa:

* **Sectores de la mejor vuelta.** El feed en vivo solo publica los sectores de
  la *ultima* vuelta de cada piloto, y ademas no suman su mejor vuelta: son
  los de la vuelta que acababa de hacer. Para comparar tiempos hay que usar
  OpenF1 (``/laps``), donde los sectores de la mejor vuelta **suman
  exactamente** el tiempo de esa vuelta.
* **Delta contra un piloto.** Se calcula sobre esos mismos sectores, asi que
  es comparable vuelta a vuelta (mismo circuito, mismo compuesto).
* **Delta contra otra sesion** (por ejemplo FP3 contra Clasificacion): misma
  fuente y mismo criterio, una mejor vuelta por piloto en cada sesion.
* **Campeonato.** Solo Jolpica publica la clasificacion de la temporada:
  OpenF1 no tiene endpoints de campeonato (``championship_drivers`` y
  ``championship_teams`` devuelven 404).

Reglas que se respetan aqui:

* Si un dato no existe, se devuelve ``None`` y se dibuja como "—". Nunca se
  convierte en cero.
* Si una fuente falla, se devuelve el motivo. No hay fallback silencioso ni
  datos simulados.
* Lo que se calcula a partir de datos de proveedor se cachea: OpenF1 limita la
  tasa por IP y la misma sesion no cambia una vez terminada.
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any

from django.conf import settings

from providers.base import ProviderError, format_lap_time
from providers.jolpica import JolpicaProvider
from providers.openf1 import OpenF1Provider

from .models import Session, SessionSnapshot

logger = logging.getLogger("racecenter.analysis")

# Una sesion terminada no cambia: la cache evita gastar la cuota de OpenF1.
RAW_TTL_SECONDS = 3600.0
CHAMPIONSHIP_TTL_SECONDS = 3600.0

# Proveedor "propio" para los datos derivados. Se aparta de "openf1" a
# proposito: el historico se lee por ``provider_id="openf1"`` y no debe
# confundirse con esto.
DERIVED_PROVIDER = "race-center-analysis"

# Version de los datos derivados guardados. Se sube cuando cambia el formato
# (por ejemplo, la edad del neumatico o el equipo de cada piloto): si no, la
# base seguiria sirviendo el payload viejo durante la hora de cache.
#
# v3: la vuelta que se analiza es la que cuenta para la clasificacion (el
# tiempo del ultimo segmento alcanzado), no la mas rapida registrada. Antes
# el analisis podia mostrar una vuelta anulada por la federacion.
CACHE_VERSION = "v3"

_RAW_CACHE: dict[str, dict[str, Any]] = {}
_CHAMPIONSHIP_CACHE: dict[str, dict[str, Any]] = {}


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _format_sector(seconds: float | None) -> str | None:
    """Tiempo de sector en el formato de la cronometracion (``25.310``)."""
    if seconds is None:
        return None
    return "%.3f" % seconds


def _format_delta(seconds: float | None) -> str | None:
    """Diferencia con signo: ``+0.123`` / ``-0.045``."""
    if seconds is None:
        return None
    return "%+.3f" % seconds


def _openf1_provider() -> OpenF1Provider:
    return OpenF1Provider(
        base_url=settings.OPENF1_BASE_URL,
        api_key=settings.OPENF1_API_KEY,
        live_enabled=settings.OPENF1_LIVE_ENABLED,
    )


def _jolpica_provider() -> JolpicaProvider:
    return JolpicaProvider(base_url=settings.JOLPICA_BASE_URL)


# --------------------------------------------------------------------------- #
# Datos crudos de una sesion (cacheados en memoria y en la base)
# --------------------------------------------------------------------------- #


def _load_raw_from_db(session_key: str) -> dict[str, Any] | None:
    """Datos crudos ya descargados de una sesion, si siguen en la base."""

    def _consultar() -> dict[str, Any] | None:
        session = Session.objects.filter(
            provider_id=DERIVED_PROVIDER,
            provider_session_id="%s-%s" % (session_key, CACHE_VERSION),
        ).first()
        if session is None:
            return None
        stored = (
            SessionSnapshot.objects.filter(session=session, scope="raw")
            .order_by("-created_at")
            .first()
        )
        if stored is None:
            return None
        return dict(stored.payload)

    return _consultar()


def _store_raw(session_key: str, payload: dict[str, Any]) -> None:
    """Guarda los datos crudos de la sesion para no volver a descargarlos."""

    def _guardar() -> None:
        session, _ = Session.objects.get_or_create(
            provider_id=DERIVED_PROVIDER,
            provider_session_id="%s-%s" % (session_key, CACHE_VERSION),
            defaults={
                "name": "Analisis: sesion %s" % session_key,
                "session_type": "analysis",
            },
        )
        SessionSnapshot.objects.create(
            session=session,
            provider_id=DERIVED_PROVIDER,
            scope="raw",
            data_state="HISTORICAL",
            fingerprint="%s-%s" % (session_key, payload.get("fetched_at")),
            payload=payload,
        )

    _guardar()


async def raw_session(session_key: str) -> dict[str, Any]:
    """Mejor vuelta por piloto (con sectores) y ficha de pilotos de una sesion.

    Se consulta una sola vez por sesion: el resultado se guarda en memoria y
    en la base, porque una sesion terminada no vuelve a cambiar.
    """
    key = str(session_key)
    now = time.monotonic()
    cached = _RAW_CACHE.get(key)
    if cached is not None and cached["expires"] > now:
        return cached["data"]

    stored = await asyncio.to_thread(_load_raw_from_db, key)
    if stored is not None:
        _RAW_CACHE[key] = {"expires": now + RAW_TTL_SECONDS, "data": stored}
        return stored

    provider = _openf1_provider()
    await provider.connect()
    try:
        session = await provider.get_session(key)
        if session is None:
            raise ProviderError("No existe la sesion %s en OpenF1." % key)
        laps = await provider.get_best_laps(key)
        drivers = await provider.get_drivers(key)
    finally:
        await provider.disconnect()

    payload = {
        "fetched_at": _stamp(),
        "session": {
            "provider_id": session.provider_id,
            "session_key": session.provider_session_id,
            "session_name": session.session_name,
            "session_type": session.session_type,
            "meeting_name": session.meeting_name,
            "official_name": session.official_name,
            "circuit_name": session.circuit_name,
            "season": session.season,
            "start_time_utc": (
                session.start_time_utc.isoformat() if session.start_time_utc else None
            ),
            "end_time_utc": session.end_time_utc.isoformat() if session.end_time_utc else None,
        },
        "laps": laps,
        "drivers": [
            {
                "driver_number": driver.number,
                "code": driver.code,
                "full_name": driver.full_name,
                "team": driver.team_name,
            }
            for driver in drivers
        ],
    }

    try:
        await asyncio.to_thread(_store_raw, key, payload)
    except Exception as exc:  # pragma: no cover - la cache en memoria alcanza
        logger.warning("No se pudo guardar el analisis crudo de %s: %s", key, exc)

    _RAW_CACHE[key] = {"expires": now + RAW_TTL_SECONDS, "data": payload}
    return payload


# --------------------------------------------------------------------------- #
# Ficha de pilotos (nombre, equipo y color de escuderia)
# --------------------------------------------------------------------------- #


def _live_driver_colours() -> dict[str, dict[str, Any]]:
    """Color de escuderia y nombre corto, tomados del feed en vivo.

    El feed de F1 publica ``TeamColour``; OpenF1 no. Como el color es un dato
    real del proveedor, se usa el que hay y no se inventa.
    """
    from .ingest import latest_snapshot

    colores: dict[str, dict[str, Any]] = {}
    snapshot = latest_snapshot() or {}
    for driver in snapshot.get("drivers") or []:
        numero = str(driver.get("number") or "")
        if not numero:
            continue
        colores[numero] = {
            "code": driver.get("code"),
            "full_name": driver.get("full_name"),
            "team": driver.get("team_name"),
            "team_colour": driver.get("team_colour"),
        }
    return colores


# --------------------------------------------------------------------------- #
# Analisis por sectores
# --------------------------------------------------------------------------- #


def _sector_list(lap: dict[str, Any]) -> list[dict[str, Any]]:
    """Los tres sectores de una vuelta, con el indice 0 = S1."""
    valores = [lap.get("sector_1"), lap.get("sector_2"), lap.get("sector_3")]
    return [{"index": index, "time": value} for index, value in enumerate(valores)]


def build_sector_analysis(
    session_key: str,
    reference_driver: str | None = None,
    compare_session_key: str | None = None,
) -> dict[str, Any]:
    """Compara la mejor vuelta de cada piloto, sector por sector.

    ``reference_driver`` es el piloto contra el que se mide el delta (si no se
    indica, se usa el mas rapido de la sesion). ``compare_session_key`` es la
    sesion contra la que se compara vuelta a vuelta (por ejemplo FP3).
    """
    raw = asyncio.run(raw_session(session_key))
    laps = list(raw.get("laps") or [])
    if not laps:
        return {
            "found": False,
            "session_key": str(session_key),
            "reason": "No hay vueltas registradas para la sesion %s." % session_key,
            "rows": [],
            "source": settings.HISTORICAL_PROVIDER,
        }

    compare_raw = None
    if compare_session_key and str(compare_session_key) != str(session_key):
        try:
            compare_raw = asyncio.run(raw_session(compare_session_key))
        except ProviderError as exc:
            logger.warning("No se pudo leer la sesion de comparacion %s: %s", compare_session_key, exc)
            compare_raw = None

    compare_laps: dict[str, dict[str, Any]] = {}
    if compare_raw is not None:
        for lap in compare_raw.get("laps") or []:
            numero = str(lap.get("driver_number") or "")
            if numero:
                compare_laps[numero] = lap

    # Ficha de pilotos: primero la de la sesion, luego el feed en vivo para el
    # color de escuderia.
    meta: dict[str, dict[str, Any]] = {}
    for driver in raw.get("drivers") or []:
        numero = str(driver.get("driver_number") or "")
        if numero:
            meta[numero] = dict(driver)
    for numero, info in _live_driver_colours().items():
        entry = meta.setdefault(numero, {})
        for campo in ("code", "full_name", "team"):
            if not entry.get(campo) and info.get(campo):
                entry[campo] = info[campo]
        if info.get("team_colour"):
            entry["team_colour"] = info["team_colour"]

    # Mas rapido de la sesion: es el cero de todas las diferencias.
    mas_rapido = min(laps, key=lambda item: item.get("lap_time") or 0.0)
    tiempo_mas_rapido = mas_rapido.get("lap_time")
    sectores_mas_rapidos = {s["index"]: s["time"] for s in _sector_list(mas_rapido)}

    referencia_numero = str(reference_driver or mas_rapido.get("driver_number") or "")
    fila_referencia = next(
        (lap for lap in laps if str(lap.get("driver_number")) == referencia_numero),
        None,
    )
    sectores_referencia = (
        {s["index"]: s["time"] for s in _sector_list(fila_referencia)}
        if fila_referencia
        else dict(sectores_mas_rapidos)
    )

    filas: list[dict[str, Any]] = []
    for lap in laps:
        numero = str(lap.get("driver_number") or "")
        info = meta.get(numero, {})
        tiempo = lap.get("lap_time")
        sectores = _sector_list(lap)

        for sector in sectores:
            mejor = sectores_mas_rapidos.get(sector["index"])
            referencia = sectores_referencia.get(sector["index"])
            sector["display"] = _format_sector(sector["time"])
            sector["delta_to_fastest"] = (
                round(sector["time"] - mejor, 3)
                if sector["time"] is not None and mejor is not None
                else None
            )
            sector["delta_to_reference"] = (
                round(sector["time"] - referencia, 3)
                if sector["time"] is not None and referencia is not None
                else None
            )
            sector["is_fastest"] = sector["time"] is not None and mejor is not None and sector["time"] == mejor

        fila: dict[str, Any] = {
            "driver_number": numero,
            "code": info.get("code"),
            "full_name": info.get("full_name"),
            "team": info.get("team"),
            "team_colour": info.get("team_colour"),
            "position": len(filas) + 1,
            "lap_number": lap.get("lap_number"),
            "lap_time": tiempo,
            "lap_time_display": format_lap_time(tiempo),
            "delta_to_fastest": (
                round(tiempo - tiempo_mas_rapido, 3)
                if tiempo is not None and tiempo_mas_rapido is not None
                else None
            ),
            "sectors": sectores,
            "compound": lap.get("compound"),
            "tyre_age": lap.get("tyre_age"),
            "is_pit_out_lap": lap.get("is_pit_out_lap"),
            "i1_speed": lap.get("i1_speed"),
            "i2_speed": lap.get("i2_speed"),
            "compare": None,
        }
        fila["delta_display"] = _format_delta(fila["delta_to_fastest"])

        if compare_laps:
            otra = compare_laps.get(numero)
            if otra is not None:
                tiempo_otra = otra.get("lap_time")
                sectores_otra = {s["index"]: s["time"] for s in _sector_list(otra)}
                fila["compare"] = {
                    "session_key": str(compare_session_key),
                    "lap_time": tiempo_otra,
                    "lap_time_display": format_lap_time(tiempo_otra),
                    "compound": otra.get("compound"),
                    # Positivo = en esta sesion fue mas lento que en la otra.
                    "delta_lap": (
                        round(tiempo - tiempo_otra, 3)
                        if tiempo is not None and tiempo_otra is not None
                        else None
                    ),
                    "sector_deltas": [
                        {
                            "index": sector["index"],
                            "delta": (
                                round(sector["time"] - sectores_otra.get(sector["index"]), 3)
                                if sector["time"] is not None
                                and sectores_otra.get(sector["index"]) is not None
                                else None
                            ),
                        }
                        for sector in sectores
                    ],
                }
                fila["compare"]["delta_display"] = _format_delta(fila["compare"]["delta_lap"])
            else:
                # El piloto no participated de la sesion de comparacion.
                fila["compare"] = {"session_key": str(compare_session_key), "lap_time": None}

        filas.append(fila)

    filas.sort(key=lambda item: (item.get("lap_time") is None, item.get("lap_time") or 0.0))

    return {
        "found": True,
        "generated_at": _stamp(),
        "session_key": str(session_key),
        "session": raw.get("session"),
        "source": settings.HISTORICAL_PROVIDER,
        "fastest": {
            "driver_number": str(mas_rapido.get("driver_number") or ""),
            "lap_time": tiempo_mas_rapido,
            "lap_time_display": format_lap_time(tiempo_mas_rapido),
        },
        "reference_driver": referencia_numero,
        "reference": (
            {
                "driver_number": str(fila_referencia.get("driver_number") or ""),
                "lap_time": fila_referencia.get("lap_time"),
                "lap_time_display": format_lap_time(fila_referencia.get("lap_time")),
            }
            if fila_referencia
            else None
        ),
        "compare_session": (
            {
                "session_key": str(compare_session_key),
                "session": compare_raw.get("session") if compare_raw else None,
                "found": bool(compare_laps),
            }
            if compare_session_key
            else None
        ),
        "rows": filas,
    }


# --------------------------------------------------------------------------- #
# Campeonato
# --------------------------------------------------------------------------- #


def _load_championship_from_db(season: int) -> dict[str, Any] | None:
    def _consultar() -> dict[str, Any] | None:
        session = Session.objects.filter(
            provider_id=DERIVED_PROVIDER,
            provider_session_id="championship-%s-%s" % (season, CACHE_VERSION),
        ).first()
        if session is None:
            return None
        stored = (
            SessionSnapshot.objects.filter(session=session, scope="championship")
            .order_by("-created_at")
            .first()
        )
        if stored is None:
            return None
        return dict(stored.payload)

    return _consultar()


def _store_championship(season: int, payload: dict[str, Any]) -> None:
    def _guardar() -> None:
        session, _ = Session.objects.get_or_create(
            provider_id=DERIVED_PROVIDER,
            provider_session_id="championship-%s-%s" % (season, CACHE_VERSION),
            defaults={"name": "Campeonato %s" % season, "session_type": "championship"},
        )
        SessionSnapshot.objects.create(
            session=session,
            provider_id=DERIVED_PROVIDER,
            scope="championship",
            data_state="HISTORICAL",
            fingerprint="%s-%s" % (season, payload.get("fetched_at")),
            payload=payload,
        )

    _guardar()


def current_season() -> int:
    """Temporada en curso, segun la sesion que se esta mostrando."""
    from .ingest import latest_snapshot

    snapshot = latest_snapshot() or {}
    temporada = ((snapshot.get("session") or {}).get("season")) or None
    if temporada:
        try:
            return int(temporada)
        except (TypeError, ValueError):
            pass
    return datetime.now(timezone.utc).year


def build_championship(season: int | None = None) -> dict[str, Any]:
    """Clasificacion del campeonato de pilotos y de constructores.

    La fuente es Jolpica. El dato es real, pero hay que decirlo bien: la
    tabla refleja **la ultima ronda ya contabilizada**. Austin es la ronda 18
    de 2026 y todavia no suma puntos hasta que se corre la carrera.
    """
    temporada = int(season or current_season())
    now = time.monotonic()
    cached = _CHAMPIONSHIP_CACHE.get(str(temporada))
    if cached is not None and cached["expires"] > now:
        return cached["data"]

    stored = _load_championship_from_db(temporada)
    if stored is None:
        provider = _jolpica_provider()
        tabla = asyncio.run(provider.get_championship(temporada))
        drivers = tabla.get("drivers") or []
        teams = tabla.get("teams") or []

        lider = drivers[0]["points"] if drivers else None
        lider_equipo = teams[0]["points"] if teams else None
        for piloto in drivers:
            piloto["gap_to_leader"] = (
                piloto["points"] - lider if lider is not None else None
            )
        for equipo in teams:
            equipo["gap_to_leader"] = (
                equipo["points"] - lider_equipo if lider_equipo is not None else None
            )

        stored = {
            "found": True,
            "fetched_at": _stamp(),
            "season": tabla.get("season") or temporada,
            "round": tabla.get("round"),
            "source": settings.METADATA_PROVIDER,
            "drivers": drivers,
            "teams": teams,
        }
        try:
            _store_championship(temporada, stored)
        except Exception as exc:  # pragma: no cover
            logger.warning("No se pudo guardar el campeonato %s: %s", temporada, exc)

    stored["note"] = (
        "Clasificacion tras la ronda %s: la ronda %s (Austin) todavia no suma puntos "
        "hasta que se disputa la carrera."
        % (stored.get("round"), (stored.get("round") or 0) + 1)
    )
    _CHAMPIONSHIP_CACHE[str(temporada)] = {
        "expires": now + CHAMPIONSHIP_TTL_SECONDS,
        "data": stored,
    }
    return stored
