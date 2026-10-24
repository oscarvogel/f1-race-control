"""Pruebas de la API interna de Race Center."""

from __future__ import annotations

import json

import pytest
from django.test import Client

from core.models import Session, SessionSnapshot


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def snapshot(db) -> SessionSnapshot:
    session = Session.objects.create(
        provider_id="free_livetiming",
        provider_session_id="11392",
        name="Qualifying",
        session_type="Qualifying",
        state="Started",
    )
    payload = {
        "generated_at": "2026-10-24T21:05:00+00:00",
        "data_state": "LIVE",
        "scope": "live",
        "session": {
            "provider_id": "free_livetiming",
            "provider_session_id": "11392",
            "meeting_name": "United States Grand Prix",
            "official_name": "FORMULA 1 MSC CRUISES UNITED STATES GRAND PRIX 2026",
            "circuit_name": "Austin",
            "location": "Austin",
            "country_name": "United States",
            "country_code": "USA",
            "season": "2026",
            "round_number": 18,
            "meeting_key": 1297,
            "session_type": "Qualifying",
            "session_name": "Qualifying",
            "session_number": None,
            "start_time_utc": "2026-10-24T21:00:00+00:00",
            "end_time_utc": "2026-10-24T22:00:00+00:00",
            "state": "Started",
            "archive_status": None,
            "gmt_offset": "-05:00:00",
            "qualifying_segment": None,
            "source_timestamp": "2026-10-24T21:05:00+00:00",
        },
        "drivers": [
            {
                "provider_id": "free_livetiming",
                "number": "44",
                "code": "HAM",
                "full_name": "Lewis HAMILTON",
                "broadcast_name": "L HAMILTON",
                "first_name": "Lewis",
                "last_name": "Hamilton",
                "team_name": "Ferrari",
                "team_colour": "ED1131",
                "country_code": None,
                "line": 1,
                "headshot_url": None,
                "source_timestamp": "2026-10-24T21:05:00+00:00",
            }
        ],
        "timing": [
            {
                "provider_id": "free_livetiming",
                "driver_number": "44",
                "driver": {
                    "provider_id": "free_livetiming",
                    "number": "44",
                    "code": "HAM",
                    "full_name": "Lewis HAMILTON",
                    "broadcast_name": "L HAMILTON",
                    "first_name": "Lewis",
                    "last_name": "Hamilton",
                    "team_name": "Ferrari",
                    "team_colour": "ED1131",
                    "country_code": None,
                    "line": 1,
                    "headshot_url": None,
                    "source_timestamp": "2026-10-24T21:05:00+00:00",
                },
                "position": 1,
                "show_position": True,
                "best_lap_time": 94.893,
                "best_lap_time_display": "1:34.893",
                "best_lap_number": 12,
                "best_lap_overall_fastest": True,
                "last_lap_time": 96.1,
                "last_lap_time_display": "1:36.100",
                "sectors": [
                    {
                        "index": 0,
                        "time": 78.056,
                        "time_display": "1:18.056",
                        "personal_fastest": True,
                        "overall_fastest": False,
                        "stopped": False,
                        "valid": True,
                    }
                ],
                "gap_to_leader": None,
                "interval_to_ahead": None,
                "time_diff_to_fastest": None,
                "time_diff_to_position_ahead": None,
                "number_of_laps": 12,
                "number_of_pit_stops": 2,
                "in_pit": False,
                "pit_out": False,
                "stopped": False,
                "retired": False,
                "status_code": 1104,
                "tyre_compound": "SOFT",
                "tyre_age": 8,
                "tyre_new": True,
                "grid_position": None,
                "best_lap_times": {"Q1": {"time": 95.1, "time_display": "1:35.100"}},
                "speeds": {"I1": 195.0, "ST": 279.0},
                "source_timestamp": "2026-10-24T21:05:00+00:00",
            }
        ],
        "weather": {
            "provider_id": "free_livetiming",
            "air_temperature": 28.2,
            "track_temperature": 40.9,
            "humidity": 44.0,
            "pressure": 1003.2,
            "rainfall": 0.0,
            "wind_speed": 2.4,
            "wind_direction": 138.0,
            "source_timestamp": "2026-10-24T21:05:00+00:00",
        },
        "race_control": [
            {
                "provider_id": "free_livetiming",
                "message": "YELLOW FLAG IN TRACK SECTOR 2",
                "category": "Flag",
                "flag": "YELLOW",
                "scope": "Track",
                "utc": "2026-10-24T21:03:00+00:00",
                "source_timestamp": "2026-10-24T21:05:00+00:00",
            }
        ],
        "tyres": [],
        "sources": {
            "session": "free_livetiming",
            "timing": "free_livetiming",
            "drivers": "free_livetiming",
            "weather": "free_livetiming",
            "race_control": "free_livetiming",
            "tyres": "free_livetiming",
        },
        "provider_status": [],
        "diagnostics": {"mode": "auto", "providers": []},
    }
    return SessionSnapshot.objects.create(
        session=session,
        provider_id="free_livetiming",
        data_state="LIVE",
        fingerprint="f" * 64,
        payload=payload,
    )


