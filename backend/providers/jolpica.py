"""Adaptador de Jolpica (Ergast F1 API) para metadatos.

Documentacion: https://api.jolpi.ca/docs/

Uso previsto, segun lo pedido:

* calendario de la temporada,
* resultados y sesiones,
* metadatos de pilotos, equipos y circuitos.

**No** es una fuente de telemetria en vivo ni de cronometraje. Por eso sus
capacidades de ``live``/``telemetry``/``timing`` estan en ``False``: el
:class:`~providers.manager.ProviderManager` nunca lo usara para clasificar en
vivo.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import (
    Driver,
    ProviderCapabilities,
    ProviderError,
    ProviderStatus,
    SessionInfo,
    TimingProvider,
    parse_timestamp,
    to_int,
)


class JolpicaProvider(TimingProvider):
    """Proveedor de metadatos: calendario, circuitos, equipos y resultados."""

    provider_id = "jolpica"
    display_name = "Jolpica (Ergast) - calendario y metadatos"

    # API externa: comprobarla en cada ciclo (cada 3 s) no aporta nada y suma
    # carga a un servicio de terceros que no es la fuente de cronometraje.
    health_check_interval = 300.0

    def __init__(self, base_url: str = "https://api.jolpi.ca/ergast/f1", timeout: float = 30.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = self.base_url
        self.timeout = timeout
        super().__init__()
        self._client: httpx.AsyncClient | None = None

    # -- ciclo de vida ----------------------------------------------------- #

    async def connect(self) -> bool:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            headers={"Accept": "application/json", "User-Agent": "RaceCenter/1.0"},
            follow_redirects=True,
        )
        try:
            status = await self.health_check()
        except Exception:
            status = None
        return bool(status and status.is_connected)

    async def disconnect(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self.status.is_connected = False
        self.status.state = "OFFLINE"

    async def health_check(self) -> ProviderStatus:
        started = time.perf_counter()
        try:
            payload = await self._get_json("/current.json")
        except ProviderError as exc:
            self.status.is_connected = False
            self.status.state = "ERROR"
            self.status.last_error = str(exc)
            self.status.updated_at = datetime.now(timezone.utc)
            raise

        latency_ms = (time.perf_counter() - started) * 1000.0
        self.status.is_connected = True
        self.status.state = "CONNECTED"
        self.status.latency_ms = round(latency_ms, 2)
        self.status.last_error = None
        self.status.updated_at = datetime.now(timezone.utc)
        self.status.capabilities = await self.get_capabilities()
        return self.status

    async def get_capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            provider_id=self.provider_id,
            live=False,
            historical=True,
            metadata=True,
            timing=False,
            laps=False,
            sectors=False,
            tyres=False,
            weather=False,
            race_control=False,
            telemetry=False,
            positions=False,
            notes=(
                "Solo calendario, resultados y metadatos. "
                "No es fuente de telemetria ni de cronometraje en vivo."
            ),
        )

    # -- transporte -------------------------------------------------------- #

    async def _get_json(self, path: str) -> dict[str, Any]:
        if self._client is None:
            await self.connect()
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            self._record_error(exc)
            raise ProviderError("Fallo de red hacia Jolpica %s: %s" % (path, exc)) from exc
        if response.status_code == 429:
            raise ProviderError("Jolpica respondio 429 (limite de tasa) en %s." % path)
        if response.status_code >= 400:
            message = "Jolpica respondio HTTP %s en %s." % (response.status_code, path)
            self._record_error(ProviderError(message))
            raise ProviderError(message)
        try:
            return response.json()
        except ValueError as exc:
            self._record_error(exc)
            raise ProviderError("Respuesta no-JSON de Jolpica en %s." % path) from exc

    # -- calendario -------------------------------------------------------- #

    async def get_calendar(self, season: int | None = None) -> list[dict[str, Any]]:
        """Devuelve el calendario de la temporada como lista normalizada."""
        path = "/%d.json" % season if season else "/current.json"
        payload = await self._get_json(path)
        races = (
            payload.get("MRData", {})
            .get("RaceTable", {})
            .get("Races", [])
        )
        return races

    async def get_meetings(self, season: int | None = None) -> list[dict[str, Any]]:
        return await self.get_calendar(season)

    async def get_round_schedule(
        self, season: int, round_number: int
    ) -> list[dict[str, Any]]:
        """Horarios de las sesiones de una ronda.

        Es la alternativa al catalogo de OpenF1: **mientras hay una sesion de
        F1 en curso, OpenF1 bloquea todo el acceso, incluso a sesiones
        pasadas**, y el calendario se queda sin poder consultarse. Jolpica no
        se bloquea, asi que el catalogo puede seguir saliendo de ahi.

        Devuelve una lista de ``{session_name, session_type, start_time_utc}``.
        """
        payload = await self._get_json("/%d/%d.json" % (season, round_number))
        races = (
            payload.get("MRData", {})
            .get("RaceTable", {})
            .get("Races", [])
        )
        if not races:
            return []
        race = races[0]
        circuit = race.get("Circuit") or {}
        location = circuit.get("Location") or {}

        def _stamp(block: dict[str, Any] | None) -> str | None:
            if not block:
                return None
            date = block.get("date")
            if not date:
                return None
            time = (block.get("time") or "").strip()
            if not time:
                return "%sT00:00:00+00:00" % date
            if time.endswith("Z"):
                time = time[:-1]
            if len(time) == 5:
                time += ":00"
            return "%sT%s+00:00" % (date, time)

        # Orden en el que se corren las sesiones de un fin de semana.
        orden = [
            ("FirstPractice", "Practice", "Practice 1"),
            ("SecondPractice", "Practice", "Practice 2"),
            ("ThirdPractice", "Practice", "Practice 3"),
            ("Sprint", "Sprint", "Sprint"),
            ("SprintQualifying", "Sprint Qualifying", "Sprint Qualifying"),
            ("Qualifying", "Qualifying", "Qualifying"),
            ("Qualifying1", "Qualifying", "Qualifying Q1"),
            ("Qualifying2", "Qualifying", "Qualifying Q2"),
            ("Qualifying3", "Qualifying", "Qualifying Q3"),
        ]

        sesiones: list[dict[str, Any]] = []
        for clave, tipo, nombre in orden:
            inicio = _stamp(race.get(clave))
            if inicio is None:
                continue
            sesiones.append(
                {
                    "session_name": nombre,
                    "session_type": tipo,
                    "start_time_utc": inicio,
                    # Jolpica no publica el fin de cada sesion: se deja vacio
                    # en vez de estimarlo.
                    "end_time_utc": None,
                }
            )

        carrera = _stamp({"date": race.get("date"), "time": race.get("time")})
        if carrera is not None:
            sesiones.append(
                {
                    "session_name": "Race",
                    "session_type": "Race",
                    "start_time_utc": carrera,
                    "end_time_utc": None,
                }
            )

        for sesion in sesiones:
            sesion["meeting_name"] = race.get("raceName")
            sesion["circuit_name"] = circuit.get("circuitName") or location.get("locality")
            sesion["location"] = location.get("locality")
            sesion["round_number"] = to_int(race.get("round"))
            sesion["season"] = str(race.get("season"))

        return sesiones

    async def find_round_by_name(
        self, season: int, race_name: str
    ) -> int | None:
        """Numero de ronda de un Gran Premio, buscado por su nombre."""
        races = await self.get_calendar(season)
        for race in races:
            if (race.get("raceName") or "").strip().lower() == race_name.strip().lower():
                return to_int(race.get("round"))
        return None

    async def get_session(self, session_key: str | int | None = None) -> SessionInfo | None:
        """Jolpica describe el calendario, no una sesion activa en vivo."""
        races = await self.get_calendar()
        if not races:
            return None
        race = races[-1]
        circuit = race.get("Circuit") or {}
        location = circuit.get("Location") or {}
        qualifying = race.get("Qualifying") or {}

        return SessionInfo(
            provider_id=self.provider_id,
            provider_session_id="%s-%s" % (race.get("season"), race.get("round")),
            meeting_name=race.get("raceName"),
            official_name=race.get("raceName"),
            circuit_name=circuit.get("circuitName"),
            location=location.get("locality"),
            country_name=location.get("country"),
            season=str(race.get("season")),
            round_number=to_int(race.get("round")),
            session_type="Race",
            session_name=race.get("raceName"),
            start_time_utc=parse_timestamp(
                "%sT%s" % (race.get("date"), race.get("time")) if race.get("time") else race.get("date")
            ),
            state="Scheduled",
            source_timestamp=datetime.now(timezone.utc),
        )

    async def get_drivers(self, session_key: str | int | None = None) -> list[Driver]:
        """Pilotos de la temporada (no de una sesion en vivo)."""
        payload = await self._get_json("/current/drivers.json")
        entries = (
            payload.get("MRData", {})
            .get("DriverTable", {})
            .get("Drivers", [])
        )
        return [
            Driver(
                provider_id=self.provider_id,
                number=str(entry.get("permanentNumber") or entry.get("driverId")),
                code=entry.get("code"),
                full_name="%s %s" % (entry.get("givenName"), entry.get("familyName")),
                first_name=entry.get("givenName"),
                last_name=entry.get("familyName"),
                country_code=entry.get("nationality"),
                source_timestamp=datetime.now(timezone.utc),
            )
            for entry in entries
        ]

    # -- capacidades no soportadas ---------------------------------------- #

    async def get_timing(self) -> list:
        raise self._unsupported("timing")

    async def get_laps(self) -> list:
        raise self._unsupported("laps")

    async def get_stints(self) -> list:
        raise self._unsupported("stints")

    async def get_tyres(self) -> list:
        raise self._unsupported("tyres")

    async def get_weather(self):
        raise self._unsupported("weather")

    async def get_race_control(self) -> list:
        raise self._unsupported("race_control")

    async def get_telemetry(self) -> list:
        raise self._unsupported("telemetry")

    async def get_positions(self) -> list:
        raise self._unsupported("positions")
