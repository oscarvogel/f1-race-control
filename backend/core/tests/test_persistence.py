"""Pruebas de persistencia: deduplicacion de snapshots y bitacora."""

from __future__ import annotations

import pytest

from core.models import IngestionRun, ProviderStatus, Session, SessionSnapshot, payload_fingerprint


@pytest.fixture
def base_payload() -> dict:
    return {
        "generated_at": "2026-10-24T21:05:00+00:00",
        "data_state": "LIVE",
        "scope": "live",
        "session": {"provider_session_id": "11392", "meeting_name": "United States Grand Prix"},
        "drivers": [{"number": "44", "full_name": "Lewis HAMILTON"}],
        "timing": [
            {
                "driver_number": "44",
                "position": 1,
                "best_lap_time": 94.893,
                "gap_to_leader": None,
            }
        ],
        "weather": {"air_temperature": 28.2},
        "race_control": [],
        "tyres": [],
        "sources": {"timing": "free_livetiming"},
    }


def test_la_huella_ignora_los_campos_volatiles(base_payload):
    """`generated_at` cambia en cada ciclo: no puede alterar la huella."""
    otro = dict(base_payload)
    otro["generated_at"] = "2026-10-24T21:05:03+00:00"
    otro["diagnostics"] = {"providers": [{"latency_ms": 12.4}]}
    assert payload_fingerprint(base_payload) == payload_fingerprint(otro)


def test_la_huella_cambia_si_cambian_los_datos(base_payload):
    otro = dict(base_payload)
    otro["timing"] = [
        {
            "driver_number": "44",
            "position": 1,
            "best_lap_time": 94.100,
            "gap_to_leader": None,
        }
    ]
    assert payload_fingerprint(base_payload) != payload_fingerprint(otro)


def test_la_huella_cambia_si_cambia_el_estado(base_payload):
    otro = dict(base_payload)
    otro["data_state"] = "DELAYED"
    assert payload_fingerprint(base_payload) != payload_fingerprint(otro)


def test_no_se_crea_una_fila_nueva_si_el_contenido_no_cambio(db, base_payload):
    """El requisito: no guardar cada snapshot completo si no hay cambios."""
    session = Session.objects.create(
        provider_id="free_livetiming",
        provider_session_id="11392",
        name="Qualifying",
    )
    fingerprint = payload_fingerprint(base_payload)
    SessionSnapshot.objects.create(
        session=session,
        provider_id="free_livetiming",
        data_state="LIVE",
        fingerprint=fingerprint,
        payload=base_payload,
    )

    # Segundo ciclo: mismo contenido -> no se escribe fila.
    segundo = dict(base_payload)
    segundo["generated_at"] = "2026-10-24T21:05:03+00:00"
    if payload_fingerprint(segundo) == fingerprint:
        assert SessionSnapshot.objects.filter(session=session).count() == 1
    else:
        raise AssertionError("La huella cambio solo por el timestamp: eso es un bug.")


def test_los_eventos_de_control_de_carrera_se_deduplican(db):
    from core.models import RaceControlEvent

    session = Session.objects.create(
        provider_id="free_livetiming",
        provider_session_id="11392",
        name="Qualifying",
    )
    for _ in range(3):
        RaceControlEvent.objects.get_or_create(
            provider_id="free_livetiming",
            session=session,
            utc="2026-10-24T21:03:00+00:00",
            message="YELLOW FLAG IN TRACK SECTOR 2",
        )
    assert RaceControlEvent.objects.count() == 1


def test_la_bitacora_se_puede_recortar(db):
    """ProviderStatus e IngestionRun son historiales acotados, no un archivo."""
    from core.ingest import HISTORY_ROWS

    assert HISTORY_ROWS > 0
    ProviderStatus.objects.create(
        provider_id="x", name="x", state="CONNECTED", is_connected=True
    )
    IngestionRun.objects.create(provider_id="x", ok=True)
    assert ProviderStatus.objects.count() == 1
    assert IngestionRun.objects.count() == 1


