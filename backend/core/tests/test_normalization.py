"""Pruebas del normalizador de datos (sin red, con fixtures sinteticos).

Los fixtures de este archivo **nunca** se muestran en el dashboard real: solo
existen aqui, en el entorno de pruebas.
"""

from __future__ import annotations

import pytest

from providers.base import (
    ProviderCapabilities,
    TimingEntry,
    UnsupportedCapability,
    format_lap_time,
    parse_lap_time,
    parse_timestamp,
    sort_timing_entries,
    to_float,
    to_int,
)


# --------------------------------------------------------------------------- #
# 1. Parseo de tiempos de vuelta
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1:35.706", 95.706),
        ("1:35", 95.0),
        ("95.706", 95.706),
        ("2:01.234", 121.234),
        ("0:59.999", 59.999),
    ],
)
def test_parse_lap_time(raw, expected):
    assert parse_lap_time(raw) == pytest.approx(expected)


def test_parse_lap_time_preserva_el_sin_dato():
    """Un valor ausente NO puede convertirse en 0: 0 es una lectura valida."""
    for value in (None, "", "   ", "abc"):
        assert parse_lap_time(value) is None


def test_format_lap_time_ida_y_vuelta():
    assert format_lap_time(95.706) == "1:35.706"
    assert format_lap_time(parse_lap_time("1:35.706")) == "1:35.706"
    assert format_lap_time(None) is None


def test_to_float_e_to_int_preservan_none():
    assert to_float("") is None
    assert to_float("abc") is None
    assert to_float("28.4") == pytest.approx(28.4)
    assert to_int(None) is None
    assert to_int("3") == 3
    assert to_int("3.7") == 3


# --------------------------------------------------------------------------- #
# 2. Timestamps
# --------------------------------------------------------------------------- #


def test_parse_timestamp_con_zulu():
    parsed = parse_timestamp("2026-10-24T18:58:14.771Z")
    assert parsed is not None
    assert parsed.year == 2026 and parsed.month == 10 and parsed.day == 24
    assert parsed.tzinfo is not None


def test_parse_timestamp_sin_zulu_se_asume_utc():
    parsed = parse_timestamp("2026-10-24T17:47:11")
    assert parsed is not None
    assert parsed.tzinfo is not None
    assert parsed.utcoffset().total_seconds() == 0


def test_parse_timestamp_invalido():
    assert parse_timestamp(None) is None
    assert parse_timestamp("") is None
    assert parse_timestamp("no-es-fecha") is None


# --------------------------------------------------------------------------- #
# 3. Orden de la clasificacion
# --------------------------------------------------------------------------- #


def _entry(number: str, position: int | None) -> TimingEntry:
    return TimingEntry(provider_id="test", driver_number=number, position=position)


def test_clasificacion_por_posicion():
    entries = [_entry("44", 1), _entry("3", 2), _entry("16", 3)]
    ordered = sort_timing_entries(entries)
    assert [e.driver_number for e in ordered] == ["44", "3", "16"]


def test_pilotos_sin_posicion_van_al_final():
    entries = [_entry("1", None), _entry("44", 1), _entry("3", 2)]
    ordered = sort_timing_entries(entries)
    assert [e.driver_number for e in ordered] == ["44", "3", "1"]


def test_orden_estable_entre_pilotos_sin_posicion():
    entries = [_entry("1", None), _entry("3", None)]
    ordered = sort_timing_entries(entries)
    assert [e.driver_number for e in ordered] == ["1", "3"]


# --------------------------------------------------------------------------- #
# 4. Capacidades
# --------------------------------------------------------------------------- #


def test_capacidades_se_serializan():
    caps = ProviderCapabilities(provider_id="x", live=True, telemetry=False)
    data = caps.as_dict()
    assert data["provider_id"] == "x"
    assert data["live"] is True
    assert data["telemetry"] is False


def test_proveedor_sin_capacidad_lanza_unsupported():
    """Un proveedor que no puede dar algo lo declara, no lo inventa."""
    from providers.jolpica import JolpicaProvider

    provider = JolpicaProvider()
    with pytest.raises(UnsupportedCapability):
        import asyncio

        asyncio.run(provider.get_telemetry())


# --------------------------------------------------------------------------- #
# 5. Fixtures sinteticos del proveedor live (normalizacion)
# --------------------------------------------------------------------------- #


