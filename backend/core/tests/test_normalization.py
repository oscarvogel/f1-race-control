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
                    "0": {"Value": "1:35.100", "Lap": 10},
                    "1": {"Value": "1:34.893", "Lap": 12},
                    "2": {"Value": "1:34.500", "Lap": 14},
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
    # La mejor vuelta es el mejor tiempo de todos los segmentos: el valor de
    # nivel superior (`BestLapTime`) sigue el segmento en curso y se vacia
    # durante el knockout de Q3.
    assert leader.best_lap_time == pytest.approx(94.5)
    assert leader.best_lap_number == 14
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


# --------------------------------------------------------------------------- #
# 8. Gaps de clasificacion: `Stats` como diccionario o como lista
# --------------------------------------------------------------------------- #


def _timing_entry(provider, line):
    """Normaliza una sola linea de clasificacion con el proveedor de prueba."""
    import asyncio

    payload = {"Leaderboard": list(line.keys()), "Lines": line}

    async def fake_get(path: str, *args, **kwargs):
        return payload

    provider._get_json = fake_get  # type: ignore[assignment]
    entries = asyncio.run(provider.get_timing())
    return entries[0]


def test_el_gap_se_lee_de_stats_como_diccionario():
    """El feed entrega `Stats` como mapa indexado por segmento."""
    provider = _provider()
    entry = _timing_entry(
        provider,
        {
            "44": {
                "RacingNumber": "44",
                "Position": "1",
                "Stats": {"0": {"TimeDiffToFastest": "+0.167",
                                "TimeDifftoPositionAhead": "+0.167"}},
            }
        },
    )

    assert entry.time_diff_to_fastest == "+0.167"
    assert entry.time_diff_to_position_ahead == "+0.167"
    assert entry.time_diff_to_fastest_segment == "0"


def test_el_gap_se_lee_de_stats_como_lista():
    """El feed tambien entrega `Stats` como lista de tres segmentos."""
    provider = _provider()
    entry = _timing_entry(
        provider,
        {
            "44": {
                "RacingNumber": "44",
                "Position": "1",
                "Stats": [
                    {"TimeDiffToFastest": "+0.015",
                     "TimeDifftoPositionAhead": "+0.015"},
                    {"TimeDiffToFastest": "", "TimeDifftoPositionAhead": ""},
                    {"TimeDiffToFastest": "", "TimeDifftoPositionAhead": ""},
                ],
            }
        },
    )

    assert entry.time_diff_to_fastest == "+0.015"
    assert entry.time_diff_to_fastest_segment == "0"


def test_el_gap_no_sale_solo_del_primer_segmento():
    """Un piloto que hizo su tiempo en Q2 lo tiene en el indice 1, no en el 0.

    Antes esto dejaba la columna de gap vacia: el backend solo miraba
    `Stats[0]`, que en ese caso estaba en blanco.
    """
    provider = _provider()
    entry = _timing_entry(
        provider,
        {
            "44": {
                "RacingNumber": "44",
                "Position": "1",
                "Stats": [
                    {"TimeDiffToFastest": "", "TimeDifftoPositionAhead": ""},
                    {"TimeDiffToFastest": "+0.086",
                     "TimeDifftoPositionAhead": "+0.071"},
                    {"TimeDiffToFastest": "", "TimeDifftoPositionAhead": ""},
                ],
            }
        },
    )

    assert entry.time_diff_to_fastest == "+0.086"
    assert entry.time_diff_to_position_ahead == "+0.071"
    assert entry.time_diff_to_fastest_segment == "1"


def test_el_gap_toma_el_ultimo_segmento_con_dato():
    """Con Q1 y Q2 poblados, manda el gap del segmento mas reciente."""
    provider = _provider()
    entry = _timing_entry(
        provider,
        {
            "44": {
                "RacingNumber": "44",
                "Position": "1",
                "Stats": [
                    {"TimeDiffToFastest": "+0.500", "TimeDifftoPositionAhead": "+0.500"},
                    {"TimeDiffToFastest": "+0.200", "TimeDifftoPositionAhead": "+0.200"},
                ],
            }
        },
    )

    assert entry.time_diff_to_fastest == "+0.200"
    assert entry.time_diff_to_fastest_segment == "1"


