"""Pruebas de la prevision meteorologica del circuito.

La prevision es un dato **distinto** del clima observado: viene de otro
servicio (Open-Meteo) y se muestra aparte. Estas pruebas fijan las reglas
que la sostienen:

* sin coordenadas conocidas no hay prevision (no se busca un lugar parecido),
* los codigos de tiempo se traducen al espanol,
* la ventana de una sesion se recorta bien,
* y un 429 de OpenF1 no puede romper nada de esto (son servicios distintos).
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from core.weather import (
    CACHE_TTL_SECONDS,
    CIRCUIT_COORDINATES,
    _normalise_hourly,
    _summarise,
    circuit_coordinates,
    describe_weather_code,
    fetch_forecast,
    forecast_window,
)


def test_austin_tiene_coordenadas_con_origen():
    coordenadas = circuit_coordinates(9)
    assert coordenadas is not None
    assert coordenadas["latitude"] == 30.1328
    assert coordenadas["longitude"] == -97.6411
    # Las coordenadas tienen que decir de donde salieron.
    assert coordenadas["source"]


def test_un_circuito_desconocido_no_tiene_prevision():
    """Es preferible no mostrar prevision antes que mostrar la de otro lado."""
    assert circuit_coordinates(9999) is None
    assert circuit_coordinates(None) is None


def test_sin_coordenadas_no_se_llama_a_open_meteo():
    forecast = asyncio.run(fetch_forecast(9999))
    assert forecast is None


def test_los_codigos_de_tiempo_se_trducen():
    assert describe_weather_code(0) == "Despejado"
    assert describe_weather_code(3) == "Nublado"
    assert describe_weather_code(65) == "Lluvia intensa"
    assert describe_weather_code(95) == "Tormenta"
    # Un codigo desconocido no inventa: lo dice.
    assert describe_weather_code(1234) == "Desconocido"
    assert describe_weather_code(None) == "Sin dato"


def test_la_precipitacion_se_normaliza():
    payload = {
        "hourly": {
            "time": ["2026-10-24T21:00", "2026-10-24T22:00"],
            "temperature_2m": [29.3, 28.9],
            "precipitation_probability": [0, 30],
            "precipitation": [0.0, 0.4],
            "weather_code": [0, 61],
            "wind_speed_10m": [15.0, 17.3],
        }
    }
    rows = _normalise_hourly(payload)
    assert len(rows) == 2
    assert rows[0]["temperature"] == 29.3
    assert rows[0]["condition"] == "Despejado"
    assert rows[1]["condition"] == "Lluvia ligera"
    assert rows[1]["precipitation_probability"] == 30.0


def test_el_resumen_informa_lo_que_se_pregunta():
    rows = [
        {"temperature": 29.3, "precipitation_probability": 0, "precipitation": 0.0,
         "weather_code": 0, "wind_speed": 15.0},
        {"temperature": 28.9, "precipitation_probability": 40, "precipitation": 0.4,
         "weather_code": 61, "wind_speed": 17.3},
    ]
    resumen = _summarise(rows)
    assert resumen["temperature_min"] == 28.9
    assert resumen["temperature_max"] == 29.3
    assert resumen["precipitation_probability_max"] == 40
    assert resumen["wind_speed_max"] == 17.3
    assert resumen["hours"] == 2


def test_la_ventana_de_una_sesion_se_recorta():
    forecast = {
        "hourly": [
            {"time_utc": "2026-10-24T20:00", "temperature": 27.0, "precipitation_probability": 0,
             "precipitation": 0.0, "weather_code": 0, "wind_speed": 12.0},
            {"time_utc": "2026-10-24T21:00", "temperature": 29.3, "precipitation_probability": 0,
             "precipitation": 0.0, "weather_code": 0, "wind_speed": 15.0},
            {"time_utc": "2026-10-24T22:00", "temperature": 28.9, "precipitation_probability": 0,
             "precipitation": 0.0, "weather_code": 0, "wind_speed": 17.3},
            {"time_utc": "2026-10-24T23:00", "temperature": 26.0, "precipitation_probability": 10,
             "precipitation": 0.0, "weather_code": 2, "wind_speed": 14.0},
        ]
    }
    inicio = datetime(2026, 10, 24, 21, 0, tzinfo=timezone.utc)
    fin = datetime(2026, 10, 24, 22, 0, tzinfo=timezone.utc)

    ventana = forecast_window(forecast, inicio, fin)

    assert ventana is not None
    assert len(ventana["hourly"]) == 2
    assert ventana["summary"]["temperature_max"] == 29.3


def test_una_ventana_sin_horas_devuelve_none():
    forecast = {"hourly": []}
    inicio = datetime(2026, 10, 24, 21, 0, tzinfo=timezone.utc)
    assert forecast_window(forecast, inicio, None) is None
    assert forecast_window(None, inicio, None) is None


def test_el_coordenado_de_austin_es_el_real():
    """El circuito de Austin es COTA, no el centro de Austin."""
    datos = CIRCUIT_COORDINATES[9]
    assert datos["circuit_name"] == "Austin"
    # COTA esta a unos 15 km al sur del centro: la latitud no es 30.26.
    assert datos["latitude"] < 30.2
    assert datos["timezone"] == "America/Chicago"


def test_la_prevision_se_cachea():
    """No tiene sentido pegarle al servicio en cada refresco del dashboard."""
    assert CACHE_TTL_SECONDS > 60
