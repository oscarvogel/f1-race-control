"""Prevision meteorologica del circuito.

El feed de cronometraje de F1 da el clima **actual** del circuito y OpenF1
guarda el clima **historico** de una sesion. Ninguno de los dos dice que va
a pasar en la sesion que viene, que es justo lo que uno quiere saber antes
de que empiece.

Para eso se usa **Open-Meteo** (https://open-meteo.com), que es un servicio
publico, sin clave y sin suscripcion: devuelve la prevision horaria de
temperatura, probabilidad de lluvia, precipitacion, codigo de tiempo y viento
para unas coordenadas.

Reglas de este modulo:

* La prevision **nunca** se mezcla con el clima observado. Cada panel dice
  de que fuente sale cada dato.
* Las coordenadas son **datos reales** de Jolpica (Ergast), no aproximadas
  a mano: el circuito de Austin es ``circuitId "americas"`` en ese servicio.
* Si el circuito no esta en el mapa de coordenadas, no hay prevision. No se
  inventa ni se busca una ciudad parecida.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger("racecenter.weather")

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"

# Coordenadas de circuitos, con su origen.
#
# ``circuit_key`` es el identificador estable de F1 para cada trazado.
# ``source`` deja constancia de donde salio cada par, para no dejar coordenadas
# sin respaldo en el codigo.
CIRCUIT_COORDINATES: dict[int, dict[str, Any]] = {
    9: {
        "circuit_key": 9,
        "circuit_name": "Austin",
        "latitude": 30.1328,
        "longitude": -97.6411,
        "timezone": "America/Chicago",
        "source": "Jolpica /circuits (circuitId 'americas', Circuit of the Americas)",
    },
}

# La prevision no cambia segundo a segundo: se cachea para no pegarle al
# servicio en cada refresco del dashboard.
_CACHE: dict[str, dict[str, Any]] = {"key": None, "expires": 0.0, "data": None}
CACHE_TTL_SECONDS = 900.0

# Codigos de tiempo de la OMM (los que usa Open-Meteo), en espanol.
WEATHER_CODES: dict[int, str] = {
    0: "Despejado",
    1: "Mayormente despejado",
    2: "Parcialmente nublado",
    3: "Nublado",
    45: "Niebla",
    48: "Niebla con escarcha",
    51: "Llovizna ligera",
    53: "Llovizna",
    55: "Llovizna intensa",
    56: "Llovizna helada ligera",
    57: "Llovizna helada",
    61: "Lluvia ligera",
    63: "Lluvia",
    65: "Lluvia intensa",
    66: "Lluvia helada ligera",
    67: "Lluvia helada",
    71: "Nieve ligera",
    73: "Nieve",
    75: "Nieve intensa",
    77: "Granos de nieve",
    80: "Chubascos ligeros",
    81: "Chubascos",
    82: "Chubascos violentos",
    85: "Chubascos de nieve ligeros",
    86: "Chubascos de nieve",
    95: "Tormenta",
    96: "Tormenta con granizo",
    99: "Tormenta fuerte con granizo",
}


def describe_weather_code(code: int | None) -> str:
    if code is None:
        return "Sin dato"
    return WEATHER_CODES.get(int(code), "Desconocido")


def circuit_coordinates(circuit_key: int | None) -> dict[str, Any] | None:
    """Coordenadas conocidas de un circuito, o ``None`` si no las hay."""
    if circuit_key is None:
        return None
    return CIRCUIT_COORDINATES.get(int(circuit_key))


def _to_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalise_hourly(payload: dict[str, Any]) -> list[dict[str, Any]]:
    hourly = payload.get("hourly") or {}
    times = hourly.get("time") or []
    temperature = hourly.get("temperature_2m") or []
    probability = hourly.get("precipitation_probability") or []
    precipitation = hourly.get("precipitation") or []
    codes = hourly.get("weather_code") or []
    wind = hourly.get("wind_speed_10m") or []
    gusts = hourly.get("wind_gusts_10m") or []

    rows: list[dict[str, Any]] = []
    for index, stamp in enumerate(times):
        def pick(values: list[Any]) -> Any:
            return values[index] if index < len(values) else None

        code = pick(codes)
        rows.append(
            {
                "time_utc": stamp,
                "temperature": _to_float(pick(temperature)),
                "precipitation_probability": _to_float(pick(probability)),
                "precipitation": _to_float(pick(precipitation)),
                "weather_code": int(code) if code is not None else None,
                "condition": describe_weather_code(int(code) if code is not None else None),
                "wind_speed": _to_float(pick(wind)),
                "wind_gusts": _to_float(pick(gusts)),
            }
        )
    return rows


def _summarise(hours: list[dict[str, Any]]) -> dict[str, Any]:
    """Resumen de una ventana horaria: lo que de verdad se pregunta."""
    temperatures = [h["temperature"] for h in hours if h["temperature"] is not None]
    probabilities = [
        h["precipitation_probability"] for h in hours
        if h["precipitation_probability"] is not None
    ]
    winds = [h["wind_speed"] for h in hours if h["wind_speed"] is not None]
    codes = [h["weather_code"] for h in hours if h["weather_code"] is not None]

    condition = "Sin dato"
    if codes:
        # El codigo mas frecuente es una buena aproximacion del estado general.
        condition = describe_weather_code(max(set(codes), key=codes.count))

    return {
        "temperature_min": min(temperatures) if temperatures else None,
        "temperature_max": max(temperatures) if temperatures else None,
        "temperature_mean": round(sum(temperatures) / len(temperatures), 1) if temperatures else None,
        "precipitation_probability_max": max(probabilities) if probabilities else None,
        "precipitation_total": round(sum(h["precipitation"] or 0 for h in hours), 2),
        "wind_speed_max": max(winds) if winds else None,
        "condition": condition,
        "hours": len(hours),
    }


async def fetch_forecast(
    circuit_key: int | None,
    hours: int = 48,
    force: bool = False,
) -> dict[str, Any] | None:
    """Prevision horaria del circuito.

    Devuelve ``None`` si no hay coordenadas conocidas para ese circuito: es
    preferible no mostrar prevision antes que mostrar la de otro lugar.
    """
    coordinates = circuit_coordinates(circuit_key)
    if coordinates is None:
        return None

    cache_key = "%s|%s" % (coordinates["circuit_key"], hours)
    now = time.monotonic()
    if (
        not force
        and _CACHE["key"] == cache_key
        and _CACHE["expires"] > now
        and _CACHE["data"] is not None
    ):
        return _CACHE["data"]

    params = {
        "latitude": coordinates["latitude"],
        "longitude": coordinates["longitude"],
        "hourly": (
            "temperature_2m,precipitation_probability,precipitation,"
            "weather_code,wind_speed_10m,wind_gusts_10m"
        ),
        "forecast_days": 3,
        "timezone": "UTC",
    }
    url = "%s?%s" % (OPEN_METEO_URL, "&".join("%s=%s" % (k, v) for k, v in params.items()))

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        logger.warning("No se pudo obtener la prevision de Open-Meteo: %s", exc)
        return None

    rows = _normalise_hourly(payload)
    # La prevision arranca "ahora": se recorta lo que ya paso.
    current = datetime.now(timezone.utc)
    upcoming: list[dict[str, Any]] = []
    for row in rows:
        try:
            stamp = datetime.fromisoformat(str(row["time_utc"])).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if stamp >= current:
            upcoming.append(row)
        if len(upcoming) >= hours:
            break

    if not upcoming:
        return None

    result = {
        "provider_id": "open_meteo",
        "display_name": "Open-Meteo (prevision del circuito)",
        "source_url": url,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "circuit_key": coordinates["circuit_key"],
        "circuit_name": coordinates["circuit_name"],
        "latitude": coordinates["latitude"],
        "longitude": coordinates["longitude"],
        "timezone": coordinates["timezone"],
        "coordinates_source": coordinates["source"],
        "summary": _summarise(upcoming),
        "hourly": upcoming,
    }

    _CACHE["key"] = cache_key
    _CACHE["expires"] = now + CACHE_TTL_SECONDS
    _CACHE["data"] = result
    return result


def forecast_window(
    forecast: dict[str, Any] | None,
    start_utc: datetime | None,
    end_utc: datetime | None,
) -> dict[str, Any] | None:
    """Parte de la prevision que cubre una sesion.

    Es la pregunta util: "con estas condiciones va a correr la clasificacion".
    """
    if not forecast or start_utc is None:
        return None

    rows = forecast.get("hourly") or []
    selected: list[dict[str, Any]] = []
    for row in rows:
        try:
            stamp = datetime.fromisoformat(str(row["time_utc"])).replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            continue
        if stamp < start_utc:
            continue
        if end_utc is not None and stamp > end_utc:
            break
        selected.append(row)

    if not selected:
        return None

    return {
        "start_utc": start_utc.isoformat(),
        "end_utc": end_utc.isoformat() if end_utc else None,
        "summary": _summarise(selected),
        "hourly": selected,
    }
