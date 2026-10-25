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
    """Devuelve vueltas y pilotos fijos, sin tocar la red."""

    provider_id = "openf1"

    def __init__(self, vueltas: dict[str, list[dict]]):
        self.vueltas = vueltas

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

    async def get_best_laps(self, session_key=None):
        clave = str(session_key)
        mejores: dict[str, dict] = {}
        for vuelta in self.vueltas.get(clave, []):
            numero = str(vuelta["driver_number"])
            if numero not in mejores or vuelta["lap_time"] < mejores[numero]["lap_time"]:
                mejores[numero] = vuelta
        return sorted(mejores.values(), key=lambda item: item["lap_time"])


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
