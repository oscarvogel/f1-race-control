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
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from django.conf import settings

from providers.base import ProviderError, format_lap_time, to_float, to_int
from providers.jolpica import JolpicaProvider
from providers.openf1 import OpenF1Provider, deleted_laps

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
# v4: se agregan las vueltas completas, los stints y los cambios de posicion
# al payload crudo (para la evolucion de posiciones y la estrategia).
#
# v5: se agrega el control de carrera, que es de donde sale que vueltas
# anulo la federacion (OpenF1 ya no las marca en /laps).
# v6: la mejor vuelta de una carrera ya no toma el tiempo total de la
# carrera como si fuera una vuelta.
CACHE_VERSION = "v6"

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

    Ademas trae las vueltas completas, los stints y los cambios de posicion:
    son los datos que necesitan la evolucion de posiciones y la estrategia de
    neuumaticos.

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
        # Las vueltas crudas se piden una vez y se reusan: la mejor vuelta de
        # cada piloto sale de ahi, y tambien hacen falta para el cruce con los
        # stints y con los cambios de posicion.
        laps_rows = await provider.get_raw_laps(key)
        laps = await provider.get_best_laps(key, laps_rows=laps_rows)
        drivers = await provider.get_drivers(key)
        stints = await provider.get_raw_stints(key)
        positions = await provider.get_position_history(key)
        # El control de carrera dice que vueltas anulo la federacion: en los
        # datos de 2026 /laps ya no las marca con `deleted`.
        race_control = await provider.get_race_control(key)
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
        "all_laps": [
            {
                "driver_number": str(row.get("driver_number")),
                "lap_number": to_int(row.get("lap_number")),
                "lap_duration": to_float(row.get("lap_duration")),
                "date_start": row.get("date_start"),
                "is_pit_out_lap": row.get("is_pit_out_lap"),
                "sector_1": to_float(row.get("duration_sector_1")),
                "sector_2": to_float(row.get("duration_sector_2")),
                "sector_3": to_float(row.get("duration_sector_3")),
            }
            for row in laps_rows
        ],
        "stints": [
            {
                "driver_number": str(row.get("driver_number")),
                "stint_number": to_int(row.get("stint_number")),
                "compound": row.get("compound"),
                "lap_start": to_int(row.get("lap_start")),
                "lap_end": to_int(row.get("lap_end")),
                "tyre_age_at_start": to_int(row.get("tyre_age_at_start")),
            }
            for row in stints
        ],
        "positions": positions,
        "race_control": [
            {"message": str(getattr(evento, "message", "") or "")}
            for evento in race_control
        ],
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


# Una vuelta de boxes (entrada o salida) es mucho mas lenta que una vuelta de
# carrera. El margen del 15% sale de los datos reales: en Austin 2026 las
# vueltas de boxes tardan 30 s mas que las de carrera.
LIMITE_VUELTA_DE_BOXES = 1.15


# --------------------------------------------------------------------------- #
# Evolucion de posiciones por vuelta
# --------------------------------------------------------------------------- #

# Margen del cruce vuelta/posicion. Medido con los datos reales de Austin
# 2026: el cambio de posicion se publica en el mismo instante en que arranca
# la vuelta siguiente, con un desfasase de ~70 ms. El margen de un segundo
# cubre esa diferencia sin llegar aopsear un cambio ajeno.
POSITION_CROSS_TOLERANCE_SECONDS = 1.0


def _parse_moment(iso: Any) -> datetime | None:
    """Una fecha ISO de OpenF1 como datetime (o None si no se puede leer)."""
    if not iso:
        return None
    try:
        return datetime.fromisoformat(str(iso))
    except ValueError:
        return None


