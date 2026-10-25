"""Pruebas del analisis post-sesion (sectores) y del campeonato.

El analisis se apoya en OpenF1 (``/laps``), que es la unica fuente donde los
sectores **suman** el tiempo de la vuelta. Aqui se comprueba que los deltas
se calculan bien, que un dato ausente queda en ``None`` (nunca en cero) y que
el campeonato se arma con los datos reales de Jolpica.
"""

from __future__ import annotations

import pytest
from django.test import Client

from core import analysis as analysis_module
from providers.jolpica import JolpicaProvider


# --------------------------------------------------------------------------- #
# Proveedor falso de OpenF1
# --------------------------------------------------------------------------- #


class _SesionFalsa:
    provider_id = "openf1"
    session_name = "Qualifying"
    session_type = "Qualifying"
    meeting_name = "United States Grand Prix"
    official_name = "FORMULA 1 MSC CRUISES UNITED STATES GRAND PRIX 2026"
    circuit_name = "Austin"
    season = "2026"

    def __init__(self, clave: str):
        self.provider_session_id = clave
        self.start_time_utc = None
        self.end_time_utc = None


class _ProveedorFalso:
    """Devuelve vueltas, stints, posiciones y pilotos fijos, sin tocar la red."""

    provider_id = "openf1"

    def __init__(
        self,
        vueltas: dict[str, list[dict]],
        stints: dict[str, list[dict]] | None = None,
        posiciones: dict[str, list[dict]] | None = None,
        race_control: dict[str, list[str]] | None = None,
    ):
        self.vueltas = vueltas
        self.stints = stints or {}
        self.posiciones = posiciones or {}
        self.race_control = race_control or {}

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def get_session(self, session_key=None):
        return _SesionFalsa(str(session_key))

    async def get_drivers(self, session_key=None):
        from providers.base import Driver

        numeros = sorted({v["driver_number"] for v in self.vueltas.get(str(session_key), [])})
        return [
            Driver(
                provider_id="openf1",
                number=str(numero),
                code="P" + str(numero),
                full_name="Piloto " + str(numero),
                team_name="Equipo " + str(numero),
            )
            for numero in numeros
        ]

    async def get_best_laps(self, session_key=None, laps_rows=None):
        clave = str(session_key)
        mejores: dict[str, dict] = {}
        for vuelta in self.vueltas.get(clave, []):
            numero = str(vuelta["driver_number"])
            if numero not in mejores or vuelta["lap_time"] < mejores[numero]["lap_time"]:
                mejores[numero] = vuelta
        return sorted(mejores.values(), key=lambda item: item["lap_time"])

    async def get_raw_laps(self, session_key=None):
        """Las filas crudas: el proveedor real las usa para el cruce."""
        return list(self.vueltas.get(str(session_key), []))

    async def get_raw_stints(self, session_key=None):
        return list(self.stints.get(str(session_key), []))

    async def get_position_history(self, session_key=None):
        return list(self.posiciones.get(str(session_key), []))

    async def get_race_control(self, session_key=None):
        """Los mensajes del control de carrera (importan los "DELETED")."""

        class _Evento:
            def __init__(self, mensaje: str):
                self.message = mensaje

        return [
            _Evento(mensaje)
            for mensaje in self.race_control.get(str(session_key), [])
        ]


def _vuelta(numero: str, tiempo: float, s1: float, s2: float, s3: float) -> dict:
    return {
        "driver_number": numero,
        "lap_number": 10,
        "lap_time": tiempo,
        "sector_1": s1,
        "sector_2": s2,
        "sector_3": s3,
        "compound": "SOFT",
        "tyre_age": 3,
        "is_pit_out_lap": False,
        "i1_speed": 300.0,
        "i2_speed": 250.0,
    }