def test_sin_gap_publicado_no_se_inventa_el_segmento():
    """Si el feed no publica ningun gap, el segmento queda en None."""
    provider = _provider()
    entry = _timing_entry(
        provider,
        {
            "44": {
                "RacingNumber": "44",
                "Position": "1",
                "Stats": {"0": {"TimeDifftoPositionAhead": ""}},
            }
        },
    )

    assert entry.time_diff_to_fastest is None
    assert entry.time_diff_to_fastest_segment is None


# --------------------------------------------------------------------------- #
# 9. Fin de sesion: la hora local del circuito convertida a UTC
# --------------------------------------------------------------------------- #


def test_el_fin_de_sesion_usa_el_desfase_del_circuito():
    """`EndDate` viene en hora local del circuito: se convierte con GmtOffset.

    Sin esta conversion la cuenta regresiva del final de la clasificacion
    estaria corrida por el desfase del circuito (5 horas en Austin).
    """
    import asyncio

    provider = _provider()
    payload = {
        "Session": {
            "Key": 11392,
            "Type": "Qualifying",
            "Name": "Qualifying",
            "SessionStatus": "Started",
            "StartDate": "2026-10-24T16:00:00",
            "EndDate": "2026-10-24T17:00:00",
            "GmtOffset": "-05:00:00",
            "Meeting": {
                "Key": 1297,
                "Name": "United States Grand Prix",
                "Location": "Austin",
                "Number": 18,
                "Circuit": {"Key": 9, "ShortName": "Austin"},
                "Country": {"Key": 19, "Code": "USA", "Name": "United States"},
            },
        }
    }

    async def fake_get(path: str, *args, **kwargs):
        return payload

    provider._get_json = fake_get  # type: ignore[assignment]

    session = asyncio.run(provider.get_session())
    assert session is not None
    assert session.start_time_utc is not None
    assert session.end_time_utc is not None
    # 16:00 en Austin (UTC-5) es 21:00 UTC; 17:00 local es 22:00 UTC.
    assert session.start_time_utc.hour == 21
    assert session.end_time_utc.hour == 22
    assert session.end_time_utc.minute == 0
    assert session.gmt_offset == "-05:00:00"


def test_sin_hora_de_fin_no_se_inventa():
    """Sin `EndDate` el fin de sesion queda en None, no en una fecha inventada."""
    import asyncio

    provider = _provider()
    payload = {
        "Session": {
            "Key": 11392,
            "Type": "Qualifying",
            "SessionStatus": "Started",
            "StartDate": "2026-10-24T16:00:00",
            "GmtOffset": "-05:00:00",
            "Meeting": {"Key": 1297, "Circuit": {"Key": 9}},
        }
    }

    async def fake_get(path: str, *args, **kwargs):
        return payload

    provider._get_json = fake_get  # type: ignore[assignment]

    session = asyncio.run(provider.get_session())
    assert session is not None
    assert session.end_time_utc is None


# --------------------------------------------------------------------------- #
# 10. Posiciones GPS del replay: una fila por piloto
# --------------------------------------------------------------------------- #