def _driver_meta(raw: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Ficha de pilotos de la sesion, con el color de escuderia del feed."""
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
            entry["team_colour"] = info.get("team_colour")
    return meta


def build_position_history(session_key: str) -> dict[str, Any]:
    """La posicion de cada piloto al final de cada vuelta.

    OpenF1 publica ``/position``: una fila por **cambio** de posicion, con el
    instante en que ocurrio (el cruce de linea). No trae el numero de vuelta,
    asi que se cruza con ``/laps``, que si lo trae.

    El cruce es directo porque el cambio de posicion se publica en el mismo
    instante en que **arranca la vuelta siguiente**: la posicion al final de
    la vuelta N es el ultimo cambio publicado hasta el comienzo de la vuelta
    N+1. Medido con los datos reales de Austin 2026, el desfasase entre el
    cruce de linea y el cambio de posicion es de ~70 ms.

    ``positions_gained`` y ``positions_lost`` se cuentan de una vuelta a otra
    (que es lo que muestra el grafico): un cambio que ocurre dentro de una
    vuelta queda reflejado en la posicion de fin de esa vuelta.
    """
    raw = asyncio.run(raw_session(session_key))
    vueltas = list(raw.get("all_laps") or [])
    cambios = list(raw.get("positions") or [])
    if not vueltas or not cambios:
        return {
            "found": False,
            "session_key": str(session_key),
            "reason": "No hay datos de posiciones para la sesion %s." % session_key,
            "rows": [],
            "source": settings.HISTORICAL_PROVIDER,
        }

    meta = _driver_meta(raw)

    cambios_por_piloto: dict[str, list[tuple[datetime, int]]] = {}
    for cambio in cambios:
        momento = _parse_moment(cambio.get("date"))
        posicion = cambio.get("position")
        if momento is None or posicion is None:
            continue
        numero = str(cambio.get("driver_number") or "")
        if not numero:
            continue
        cambios_por_piloto.setdefault(numero, []).append((momento, int(posicion)))
    for lista in cambios_por_piloto.values():
        lista.sort(key=lambda item: item[0])

    vueltas_por_piloto: dict[str, list[dict[str, Any]]] = {}
    for vuelta in vueltas:
        numero = str(vuelta.get("driver_number") or "")
        if not numero or vuelta.get("lap_number") is None:
            continue
        vueltas_por_piloto.setdefault(numero, []).append(vuelta)
    for lista in vueltas_por_piloto.values():
        lista.sort(key=lambda item: item.get("lap_number") or 0)

    filas: list[dict[str, Any]] = []
    for numero, propias in vueltas_por_piloto.items():
        propios_cambios = cambios_por_piloto.get(numero) or []
        if not propios_cambios:
            continue
        info = meta.get(numero, {})
        puntos: list[dict[str, Any]] = []
        ganadas = 0
        perdidas = 0
        anterior: int | None = None
        for indice, vuelta in enumerate(propias):
            limite = None
            if indice + 1 < len(propias):
                limite = _parse_moment(propias[indice + 1].get("date_start"))
            posicion: int | None = None
            for momento, valor in propios_cambios:
                if limite is None:
                    # Ultima vuelta: manda el ultimo cambio de la sesion.
                    posicion = valor
                    continue
                if momento <= limite + timedelta(seconds=POSITION_CROSS_TOLERANCE_SECONDS):
                    posicion = valor
                else:
                    break
            if posicion is not None and anterior is not None:
                if posicion < anterior:
                    ganadas += 1
                elif posicion > anterior:
                    perdidas += 1
            if posicion is not None:
                anterior = posicion
            puntos.append({"lap": vuelta.get("lap_number"), "position": posicion})
        filas.append(
            {
                "driver_number": numero,
                "code": info.get("code"),
                "full_name": info.get("full_name"),
                "team": info.get("team"),
                "team_colour": info.get("team_colour"),
                "final_position": puntos[-1]["position"] if puntos else None,
                "positions_gained": ganadas,
                "positions_lost": perdidas,
                "points": puntos,
            }
        )

    filas.sort(key=lambda item: (item.get("final_position") is None, item.get("final_position") or 99))

    return {
        "found": True,
        "generated_at": _stamp(),
        "session_key": str(session_key),
        "session": raw.get("session"),
        "source": settings.HISTORICAL_PROVIDER,
        "rows": filas,
    }


# --------------------------------------------------------------------------- #
# Estrategia de neumaticos
# --------------------------------------------------------------------------- #


def build_strategy(session_key: str) -> dict[str, Any]:
    """La estrategia de neumaticos de cada piloto: stints, paradas y vueltas.

    Un stint es un tramo de vueltas con el mismo compuesto. De cada stint se
    dice el compuesto, de que vuelta a que vuelta, cuantas vueltas, la edad del
    neumatico al empezar y cual fue su mejor vuelta **de carrera**.

    Tres cosas hay que tener en cuenta para que los numeros sean los
    oficiales:

    * El compuesto sale de ``/stints``: en los datos de 2026 el endpoint de
      vueltas ya no trae el compuesto ni la edad del neumatico.
    * Las vueltas anuladas por la federacion (que publica el control de
      carrera) **no cuentan**. Se detectan por su tiempo exacto: el numero de
      vuelta del mensaje es el del feed, que no coincide con el de OpenF1.
    * Dentro de un stint estan la vuelta de salida de boxes (marcada con
      ``is_pit_out_lap``) y la de vuelta a los boxes. Ninguna de las dos es una
      vuelta de carrera: son mucho mas lentas que la mejor vuelta del piloto
      (una vuelta de boxes con el pit lane de Austin son mas de 30 s mas
      lenta), asi que se dejan afuera al buscar la mejor vuelta del tramo.
    """
    raw = asyncio.run(raw_session(session_key))
    vueltas = list(raw.get("all_laps") or [])
    stints = list(raw.get("stints") or [])
    if not stints:
        return {
            "found": False,
            "session_key": str(session_key),
            "reason": "No hay datos de neumaticos para la sesion %s." % session_key,
            "rows": [],
            "source": settings.HISTORICAL_PROVIDER,
        }

    meta = _driver_meta(raw)

    # Vueltas anuladas por la federacion: no cuentan (no existen en la
    # clasificacion oficial), asi que no se usan para el mejor tiempo.
    anuladas_tiempo = deleted_laps(raw.get("race_control") or [])
    anuladas_vuelta: set[tuple[str, int]] = set()

    vueltas_por_piloto: dict[str, list[dict[str, Any]]] = {}
    for vuelta in vueltas:
        numero = str(vuelta.get("driver_number") or "")
        if not numero or vuelta.get("lap_number") is None:
            continue
        vueltas_por_piloto.setdefault(numero, []).append(vuelta)
    for lista in vueltas_por_piloto.values():
        lista.sort(key=lambda item: item.get("lap_number") or 0)

    stints_por_piloto: dict[str, list[dict[str, Any]]] = {}
    for stint in stints:
        numero = str(stint.get("driver_number") or "")
        if not numero:
            continue
        stints_por_piloto.setdefault(numero, []).append(stint)
    for lista in stints_por_piloto.values():
        lista.sort(key=lambda item: (item.get("stint_number") or 0, item.get("lap_start") or 0))

    # La mejor vuelta oficial de cada piloto (la que cuenta para la
    # clasificacion), ya resuelta por el proveedor.
    oficial_por_piloto = {
        str(lap.get("driver_number") or ""): lap
        for lap in (raw.get("laps") or [])
        if lap.get("driver_number") is not None
    }

    filas: list[dict[str, Any]] = []
    for numero, propios in stints_por_piloto.items():
        info = meta.get(numero, {})
        propias_vueltas = vueltas_por_piloto.get(numero) or []
        ultima_vuelta = propias_vueltas[-1].get("lap_number") if propias_vueltas else None

        def _anulada(vuelta: dict[str, Any]) -> bool:
            """Si esa vuelta la anulo la federacion (no cuenta)."""
            if (numero, vuelta.get("lap_number")) in anuladas_vuelta:
                return True
            # El tiempo llega con dos nombres distintos segun de donde venga la
            # vuelta: `lap_duration` en las filas crudas y `lap_time` en la
            # mejor vuelta oficial.
            tiempo = vuelta.get("lap_duration")
            if tiempo is None:
                tiempo = vuelta.get("lap_time")
            if tiempo is None:
                return False
            return (numero, round(float(tiempo), 3)) in anuladas_tiempo

        # La mejor vuelta del piloto: la **oficial de clasificacion** (la del
        # ultimo segmento alcanzado), no la mas rapida registrada.
        oficial = oficial_por_piloto.get(numero)
        referencia: float | None = None
        if oficial is not None and not _anulada(oficial):
            referencia = oficial.get("lap_time")
        if referencia is None:
            candidatas = [
                v for v in propias_vueltas
                if v.get("lap_duration") is not None and not _anulada(v)
            ]
            if candidatas:
                referencia = min(
                    candidatas, key=lambda v: v["lap_duration"]
                )["lap_duration"]

        # Una vuelta de boxes (entrada o salida) es mucho mas lenta que una
        # vuelta de carrera: no cuenta como mejor vuelta del tramo.
        limite_boxes = referencia * LIMITE_VUELTA_DE_BOXES if referencia else None

        tramos: list[dict[str, Any]] = []
        for stint in propios:
            inicio = stint.get("lap_start")
            fin = stint.get("lap_end")
            if fin is None:
                fin = ultima_vuelta
            del_stint = [
                vuelta for vuelta in propias_vueltas
                if vuelta.get("lap_number") is not None
                and (inicio is None or vuelta["lap_number"] >= inicio)
                and (fin is None or vuelta["lap_number"] <= fin)
            ]
            de_carrera = [
                vuelta for vuelta in del_stint
                if vuelta.get("lap_duration") is not None
                and not _anulada(vuelta)
                and not vuelta.get("is_pit_out_lap")
                and (limite_boxes is None or vuelta["lap_duration"] <= limite_boxes)
            ]
            mejor = min(de_carrera, key=lambda v: v["lap_duration"]) if de_carrera else None
            tiempo = mejor.get("lap_duration") if mejor else None
            tramos.append(
                {
                    "stint_number": stint.get("stint_number"),
                    "compound": stint.get("compound"),
                    "lap_start": inicio,
                    "lap_end": stint.get("lap_end"),
                    "laps": len(del_stint),
                    "racing_laps": len(de_carrera),
                    "tyre_age_at_start": stint.get("tyre_age_at_start"),
                    "is_out_lap": bool(del_stint and del_stint[0].get("is_pit_out_lap")),
                    "best_lap_time": tiempo,
                    "best_lap_time_display": format_lap_time(tiempo),
                    "best_lap_number": mejor.get("lap_number") if mejor else None,
                }
            )

        mejor_sesion = oficial if (oficial is not None and not _anulada(oficial)) else None
        if mejor_sesion is None:
            candidatas = [
                v for v in propias_vueltas
                if v.get("lap_duration") is not None and not _anulada(v)
            ]
            if candidatas:
                mejor_sesion = min(candidatas, key=lambda v: v["lap_duration"])
        tiempo_sesion = None
        if mejor_sesion is not None:
            tiempo_sesion = mejor_sesion.get("lap_time")
            if tiempo_sesion is None:
                tiempo_sesion = mejor_sesion.get("lap_duration")

        filas.append(
            {
                "driver_number": numero,
                "code": info.get("code"),
                "full_name": info.get("full_name"),
                "team": info.get("team"),
                "team_colour": info.get("team_colour"),
                "stints": tramos,
                "stint_count": len(tramos),
                # Cambios de compuesto: en una carrera, las paradas en boxes.
                "stops": max(len(tramos) - 1, 0),
                "total_laps": len(propias_vueltas),
                "compounds": [tramo.get("compound") for tramo in tramos],
                "best_lap_time": tiempo_sesion,
                "best_lap_time_display": format_lap_time(tiempo_sesion),
                "best_lap_number": (
                    mejor_sesion.get("lap_number") if mejor_sesion else None
                ),
            }
        )

    filas.sort(key=lambda item: (item.get("best_lap_time") is None, item.get("best_lap_time") or 0.0))

    return {
        "found": True,
        "generated_at": _stamp(),
        "session_key": str(session_key),
        "session": raw.get("session"),
        "source": settings.HISTORICAL_PROVIDER,
        "rows": filas,
    }