@pytest.fixture
def proveedor_falso(monkeypatch, db):
    vueltas = {
        "11392": [
            _vuelta("44", 94.000, 25.000, 37.000, 32.000),
            _vuelta("1", 94.500, 25.100, 37.100, 32.300),
        ],
        "11391": [
            _vuelta("44", 95.000, 25.500, 37.500, 32.000),
            _vuelta("1", 95.200, 25.600, 37.400, 32.200),
        ],
    }
    monkeypatch.setattr(
        analysis_module,
        "_openf1_provider",
        lambda: _ProveedorFalso(vueltas),
    )
    # Ni la cache en memoria ni la de la base: cada test usa sus datos.
    monkeypatch.setattr(analysis_module, "_RAW_CACHE", {})
    monkeypatch.setattr(analysis_module, "_load_raw_from_db", lambda key: None)
    return vueltas


# --------------------------------------------------------------------------- #
# Analisis por sectores
# --------------------------------------------------------------------------- #


def test_el_delta_contra_el_mas_rapido_se_calcula_bien(proveedor_falso):
    resultado = analysis_module.build_sector_analysis("11392")

    assert resultado["found"] is True
    assert resultado["fastest"]["driver_number"] == "44"
    assert resultado["fastest"]["lap_time"] == 94.0

    filas = {fila["driver_number"]: fila for fila in resultado["rows"]}
    assert filas["44"]["delta_to_fastest"] == pytest.approx(0.0)
    assert filas["1"]["delta_to_fastest"] == pytest.approx(0.5)
    assert filas["1"]["delta_display"] == "+0.500"
    # Los sectores suman exactamente el tiempo de la vuelta.
    assert filas["44"]["lap_time"] == pytest.approx(
        sum(s["time"] for s in filas["44"]["sectors"])
    )


def test_el_delta_por_sector_contra_el_piloto_de_referencia(proveedor_falso):
    resultado = analysis_module.build_sector_analysis("11392", reference_driver="1")

    filas = {fila["driver_number"]: fila for fila in resultado["rows"]}
    referencia = filas["1"]
    assert referencia["sectors"][0]["delta_to_reference"] == pytest.approx(0.0)

    # Contra el piloto 1, el 44 es mas rapido en los tres sectores.
    delta = filas["44"]["sectors"][0]["delta_to_reference"]
    assert delta == pytest.approx(-0.1)


def test_el_delta_contra_otra_sesion(proveedor_falso):
    resultado = analysis_module.build_sector_analysis("11392", compare_session_key="11391")

    filas = {fila["driver_number"]: fila for fila in resultado["rows"]}
    # En la quali el piloto 44 fue 1 s mas rapido que en FP3.
    assert filas["44"]["compare"]["delta_lap"] == pytest.approx(-1.0)
    assert filas["44"]["compare"]["delta_display"] == "-1.000"
    assert filas["44"]["compare"]["lap_time"] == pytest.approx(95.0)
    # Y el detalle por sector tambien viene.
    deltas = {s["index"]: s["delta"] for s in filas["44"]["compare"]["sector_deltas"]}
    assert deltas[0] == pytest.approx(-0.5)


def test_un_sector_ausente_queda_en_none_y_no_en_cero(proveedor_falso, monkeypatch, db):
    """Si falta el S3, queda None. Nunca se inventa un 0.000."""
    vueltas = {
        "11392": [
            {
                "driver_number": "44",
                "lap_number": 10,
                "lap_time": 62.0,
                "sector_1": 25.0,
                "sector_2": 37.0,
                "sector_3": None,
                "compound": None,
                "tyre_age": None,
                "is_pit_out_lap": False,
                "i1_speed": None,
                "i2_speed": None,
            }
        ]
    }
    monkeypatch.setattr(
        analysis_module,
        "_openf1_provider",
        lambda: _ProveedorFalso(vueltas),
    )
    monkeypatch.setattr(analysis_module, "_RAW_CACHE", {})
    monkeypatch.setattr(analysis_module, "_load_raw_from_db", lambda key: None)

    resultado = analysis_module.build_sector_analysis("11392")
    sector = resultado["rows"][0]["sectors"][2]
    assert sector["time"] is None
    assert sector["display"] is None
    assert sector["delta_to_fastest"] is None


def test_la_api_de_analisis_devuelve_las_filas(proveedor_falso, db):
    respuesta = Client().get("/api/analysis/sectors/11392/")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["found"] is True
    assert len(datos["rows"]) == 2