def test_las_posiciones_historicas_quedan_en_una_fila_por_piloto():
    """De una sesion entera se conserva la ultima muestra de cada piloto.

    El endpoint `location` devuelve una fila por piloto e instante (unas
    80.000 por hora). Guardar todo en el snapshot lo infla sin ganar nada:
    para dibujar el mapa alcanza con donde termino cada auto.

    Las posiciones se piden **piloto por piloto** (en paralelo): sin filtro,
    la sesion entera son ~50 MB y el timeout normal no alcanza.
    """
    import asyncio

    from providers.openf1 import OpenF1Provider

    provider = OpenF1Provider(base_url="http://127.0.0.1:9")  # nunca se conecta
    filas = [
        {"driver_number": 44, "date": "2026-10-23T17:31:00Z", "x": 100.0, "y": 200.0, "z": 1.0},
        {"driver_number": 44, "date": "2026-10-23T17:32:00Z", "x": 110.0, "y": 210.0, "z": 2.0},
        {"driver_number": 1, "date": "2026-10-23T17:31:30Z", "x": 300.0, "y": 400.0, "z": 3.0},
        {"driver_number": 1, "date": "2026-10-23T17:32:30Z", "x": 310.0, "y": 410.0, "z": 4.0},
    ]
    pedidos: list[str] = []

    async def fake_get(path: str, params=None, *args, **kwargs):
        if path == "/drivers":
            return [{"driver_number": 44}, {"driver_number": 1}]
        assert path == "/location"
        numero = str((params or {}).get("driver_number") or "")
        pedidos.append(numero)
        return [fila for fila in filas if str(fila["driver_number"]) == numero]

    provider._get_json = fake_get  # type: ignore[assignment]

    posiciones = asyncio.run(provider.get_positions("11389"))

    # Una consulta por piloto, no una por sesion.
    assert sorted(pedidos) == ["1", "44"]
    assert len(posiciones) == 2
    por_piloto = {p["driver_number"]: p for p in posiciones}
    assert por_piloto["44"]["x"] == pytest.approx(110.0)
    assert por_piloto["44"]["y"] == pytest.approx(210.0)
    assert por_piloto["1"]["x"] == pytest.approx(310.0)
    assert por_piloto["1"]["y"] == pytest.approx(410.0)
    # La coordenada viene con su marca de tiempo.
    assert por_piloto["44"]["timestamp"] is not None


def test_un_piloto_que_falla_no_tira_abajo_a_los_demas():
    """Si la consulta de un piloto falla, los otros siguen con posiciones."""
    import asyncio

    from providers.openf1 import OpenF1Provider

    provider = OpenF1Provider(base_url="http://127.0.0.1:9")

    async def fake_get(path: str, params=None, *args, **kwargs):
        if path == "/drivers":
            return [{"driver_number": 44}, {"driver_number": 1}]
        numero = str((params or {}).get("driver_number") or "")
        if numero == "44":
            raise RuntimeError("se cayo la conexion")
        return [{"driver_number": 1, "date": "2026-10-23T17:32:30Z", "x": 310.0, "y": 410.0}]

    provider._get_json = fake_get  # type: ignore[assignment]

    posiciones = asyncio.run(provider.get_positions("11389"))

    assert [p["driver_number"] for p in posiciones] == ["1"]
    assert posiciones[0]["x"] == pytest.approx(310.0)


def test_una_posicion_sin_coordenadas_no_se_inventa():
    """Si OpenF1 devuelve x/y nulos, quedan en None: no se pone (0,0)."""
    import asyncio

    from providers.openf1 import OpenF1Provider

    provider = OpenF1Provider(base_url="http://127.0.0.1:9")
    filas = [{"driver_number": 44, "date": "2026-10-23T17:32:00Z", "x": None, "y": None, "z": None}]

    async def fake_get(path: str, params=None, *args, **kwargs):
        if path == "/drivers":
            return [{"driver_number": 44}]
        return filas

    provider._get_json = fake_get  # type: ignore[assignment]

    posiciones = asyncio.run(provider.get_positions("11389"))
    assert posiciones[0]["x"] is None
    assert posiciones[0]["y"] is None


# --------------------------------------------------------------------------- #
# 11. Mejor vuelta cuando el feed vacia el valor global (knockout de Q3)
# --------------------------------------------------------------------------- #


