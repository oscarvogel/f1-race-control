"""Pruebas del ProviderManager: seleccion, semantica y fallback."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from providers.base import (
    Driver,
    ProviderCapabilities,
    ProviderError,
    ProviderStatus,
    SessionInfo,
    TimingEntry,
    TimingProvider,
    UnsupportedCapability,
)
from providers.manager import SCOPE_HISTORICAL, SCOPE_LIVE, ProviderManager


class FakeProvider(TimingProvider):
    """Proveedor de prueba con capacidades y comportamiento configurables."""

    def __init__(
        self,
        provider_id: str,
        *,
        live: bool = False,
        historical: bool = False,
        metadata: bool = False,
        timing: bool = True,
        connected: bool = True,
        error: Exception | None = None,
        unsupported: bool = False,
    ) -> None:
        self.provider_id = provider_id
        self.display_name = f"Proveedor {provider_id}"
        self.endpoint = f"http://{provider_id}.test"
        self._caps = ProviderCapabilities(
            provider_id=provider_id,
            live=live,
            historical=historical,
            metadata=metadata,
            timing=timing,
        )
        self._connected = connected
        self._error = error
        self._unsupported = unsupported
        super().__init__()
        self.status.capabilities = self._caps
        self.status.is_connected = connected
        self.status.state = "CONNECTED" if connected else "DISCONNECTED"

    async def connect(self) -> bool:
        return self._connected

    async def disconnect(self) -> None:
        self.status.is_connected = False

    async def health_check(self) -> ProviderStatus:
        return self.status

    async def get_capabilities(self) -> ProviderCapabilities:
        return self._caps

    async def get_session(self) -> SessionInfo | None:
        if self._error:
            raise self._error
        if self._unsupported:
            raise self._unsupported_error()
        return SessionInfo(provider_id=self.provider_id, provider_session_id="1")

    def _unsupported_error(self) -> UnsupportedCapability:
        return self._unsupported_exc or UnsupportedCapability("no soportado")

    _unsupported_exc: UnsupportedCapability | None = None

    async def get_drivers(self) -> list[Driver]:
        return []

    async def get_timing(self) -> list[TimingEntry]:
        if self._error:
            raise self._error
        if self._unsupported:
            raise self._unsupported_error()
        return [
            TimingEntry(
                provider_id=self.provider_id,
                driver_number="1",
                position=1,
            )
        ]

    async def get_laps(self) -> list:
        return []

    async def get_stints(self) -> list:
        return []

    async def get_tyres(self) -> list:
        return []

    async def get_weather(self):
        return None

    async def get_race_control(self) -> list:
        return []

    async def get_telemetry(self) -> list:
        if self._unsupported:
            raise self._unsupported_error()
        return []

    async def get_positions(self) -> list:
        return []


# --------------------------------------------------------------------------- #
# Seleccion de proveedor
# --------------------------------------------------------------------------- #


def test_el_proveedor_configurado_tiene_prioridad():
    live = FakeProvider("free_livetiming", live=True)
    other = FakeProvider("otro", live=True)
    manager = ProviderManager(
        providers=[live, other], live_provider="otro", mode=SCOPE_LIVE
    )
    assert manager.select_provider("timing", SCOPE_LIVE) is other


def test_solo_se_eligen_proveedores_del_ambito():
    historico = FakeProvider("openf1", historical=True)
    live = FakeProvider("free_livetiming", live=True)
    manager = ProviderManager(providers=[historico, live], mode="auto")

    assert manager.select_provider("timing", SCOPE_LIVE) is live
    assert manager.select_provider("laps", SCOPE_HISTORICAL) is historico


def test_no_hay_fallback_de_live_a_historico():
    """Regla critica: un pedido live jamas se resuelve con datos historicos."""
    historico = FakeProvider("openf1", historical=True)
    manager = ProviderManager(providers=[historico], mode="auto")

    data, provider_id = asyncio.run(manager.fetch("timing", SCOPE_LIVE))
    assert data is None
    assert provider_id is None
    assert "live" in manager.last_error.get("*", "")


def test_se_prefiere_el_proveedor_conectado():
    caido = FakeProvider("caido", live=True, connected=False)
    vivo = FakeProvider("vivo", live=True, connected=True)
    manager = ProviderManager(providers=[caido, vivo], mode=SCOPE_LIVE)
    assert manager.select_provider("timing", SCOPE_LIVE) is vivo


def test_error_de_un_proveedor_no_rompe_la_consulta():
    roto = FakeProvider("roto", live=True, error=ProviderError("se cayo"))
    manager = ProviderManager(providers=[roto], mode=SCOPE_LIVE)
    data, provider_id = asyncio.run(manager.fetch("timing", SCOPE_LIVE))
    assert data is None
    assert provider_id is None
    assert "se cayo" in manager.last_error["roto"]


def test_capacidad_no_soportada_no_se_confunde_con_error():
    provider = FakeProvider("parcial", live=True)
    provider._unsupported = True
    manager = ProviderManager(providers=[provider], mode=SCOPE_LIVE)
    data, provider_id = asyncio.run(manager.fetch("telemetry", SCOPE_LIVE))
    assert data is None
    assert provider_id is None
    assert "no soporta" in manager.last_error["parcial"]


def test_el_resultado_conserva_el_proveedor_de_origen():
    live = FakeProvider("free_livetiming", live=True)
    manager = ProviderManager(providers=[live], mode=SCOPE_LIVE)
    entries, provider_id = asyncio.run(manager.fetch("timing", SCOPE_LIVE))
    assert provider_id == "free_livetiming"
    assert entries[0].provider_id == "free_livetiming"


# --------------------------------------------------------------------------- #
# Estados de datos
# --------------------------------------------------------------------------- #


def _manager_with(connected: bool, age: float | None, session_state: str | None):
    provider = FakeProvider("free_livetiming", live=True, connected=connected)
    manager = ProviderManager(
        providers=[provider],
        live_provider="free_livetiming",
        mode=SCOPE_LIVE,
        live_max_age_seconds=90,
        delayed_max_age_seconds=300,
    )
    manager._capability_cache["free_livetiming"] = provider._caps
    provider.status.data_age_seconds = age
    if age is not None:
        provider.status.last_message_at = datetime.now(timezone.utc) - timedelta(seconds=age)
    session = (
        SessionInfo(
            provider_id="free_livetiming",
            provider_session_id="11392",
            state=session_state,
        )
        if session_state is not None
        else None
    )
    return manager, session


def test_estado_live():
    manager, session = _manager_with(True, 3.0, "Started")
    assert manager.classify_state(session) == "LIVE"


def test_estado_delayed():
    manager, session = _manager_with(True, 150.0, "Started")
    assert manager.classify_state(session) == "DELAYED"


def test_estado_historical_con_sesion_finalizada():
    manager, session = _manager_with(True, 3.0, "Finalised")
    assert manager.classify_state(session) == "HISTORICAL"


def test_estado_waiting_sin_datos():
    manager, session = _manager_with(True, None, "Started")
    assert manager.classify_state(session) == "WAITING"


def test_estado_offline_sin_conexion():
    manager, session = _manager_with(False, None, "Started")
    assert manager.classify_state(session) == "OFFLINE"


def test_estado_waiting_sin_sesion_detectada():
    manager, session = _manager_with(True, 3.0, None)
    assert manager.classify_state(session) == "WAITING"


# --------------------------------------------------------------------------- #
# Diagnostico
# --------------------------------------------------------------------------- #


def test_diagnostico_incluye_los_proveedores():
    live = FakeProvider("free_livetiming", live=True)
    manager = ProviderManager(providers=[live], live_provider="free_livetiming")
    diagnostics = manager.diagnostics()
    assert diagnostics["live_provider"] == "free_livetiming"
    assert len(diagnostics["providers"]) == 1
    assert diagnostics["providers"][0]["provider_id"] == "free_livetiming"