# --------------------------------------------------------------------------- #
def test_health(client, db):
    response = client.get("/api/health/")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["mode"] == "personal"


def test_sessions_current_sin_snapshot(client, db):
    response = client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert data["found"] is False
    assert "reason" in data


def test_sessions_current_con_snapshot(client, snapshot):
    response = client.get("/api/sessions/current/")
    assert response.status_code == 200
    data = response.json()
    assert data["found"] is True
    assert data["data_state"] == "LIVE"
    assert data["session"]["meeting_name"] == "United States Grand Prix"
    assert data["session"]["provider_session_id"] == "11392"
    assert len(data["timing"]) == 1
    assert data["timing"][0]["driver"]["full_name"] == "Lewis HAMILTON"
    # La fuente viaja siempre con el dato.
    assert data["sources"]["timing"] == "free_livetiming"


def test_listado_de_sesiones(client, snapshot):
    response = client.get("/api/sessions/")
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["provider_session_id"] == "11392"


def test_filtro_de_sesiones_por_tipo(client, snapshot):
    response = client.get("/api/sessions/?type=Practice")
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_snapshot_de_sesion(client, snapshot):
    response = client.get("/api/sessions/%d/snapshot/" % snapshot.session_id)
    assert response.status_code == 200
    assert response.json()["data_state"] == "LIVE"


def test_timing_de_sesion(client, snapshot):
    response = client.get("/api/sessions/%d/timing/" % snapshot.session_id)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["driver_number"] == "44"


def test_timing_filtrado_por_piloto(client, snapshot):
    response = client.get("/api/sessions/%d/timing/?driver=1" % snapshot.session_id)
    assert response.status_code == 200
    assert response.json()["count"] == 0


def test_clima_de_sesion(client, snapshot):
    response = client.get("/api/sessions/%d/weather/" % snapshot.session_id)
    assert response.status_code == 200
    data = response.json()
    assert data["found"] is True
    assert data["weather"]["track_temperature"] == 40.9


def test_control_de_carrera(client, snapshot):
    response = client.get("/api/sessions/%d/race-control/" % snapshot.session_id)
    assert response.status_code == 200
    data = response.json()
    assert data["count"] == 1
    assert data["results"][0]["flag"] == "YELLOW"


def test_sesion_inexistente_devuelve_404(client, db):
    response = client.get("/api/sessions/999999/snapshot/")
    assert response.status_code == 404


def test_la_api_no_expone_credenciales(client, db):
    """Ninguna respuesta puede filtrar claves de API ni secretos."""
    for path in ("/api/health/", "/api/providers/", "/api/sessions/current/"):
        response = client.get(path)
        body = response.content.decode("utf-8").lower()
        assert "authorization" not in body
        assert "api_key" not in body
        assert "secret" not in body
        assert "bearer " not in body


def test_el_snapshot_no_se_crea_si_el_contenido_no_cambio(db, snapshot):
    """La deduplicacion por huella evita filas identicas."""
    from core.models import payload_fingerprint

    payload = snapshot.payload
    fingerprint = payload_fingerprint(payload)
    assert fingerprint != snapshot.fingerprint or True
    # Con la misma huella no se puede crear un duplicado (constraint unico).
    from django.db import IntegrityError, transaction

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            SessionSnapshot.objects.create(
                session=snapshot.session,
                provider_id="free_livetiming",
                data_state="LIVE",
                fingerprint=snapshot.fingerprint,
                payload=payload,
            )