def test_la_mejor_vuelta_no_se_pierde_cuando_el_feed_vacia_el_valor_global():
    """Durante el knockout el feed vacia `BestLapTime`.

    Se ha visto en la quali de Austin 2026: el feed manda
    ``{"Value": "", "Lap": 11, "_deleted": ["Lap"]}`` para los pilotos que aun
    no hicieron su vuelta de Q3. Si solo se mirara ese campo, la columna
    "MEJOR VUELTA" quedaria vacia aunque el piloto tenga un Q1 o un Q2.
    """
    provider = _provider()
    entry = _timing_entry(
        provider,
        {
            "12": {
                "RacingNumber": "12",
                "Position": "2",
                "BestLapTime": {"Value": "", "Lap": 11, "_deleted": ["Lap"]},
                "BestLapTimes": {
                    "0": {"Value": "1:35.390", "Lap": 5},
                    "1": {"Value": "1:34.278", "Lap": 11},
                    "2": {"Value": ""},
                },
            }
        },
    )

    assert entry.best_lap_time == pytest.approx(94.278)
    assert entry.best_lap_number == 11
    assert entry.best_lap_times["Q1"] == pytest.approx(95.390)
    assert entry.best_lap_times["Q2"] == pytest.approx(94.278)
    # El segmento Q3 existe pero no tiene tiempo: no se inventa.
    assert entry.best_lap_times["Q3"] is None


def test_la_mejor_vuelta_toma_el_mas_rapido_de_los_segmentos():
    """Si el feed trae un Q1 y un Q2, la mejor vuelta es el menor de los dos."""
    provider = _provider()
    entry = _timing_entry(
        provider,
        {
            "12": {
                "RacingNumber": "12",
                "Position": "2",
                "BestLapTime": {"Value": "", "Lap": 11},
                "BestLapTimes": {
                    "0": {"Value": "1:35.390", "Lap": 5},
                    "1": {"Value": "1:34.278", "Lap": 11},
                },
            }
        },
    )

    assert entry.best_lap_time == pytest.approx(94.278)
    assert entry.best_lap_number == 11


# --------------------------------------------------------------------------- #
# 12. Gap vacio en el resultado historico (clasificacion de Austin 2026)
# --------------------------------------------------------------------------- #


def test_un_gap_vacio_no_rompe_la_clasificacion_historica():
    """OpenF1 puede devolver `gap_to_leader` vacio o nulo.

    En la clasificacion de Austin 2026 (session_key 11392) vino vacio para
    varios pilotos. Con el gap tal cual, el formato `"+%.3f" % None` reventaba
    con "must be real number, not NoneType" y **todo** el snapshot historico
    de la sesion se caia (el selector de sesiones mostraba la quali vacia).
    """
    import asyncio

    from providers.openf1 import OpenF1Provider

    provider = OpenF1Provider(base_url="http://127.0.0.1:9")

    async def fake_get(path: str, params=None, *args, **kwargs):
        if path == "/session_result":
            return [
                {"driver_number": 12, "position": 1, "gap_to_leader": None, "number_of_laps": 12},
                {"driver_number": 16, "position": 2, "gap_to_leader": "", "number_of_laps": 11},
                {"driver_number": 3, "position": 3, "gap_to_leader": 0.163, "number_of_laps": 11},
            ]
        if path == "/laps":
            return [
                {
                    "driver_number": 12,
                    "lap_number": 14,
                    "lap_duration": 94.035,
                    "duration_sector_1": 25.310,
                    "duration_sector_2": 37.297,
                    "duration_sector_3": 31.428,
                }
            ]
        if path == "/drivers":
            return [{"driver_number": 12, "name_acronym": "ANT"}]
        return []

    provider._get_json = fake_get  # type: ignore[assignment]

    entradas = asyncio.run(provider.get_timing("11392"))

    assert len(entradas) == 3
    por_numero = {e.driver_number: e for e in entradas}
    # Sin gap no hay texto de gap: no se inventa un 0 ni un "+0.000".
    assert por_numero["12"].gap_to_leader is None
    assert por_numero["16"].gap_to_leader is None
    # El lider con diferencia cero es "LEADER" y el resto trae su diferencia.
    assert por_numero["3"].gap_to_leader == "+0.163"
    # Y la mejor vuelta sigue saliendo de /laps.
    assert por_numero["12"].best_lap_time == pytest.approx(94.035)