# --------------------------------------------------------------------------- #
# Campeonato (Jolpica)
# --------------------------------------------------------------------------- #


def test_el_campeonato_se_arma_con_los_datos_de_jolpica(monkeypatch, db):
    payload = {
        "MRData": {
            "StandingsTable": {
                "season": "2026",
                "StandingsLists": [
                    {
                        "round": "17",
                        "DriverStandings": [
                            {
                                "position": "1",
                                "points": "340",
                                "wins": "8",
                                # El endpoint NO publica los podios.
                                "Driver": {
                                    "permanentNumber": "12",
                                    "code": "ANT",
                                    "givenName": "Andrea Kimi",
                                    "familyName": "Antonelli",
                                    "nationality": "Italian",
                                },
                                # El equipo viene en "Constructors" (lista), no
                                # en "Constructor": el actual es el ultimo.
                                "Constructors": [
                                    {
                                        "constructorId": "mercedes",
                                        "name": "Mercedes",
                                        "nationality": "German",
                                    }
                                ],
                            },
                            {
                                "position": "2",
                                "points": "238",
                                "wins": "3",
                                "Driver": {
                                    "permanentNumber": "63",
                                    "code": "RUS",
                                    "givenName": "George",
                                    "familyName": "Russell",
                                    "nationality": "British",
                                },
                                "Constructors": [
                                    {
                                        "constructorId": "mercedes",
                                        "name": "Mercedes",
                                        "nationality": "German",
                                    }
                                ],
                            },
                        ],
                        "ConstructorStandings": [
                            {
                                "position": "1",
                                "points": "500",
                                "wins": "9",
                                "Constructor": {"name": "Mercedes", "nationality": "German"},
                            }
                        ],
                    }
                ],
            }
        }
    }

    async def fake_get_json(self, path: str):
        return payload

    monkeypatch.setattr(JolpicaProvider, "_get_json", fake_get_json)
    monkeypatch.setattr(analysis_module, "_CHAMPIONSHIP_CACHE", {})

    resultado = analysis_module.build_championship(2026)

    assert resultado["found"] is True
    assert resultado["round"] == 17
    assert resultado["drivers"][0]["code"] == "ANT"
    assert resultado["drivers"][0]["points"] == 340
    assert resultado["drivers"][0]["wins"] == 8
    # Los podios no los publica el endpoint: quedan en None (no en 0).
    assert resultado["drivers"][0]["podiums"] is None
    # El equipo sale del ultimo de "Constructors".
    assert resultado["drivers"][0]["team"] == "Mercedes"
    # El rezago con el lider.
    assert resultado["drivers"][0]["gap_to_leader"] == 0
    assert resultado["drivers"][1]["gap_to_leader"] == -102
    assert resultado["teams"][0]["points"] == 500
    # Y el aviso de en que ronda esta la tabla.
    assert "ronda 17" in resultado["note"]


def test_la_api_del_campeonato_responde(monkeypatch, db):
    async def fake_get_championship(self, season=None):
        return {"season": season or 2026, "round": 17, "drivers": [], "teams": []}

    monkeypatch.setattr(
        analysis_module.JolpicaProvider,
        "get_championship",
        fake_get_championship,
    )
    monkeypatch.setattr(analysis_module, "_CHAMPIONSHIP_CACHE", {})

    respuesta = Client().get("/api/championship/")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["found"] is True
    assert datos["round"] == 17


# --------------------------------------------------------------------------- #
# Evolucion de posiciones
# --------------------------------------------------------------------------- #


def _vuelta_cruda(numero: str, vuelta: int, duracion: float, inicio: str) -> dict:
    """Una vuelta cruda de /laps, con la hora de inicio."""
    return {
        "driver_number": numero,
        "lap_number": vuelta,
        "lap_duration": duracion,
        "date_start": inicio,
        "is_pit_out_lap": False,
        "duration_sector_1": 25.0,
        "duration_sector_2": 37.0,
        "duration_sector_3": 32.0,
        "lap_time": duracion,
        "sector_1": 25.0,
        "sector_2": 37.0,
        "sector_3": 32.0,
        "compound": None,
        "tyre_age": None,
        "i1_speed": 300.0,
        "i2_speed": 250.0,
    }


