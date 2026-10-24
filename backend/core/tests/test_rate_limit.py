"""Pruebas del manejo de limite de tasa y de degradacion elegante.

Contexto real (medido contra la API el 24/10/2026): OpenF1 limita la tasa
por IP y responde **429 con la cabecera ``retry-after: 60``**. Tres
comportamientos tienen que quedar garantizados:

1. El proveedor respeta la cadencia de health check declarada: un proveedor
   externo no se sondea en cada ciclo de ingesta.
2. Ante un 429 se espera lo que pide el servidor y se recuerda el cooldown,
   sin emitir peticiones durante ese periodo.
3. Un snapshot historico incompleto no es un fallo: la parte opcional se
   degrada, se anota el motivo y el resto de la sesion se entrega igual.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from core import history
from core.history import build_historical_snapshot
from providers import openf1 as openf1_module
from providers.base import (
    Driver,
    ProviderRateLimited,
    SessionInfo,
    TimingEntry,
    TimingProvider,
)
from providers.manager import ProviderManager
from providers.openf1 import OpenF1Provider

# --------------------------------------------------------------------------- #
# Utilidades de prueba
# --------------------------------------------------------------------------- #


class FakeResponse:
    def __init__(self, status_code: int, payload=None, headers=None) -> None:
        self.status_code = status_code
        self._payload = [] if payload is None else payload
        self.headers = headers or {}

    def json(self):
        return self._payload


class FakeClient:
    """Cliente HTTP de prueba: devuelve respuestas en orden y registra las URLs."""

    def __init__(self, responses) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    async def get(self, url: str) -> FakeResponse:
        self.calls.append(url)
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _reset_rate_limit_state(monkeypatch):
    """El cooldown y el intervalo son estado de modulo: se reinician por test."""
    monkeypatch.setattr(openf1_module, "_cooldown_until", 0.0)
    monkeypatch.setattr(openf1_module, "_last_request_at", 0.0)
    monkeypatch.setattr(openf1_module, "MIN_REQUEST_INTERVAL_SECONDS", 0.0)


# --------------------------------------------------------------------------- #
# 1. Cadencia del health check
# --------------------------------------------------------------------------- #


class CountingProvider(TimingProvider):
    provider_id = "contado"
    display_name = "Proveedor contado"
    endpoint = "http://contado.test"

    def __init__(self, interval: float = 0.0) -> None:
        self.health_check_interval = interval
        self.checks = 0
        super().__init__()

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def health_check(self):
        self.checks += 1
        self.status.is_connected = True
        self.status.state = "CONNECTED"
        return self.status

    async def get_capabilities(self):
        return None

    async def get_session(self):
        return None

    async def get_drivers(self):
        return []

    async def get_timing(self):
        return []

    async def get_laps(self):
        return []

    async def get_stints(self):
        return []

    async def get_tyres(self):
        return []

    async def get_weather(self):
        return None

    async def get_race_control(self):
        return []

    async def get_telemetry(self):
        return []

    async def get_positions(self):
        return []


def test_el_health_check_respeta_la_cadencia_declarada():
    provider = CountingProvider(interval=300.0)
    manager = ProviderManager(providers=[provider])

    asyncio.run(manager.refresh_status())
    asyncio.run(manager.refresh_status())
    asyncio.run(manager.refresh_status())

    assert provider.checks == 1, "no debe sondear un proveedor con cadencia larga"


def test_force_ignora_la_cadencia():
    provider = CountingProvider(interval=300.0)
    manager = ProviderManager(providers=[provider])

    asyncio.run(manager.refresh_status())
    asyncio.run(manager.refresh_status(force=True))

    assert provider.checks == 2


def test_sin_cadencia_se_sondea_en_cada_ciclo():
    provider = CountingProvider(interval=0.0)
    manager = ProviderManager(providers=[provider])

    asyncio.run(manager.refresh_status())
    asyncio.run(manager.refresh_status())

    assert provider.checks == 2


# --------------------------------------------------------------------------- #
# 2. Limite de tasa de OpenF1
# --------------------------------------------------------------------------- #


def test_se_reintenta_respetando_el_retry_after():
    provider = OpenF1Provider()
    provider._client = FakeClient(
        [
            FakeResponse(429, headers={"retry-after": "0.05"}),
            FakeResponse(200, payload=[{"driver_number": 44, "name_acronym": "HAM"}]),
        ]
    )

    rows = asyncio.run(provider.get_drivers("11389"))

    assert len(rows) == 1
    assert rows[0].number == "44"
    assert len(provider._client.calls) == 2


def test_agotados_los_reintentos_levanta_error_de_cuota():
    provider = OpenF1Provider()
    provider._client = FakeClient(
        [FakeResponse(429, headers={"retry-after": "0.01"})] * 3
    )

    with pytest.raises(ProviderRateLimited):
        asyncio.run(provider.get_drivers("11389"))

    assert len(provider._client.calls) == 3


def test_la_espera_respeta_el_retry_after_del_servidor():
    """Un 429 con retry-after: 1 obliga a esperar un segundo, no lo que uno quiera."""
    provider = OpenF1Provider()
    provider._client = FakeClient(
        [
            FakeResponse(429, headers={"retry-after": "1"}),
            FakeResponse(200, payload=[]),
        ]
    )

    started = time.monotonic()
    asyncio.run(provider.get_drivers("11389"))
    elapsed = time.monotonic() - started

    assert elapsed >= 1.0, "no se respeta el retry-after del servidor"


def test_durante_el_cooldown_no_se_emite_ninguna_peticion():
    """Con el cooldown vigente, preguntar solo gastaria cuota."""
    provider = OpenF1Provider()
    provider._client = FakeClient([FakeResponse(200, payload=[])])

    openf1_module._cooldown_until = time.monotonic() + 30.0

    with pytest.raises(ProviderRateLimited):
        asyncio.run(provider.get_drivers("11389"))

    assert provider._client.calls == [], "no se debe gastar cuota durante el cooldown"


def test_el_cooldown_impide_incluso_a_otro_proveedor_del_proceso():
    """El cooldown es del servicio (por IP), no de una instancia."""
    otro = OpenF1Provider()
    otro._client = FakeClient([FakeResponse(200, payload=[])])

    openf1_module._cooldown_until = time.monotonic() + 30.0

    with pytest.raises(ProviderRateLimited):
        asyncio.run(otro.get_drivers("11389"))

    assert otro._client.calls == []


def test_un_429_no_deja_el_proveedor_en_error():
    """Agotar la cuota no significa que el proveedor este caido."""
    provider = OpenF1Provider()
    provider.status.is_connected = True
    provider.status.state = "CONNECTED"
    provider._client = FakeClient(
        [FakeResponse(429, headers={"retry-after": "0.01"})] * 3
    )

    status = asyncio.run(provider.health_check())

    assert status.is_connected is True
    assert status.state == "CONNECTED"
    assert status.last_error


def test_el_health_check_de_openf1_declara_cadencia_larga():
    assert OpenF1Provider.health_check_interval >= 60.0


# --------------------------------------------------------------------------- #
# 3. Degradacion elegante del snapshot historico
# --------------------------------------------------------------------------- #


class FakeHistoricalProvider:
    """Proveedor de prueba: falla solo en la parte opcional (neumaticos)."""

    provider_id = "openf1"

    async def connect(self) -> bool:
        return True

    async def disconnect(self) -> None:
        return None

    async def get_session(self, session_key=None):
        return SessionInfo(
            provider_id="openf1",
            provider_session_id=str(session_key),
            session_name="Practice 1",
            meeting_name="United States Grand Prix",
        )

    async def get_drivers(self, session_key=None):
        return [Driver(provider_id="openf1", number="44", code="HAM")]

    async def get_timing(self, session_key=None):
        return [
            TimingEntry(
                provider_id="openf1",
                driver_number="44",
                position=1,
                best_lap_time=94.893,
            )
        ]

    async def get_stints(self, session_key=None):
        raise ProviderRateLimited("OpenF1 esta en cooldown por limite de tasa")

    async def get_weather(self, session_key=None):
        return None

    async def get_race_control(self, session_key=None):
        return []


def test_un_snapshot_incompleto_no_es_un_fallo(monkeypatch):
    monkeypatch.setattr(history, "_openf1_provider", lambda: FakeHistoricalProvider())

    payload = asyncio.run(build_historical_snapshot("11389"))

    assert payload is not None
    # La parte esencial sigue disponible.
    assert len(payload["timing"]) == 1
    assert payload["timing"][0]["driver_number"] == "44"
    assert len(payload["drivers"]) == 1
    # Y la parte que fallo queda anotada, no inventada.
    assert payload["warnings"], "la parte que fallo debe quedar registrada"
    assert "neumaticos" in payload["warnings"][0]
    assert payload["tyres"] == []


def test_sin_fallos_no_hay_avisos(monkeypatch):
    class Completo(FakeHistoricalProvider):
        async def get_stints(self, session_key=None):
            return []

    monkeypatch.setattr(history, "_openf1_provider", lambda: Completo())

    payload = asyncio.run(build_historical_snapshot("11389"))

    assert payload["warnings"] == []