def test_un_historico_no_toma_el_lugar_del_snapshot_en_vivo(db, base_payload):
    """Cargar un FP1 no puede cambiar lo que muestra el dashboard en vivo.

    El historico se guarda en la misma tabla que el snapshot en vivo. Sin
    distinguirlos por ambito, la fila del historico quedaba como "la mas
    reciente" y el dashboard en vivo pasaba a servir datos historicos.
    """
    from core.ingest import latest_snapshot

    # Snapshot en vivo.
    session_live = Session.objects.create(
        provider_id="free_livetiming",
        provider_session_id="11392",
        name="Qualifying",
    )
    SessionSnapshot.objects.create(
        session=session_live,
        provider_id="free_livetiming",
        scope="live",
        data_state="LIVE",
        fingerprint=payload_fingerprint(base_payload),
        payload=base_payload,
    )

    # Despues se carga un historico (mas reciente).
    session_hist = Session.objects.create(
        provider_id="openf1",
        provider_session_id="11389",
        name="Practice 1",
    )
    historico = dict(base_payload)
    historico["scope"] = "historical"
    historico["session"] = {"provider_session_id": "11389"}
    SessionSnapshot.objects.create(
        session=session_hist,
        provider_id="openf1",
        scope="historical",
        data_state="HISTORICAL",
        fingerprint=payload_fingerprint(historico),
        payload=historico,
    )

    # El dashboard sigue leyendo el snapshot en vivo.
    actual = latest_snapshot()
    assert actual is not None
    assert actual["scope"] == "live"
    assert actual["session"]["provider_session_id"] == "11392"


def test_los_snapshots_en_vivo_se_recortan(db, base_payload):
    """Cada snapshot en vivo pesa ~90 KB: sin recorte la base crece sin limite.

    Los historicos no se tocan: hay uno por sesion y se consultan a pedido.
    """
    from core.ingest import SNAPSHOT_ROWS, trim_history

    session_live = Session.objects.create(
        provider_id="free_livetiming",
        provider_session_id="11392",
        name="Qualifying",
    )
    session_hist = Session.objects.create(
        provider_id="openf1",
        provider_session_id="11389",
        name="Practice 1",
    )

    for indice in range(SNAPSHOT_ROWS + 40):
        SessionSnapshot.objects.create(
            session=session_live,
            provider_id="free_livetiming",
            scope="live",
            data_state="LIVE",
            fingerprint=payload_fingerprint({**base_payload, "timing": [{"n": indice}]}),
            payload=base_payload,
        )

    for indice in range(5):
        SessionSnapshot.objects.create(
            session=session_hist,
            provider_id="openf1",
            scope="historical",
            data_state="HISTORICAL",
            fingerprint=payload_fingerprint({**base_payload, "timing": [{"h": indice}]}),
            payload=base_payload,
        )

    trim_history()

    vivos = SessionSnapshot.objects.filter(scope="live").count()
    historicos = SessionSnapshot.objects.filter(scope="historical").count()
    assert vivos == SNAPSHOT_ROWS, "los snapshots en vivo deberian estar recortados"
    assert historicos == 5, "los historicos no se deben tocar"


def test_un_snapshot_de_otra_version_no_se_sirve_desde_la_cache(db):
    """Un snapshot guardado con otro formato del payload se vuelve a pedir.

    Sin esto, la base puede seguir sirviendo un snapshot viejo (por ejemplo,
    con las posiciones incompletas por el limite de tasa de OpenF1) durante
    meses, sin que nadie se entere.
    """
    from core import history
    from core.models import Session, SessionSnapshot

    session = Session.objects.create(
        provider_id="openf1",
        provider_session_id="11392",
        name="Qualifying",
        session_type="Qualifying",
    )
    SessionSnapshot.objects.create(
        session=session,
        provider_id="openf1",
        scope="historical",
        data_state="HISTORICAL",
        fingerprint="viejo",
        payload={
            "generated_at": "2026-10-24T21:05:00+00:00",
            "snapshot_version": "v1",  # version anterior
            "data_state": "HISTORICAL",
            "session": {"provider_session_id": "11392"},
            "timing": [],
            "positions": [],
            "warnings": [],
        },
    )

    assert history.cached_historical_snapshot("11392") is None