def _cambio(numero: str, posicion: int, momento: str) -> dict:
    """Un cambio de posicion de /position."""
    return {"driver_number": numero, "position": posicion, "date": momento}


@pytest.fixture
def proveedor_con_posiciones(monkeypatch, db):
    """Un piloto con tres vueltas y cuatro cambios de posicion.

    Los tiempos estan puestos para que se vea el cruce: el cambio de
    posicion se publica en el mismo instante en que arranca la vuelta
    siguiente, con un desfasase de hasta medio segundo.
    """
    vueltas = {
        "11392": [
            _vuelta_cruda("1", 1, 95.0, "2026-10-24T21:00:00+00:00"),
            _vuelta_cruda("1", 2, 94.5, "2026-10-24T21:01:00+00:00"),
            _vuelta_cruda("1", 3, 94.0, "2026-10-24T21:02:00+00:00"),
        ]
    }
    posiciones = {
        "11392": [
            _cambio("1", 3, "2026-10-24T21:00:30+00:00"),
            # Al cruzar la linea de la vuelta 1, medio segundo despues de que
            # arrancara la vuelta 2.
            _cambio("1", 1, "2026-10-24T21:01:00.500000+00:00"),
            _cambio("1", 2, "2026-10-24T21:01:30+00:00"),
            _cambio("1", 4, "2026-10-24T21:02:00+00:00"),
        ]
    }
    monkeypatch.setattr(
        analysis_module,
        "_openf1_provider",
        lambda: _ProveedorFalso(vueltas, posiciones=posiciones),
    )
    monkeypatch.setattr(analysis_module, "_RAW_CACHE", {})
    monkeypatch.setattr(analysis_module, "_load_raw_from_db", lambda key: None)
    return vueltas


def test_la_posicion_al_final_de_cada_vuelta(proveedor_con_posiciones):
    """La posicion de una vuelta es el ultimo cambio hasta el inicio de la siguiente.

    El cambio se publica en el mismo instante en que arranca la vuelta
    siguiente (con un desfasase de decenas de milisegundos), asi que la
    posicion al final de la vuelta 1 es la del cambio que coincide con el
    arranque de la vuelta 2.
    """
    resultado = analysis_module.build_position_history("11392")

    assert resultado["found"] is True
    assert len(resultado["rows"]) == 1
    fila = resultado["rows"][0]
    puntos = {p["lap"]: p["position"] for p in fila["points"]}

    # Vuelta 1: el cambio de las 21:01:00.500 (P1) todavia pertenece a la
    # vuelta 1, porque la vuelta 2 arranca a las 21:01:00.
    assert puntos[1] == 1
    # Vuelta 2: el cambio de las 21:02:00 (P4).
    assert puntos[2] == 4
    # Vuelta 3 (la ultima): manda el ultimo cambio de la sesion.
    assert puntos[3] == 4
    assert fila["final_position"] == 4
    # Los movimientos se cuentan de una vuelta a otra (que es lo que muestra
    # el grafico): de P1 a P4 se perdieron tres puestos. El cambio de P3 a P1
    # de la vuelta 1 pasa dentro de la vuelta, asi que no cuenta.
    assert fila["positions_gained"] == 0
    assert fila["positions_lost"] == 1


def test_sin_cambios_de_posicion_no_hay_evolucion(monkeypatch, db):
    """Sin datos de posiciones, el panel dice que no hay datos (no inventa)."""
    monkeypatch.setattr(
        analysis_module,
        "_openf1_provider",
        lambda: _ProveedorFalso({"11392": [_vuelta_cruda("1", 1, 95.0, "2026-10-24T21:00:00+00:00")]}),
    )
    monkeypatch.setattr(analysis_module, "_RAW_CACHE", {})
    monkeypatch.setattr(analysis_module, "_load_raw_from_db", lambda key: None)

    resultado = analysis_module.build_position_history("11392")
    assert resultado["found"] is False
    assert resultado["rows"] == []