def _standings_payload() -> dict:
    """Reproduce la forma real que devuelve /api/standings del proveedor live."""
    return {
        "Leaderboard": ["44", "1", "_kf"],
        "Lines": {
            "44": {
                "RacingNumber": "44",
                "FullName": "PILOTO UNO",
                "Tla": "AAA",
                "TeamName": "EQUIPO UNO",
                "TeamColour": "ED1131",
                "Position": "1",
                "ShowPosition": True,
                "Retired": False,
                "InPit": False,
                "Stopped": False,
                "TimeDiffToFastest": "",
                "TimeDiffToPositionAhead": "",
                "BestLapTime": {"Value": "1:34.893", "Lap": 12, "OverallFastest": True},
                "LastLapTime": {"Value": "1:36.100", "Status": 0},
                "NumberOfLaps": 21,
                "NumberOfPitStops": 4,
                "Sectors": [
                    {"Value": "78.056", "PersonalFastest": True, "OverallFastest": False},
                    {"Value": "41.082", "PersonalFastest": False, "OverallFastest": False},
                    {"Value": "37.368", "PersonalFastest": False, "OverallFastest": False},
                ],
                "Speeds": {"I1": {"Value": "195"}, "ST": {"Value": "279"}},
                "BestLapTimes": {
                    "0": {"Value": "1:35.100"},
                    "1": {"Value": "1:34.893"},
                    "2": {"Value": "1:34.500"},
                },
            },
            "1": {
                "RacingNumber": "1",
                "FullName": "PILOTO DOS",
                "Tla": "BBB",
                "TeamName": "EQUIPO DOS",
                "TeamColour": "F47600",
                "Position": "2",
                "TimeDiffToFastest": "+0.813",
                "TimeDiffToPositionAhead": "+0.115",
                "BestLapTime": {"Value": "1:35.706", "Lap": 9},
                "LastLapTime": {"Value": "2:26.878"},
                "NumberOfLaps": 17,
                "NumberOfPitStops": 3,
                "Sectors": [
                    {"Value": "68.428"},
                    {"Value": "41.082"},
                    {"Value": "37.368"},
                ],
                "BestLapTimes": {"0": {"Value": "1:36.000"}},
            },
            "_kf": {"RacingNumber": "_kf"},
        },
    }


def _provider():
    from providers.free_live import FreeLiveTimingProvider

    return FreeLiveTimingProvider(base_url="http://127.0.0.1:9")  # nunca se conecta


def test_normaliza_la_clasificacion_del_proveedor_live():
    import asyncio

    provider = _provider()
    payload = _standings_payload()

    async def fake_get(path: str, *args, **kwargs):
        if path == "/api/standings":
            return payload
        if path == "/api/leaderboard":
            return payload
        raise AssertionError("endpoint inesperado: %s" % path)

    provider._get_json = fake_get  # type: ignore[assignment]

    entries = asyncio.run(provider.get_timing())
    entries = sort_timing_entries(entries)

    # El marcador "_kf" se descarta: no es un piloto.
    assert len(entries) == 2
    assert [e.driver_number for e in entries] == ["44", "1"]

    leader = entries[0]
    assert leader.position == 1
    assert leader.best_lap_time == pytest.approx(94.893)
    assert leader.best_lap_number == 12
    assert leader.best_lap_overall_fastest is True
    assert leader.number_of_laps == 21
    assert leader.driver is not None
    assert leader.driver.team_colour == "ED1131"


def test_separa_las_mejores_vueltas_por_segmento():
    import asyncio

    provider = _provider()
    payload = _standings_payload()

    async def fake_get(path: str, *args, **kwargs):
        return payload

    provider._get_json = fake_get  # type: ignore[assignment]

    entries = asyncio.run(provider.get_timing())
    leader = [e for e in entries if e.driver_number == "44"][0]

    assert leader.best_lap_times["Q1"] == pytest.approx(95.100)
    assert leader.best_lap_times["Q2"] == pytest.approx(94.893)
    assert leader.best_lap_times["Q3"] == pytest.approx(94.500)
    # Un piloto sin Q2/Q3 no inventa esos segmentos.
    other = [e for e in entries if e.driver_number == "1"][0]
    assert "Q2" not in other.best_lap_times


def test_parsea_los_sectores():
    import asyncio

    provider = _provider()
    payload = _standings_payload()

    async def fake_get(path: str, *args, **kwargs):
        return payload

    provider._get_json = fake_get  # type: ignore[assignment]

    entries = asyncio.run(provider.get_timing())
    leader = [e for e in entries if e.driver_number == "44"][0]

    assert len(leader.sectors) == 3
    assert leader.sectors[0].time == pytest.approx(78.056)
    assert leader.sectors[0].personal_fastest is True
    assert leader.sectors[1].personal_fastest is False


def test_gap_vacio_no_se_convierte_en_cero():
    """En clasificacion el lider no tiene gap: debe quedar None, no 0.000."""
    import asyncio

    provider = _provider()
    payload = _standings_payload()

    async def fake_get(path: str, *args, **kwargs):
        return payload

    provider._get_json = fake_get  # type: ignore[assignment]

    entries = asyncio.run(provider.get_timing())
    leader = [e for e in entries if e.driver_number == "44"][0]
    follower = [e for e in entries if e.driver_number == "1"][0]

    assert leader.time_diff_to_fastest is None
    assert follower.time_diff_to_fastest == "+0.813"


def test_combo_de_pneumatico_y_posicion():
    import asyncio

    provider = _provider()
    payload = {
        "Leaderboard": ["44"],
        "Lines": {
            "44": {
                "RacingNumber": "44",
                "Position": "1",
                "Stints": [
                    {"Compound": "SOFT", "New": "true", "TotalLaps": 8, "StartLaps": 0},
                    {"Compound": "MEDIUM", "New": "false", "TotalLaps": 6, "StartLaps": 8},
                ],
            }
        },
    }

    async def fake_get(path: str, *args, **kwargs):
        if path == "/api/standings":
            return payload
        if path == "/api/leaderboard":
            return payload
        return {}

    provider._get_json = fake_get  # type: ignore[assignment]

    entries = asyncio.run(provider.get_timing())
    assert entries[0].tyre_compound == "MEDIUM"
    assert entries[0].tyre_age == 6
    assert entries[0].tyre_new is False