def test_la_api_de_posiciones_devuelve_las_filas(proveedor_con_posiciones, db):
    respuesta = Client().get("/api/analysis/positions/11392/")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["found"] is True
    assert len(datos["rows"]) == 1
    assert datos["rows"][0]["points"]


# --------------------------------------------------------------------------- #
# Estrategia de neumaticos
# --------------------------------------------------------------------------- #


@pytest.fixture
def proveedor_con_stints(monkeypatch, db):
    """Un piloto con dos tramos: uno de 3 vueltas y otro de 2."""
    vueltas = {
        "11396": [
            _vuelta_cruda("1", 1, 95.0, "2026-10-24T21:00:00+00:00"),
            _vuelta_cruda("1", 2, 94.0, "2026-10-24T21:01:35+00:00"),
            _vuelta_cruda("1", 3, 93.5, "2026-10-24T21:03:10+00:00"),
            _vuelta_cruda("1", 4, 93.8, "2026-10-24T21:04:45+00:00"),
            _vuelta_cruda("1", 5, 94.2, "2026-10-24T21:06:20+00:00"),
        ]
    }
    stints = {
        "11396": [
            {
                "driver_number": "1",
                "stint_number": 1,
                "compound": "MEDIUM",
                "lap_start": 1,
                "lap_end": 3,
                "tyre_age_at_start": 0,
            },
            {
                "driver_number": "1",
                "stint_number": 2,
                "compound": "SOFT",
                "lap_start": 4,
                "lap_end": 5,
                "tyre_age_at_start": 0,
            },
        ]
    }
    monkeypatch.setattr(
        analysis_module,
        "_openf1_provider",
        lambda: _ProveedorFalso(vueltas, stints=stints),
    )
    monkeypatch.setattr(analysis_module, "_RAW_CACHE", {})
    monkeypatch.setattr(analysis_module, "_load_raw_from_db", lambda key: None)
    return vueltas


def test_la_estrategia_dice_el_compuesto_las_vueltas_y_la_mejor_vuelta(proveedor_con_stints):
    resultado = analysis_module.build_strategy("11396")

    assert resultado["found"] is True
    assert len(resultado["rows"]) == 1
    fila = resultado["rows"][0]

    assert fila["stint_count"] == 2
    assert fila["stops"] == 1
    assert fila["total_laps"] == 5
    assert fila["compounds"] == ["MEDIUM", "SOFT"]
    assert fila["best_lap_time"] == pytest.approx(93.5)
    assert fila["best_lap_number"] == 3

    tramos = fila["stints"]
    assert tramos[0]["compound"] == "MEDIUM"
    assert tramos[0]["lap_start"] == 1
    assert tramos[0]["lap_end"] == 3
    assert tramos[0]["laps"] == 3
    # La mejor vuelta del tramo es la mas rapida de sus vueltas.
    assert tramos[0]["best_lap_time"] == pytest.approx(93.5)
    assert tramos[0]["best_lap_number"] == 3
    assert tramos[0]["best_lap_time_display"] == "1:33.500"

    assert tramos[1]["compound"] == "SOFT"
    assert tramos[1]["laps"] == 2
    assert tramos[1]["best_lap_time"] == pytest.approx(93.8)


def test_sin_stints_no_hay_estrategia(monkeypatch, db):
    monkeypatch.setattr(
        analysis_module,
        "_openf1_provider",
        lambda: _ProveedorFalso({"11392": [_vuelta_cruda("1", 1, 95.0, "2026-10-24T21:00:00+00:00")]}),
    )
    monkeypatch.setattr(analysis_module, "_RAW_CACHE", {})
    monkeypatch.setattr(analysis_module, "_load_raw_from_db", lambda key: None)

    resultado = analysis_module.build_strategy("11392")
    assert resultado["found"] is False
    assert resultado["rows"] == []


def test_la_api_de_estrategia_devuelve_las_filas(proveedor_con_stints, db):
    respuesta = Client().get("/api/analysis/strategy/11396/")
    assert respuesta.status_code == 200
    datos = respuesta.json()
    assert datos["found"] is True
    assert len(datos["rows"]) == 1
    assert len(datos["rows"][0]["stints"]) == 2


def test_una_vuelta_anulada_no_cuenta_en_la_estrategia(monkeypatch, db):
    """La vuelta anulada por la federacion no puede ser la mejor vuelta.

    Es el caso real de Norris en la quali de Austin 2026: su vuelta de
    1:34.379 fue anulada por track limits (lo publica el control de carrera)
    y su tiempo valido de Q3 es 1:35.049.
    """
    vueltas = {
        "11392": [
            _vuelta_cruda("1", 10, 94.379, "2026-10-24T21:59:36+00:00"),
            _vuelta_cruda("1", 11, 95.049, "2026-10-24T21:50:44+00:00"),
        ]
    }
    stints = {
        "11392": [
            {
                "driver_number": "1",
                "stint_number": 1,
                "compound": "SOFT",
                "lap_start": 10,
                "lap_end": 11,
                "tyre_age_at_start": 0,
            }
        ]
    }
    race_control = {
        "11392": [
            "CAR 1 (NOR) TIME 1:34.379 DELETED - TRACK LIMITS AT TURN 19 LAP 15 17:01:02",
        ]
    }
    monkeypatch.setattr(
        analysis_module,
        "_openf1_provider",
        lambda: _ProveedorFalso(vueltas, stints=stints, race_control=race_control),
    )
    monkeypatch.setattr(analysis_module, "_RAW_CACHE", {})
    monkeypatch.setattr(analysis_module, "_load_raw_from_db", lambda key: None)

    resultado = analysis_module.build_strategy("11392")
    fila = resultado["rows"][0]

    # La mejor vuelta del tramo no es la anulada (1:34.379) sino la que cuenta.
    assert fila["stints"][0]["best_lap_time"] == pytest.approx(95.049)
    assert fila["best_lap_time"] == pytest.approx(95.049)


def test_el_control_de_carrera_que_no_anula_nada_no_cambia_nada(monkeypatch, db):
    """Si no hay eventos de anulacion, la mejor vuelta es la mas rapida."""
    vueltas = {
        "11392": [
            _vuelta_cruda("1", 10, 94.379, "2026-10-24T21:59:36+00:00"),
            _vuelta_cruda("1", 11, 95.049, "2026-10-24T21:50:44+00:00"),
        ]
    }
    stints = {
        "11392": [
            {
                "driver_number": "1",
                "stint_number": 1,
                "compound": "SOFT",
                "lap_start": 10,
                "lap_end": 11,
                "tyre_age_at_start": 0,
            }
        ]
    }
    monkeypatch.setattr(
        analysis_module,
        "_openf1_provider",
        lambda: _ProveedorFalso(vueltas, stints=stints),
    )
    monkeypatch.setattr(analysis_module, "_RAW_CACHE", {})
    monkeypatch.setattr(analysis_module, "_load_raw_from_db", lambda key: None)

    resultado = analysis_module.build_strategy("11392")
    assert resultado["rows"][0]["stints"][0]["best_lap_time"] == pytest.approx(94.379)


def test_se_leen_las_anulaciones_del_control_de_carrera():
    """El parser saca piloto, tiempo y vuelta del mensaje del control."""
    por_vuelta, por_tiempo = analysis_module._vueltas_anuladas(
        [
            {
                "message": "CAR 1 (NOR) TIME 1:34.379 DELETED - TRACK LIMITS AT TURN 19 LAP 15 17:01:02"
            },
            {
                "message": "CAR 5 (BOR) LAP DELETED - TRACK LIMITS AT TURN 11 LAP 9 16:29:31 (PIT)"
            },
            {"message": "CAR 12 (ANT) TIME 1:43.354 DELETED - TRACK LIMITS AT TURN 15 LAP 24"},
            {"message": "GREEN LIGHT, RACE START"},
        ]
    )

    assert ("1", 15) in por_vuelta
    assert ("5", 9) in por_vuelta
    assert ("12", 24) in por_vuelta
    assert ("1", 94.379) in por_tiempo
    assert ("12", 103.354) in por_tiempo
    # El evento que no es de anulacion se ignora.
    assert len(por_vuelta) == 3
