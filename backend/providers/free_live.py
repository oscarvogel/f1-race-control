"""Adaptador del servicio local ``f1-livetiming-api`` (Node.js).

Este proveedor es el candidato principal para cronometraje EN VIVO.

El servicio Node mantiene en memoria el estado del feed SignalR de la Formula 1
y lo expone por HTTP local. Este adaptador **no** habla con los servidores de la
F1: habla solo con ``http://127.0.0.1:3000``. Por eso:

* no hay credenciales de F1 en este repositorio,
* no hay scraping ni evasion de controles,
* el proveedor Node ya se ocupa del protocolo SignalR.

Los endpoints se verifican en tiempo de ejecucion: si un endpoint no existe o
devuelve algo inesperado, el adaptador lo reporta como error en vez de
inventar datos.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import httpx

from .base import (
    Driver,
    ProviderCapabilities,
    ProviderError,
    ProviderStatus,
    RaceControlEvent,
    Sector,
    SessionInfo,
    Stint,
    TelemetrySample,
    TimingEntry,
    TimingProvider,
    UnsupportedCapability,
    WeatherReport,
    parse_lap_time,
    parse_timestamp,
    to_float,
    to_int,
)

# Clave fantasma que el feed de cronometraje usa como marcador interno.
_PLACEHOLDER_KEYS = {"_kf", "_kf_", ""}

_SEGMENT_BY_KEY = {"0": "Q1", "1": "Q2", "2": "Q3"}


class FreeLiveTimingProvider(TimingProvider):
    """Proveedor de cronometraje en vivo servido por el servicio Node local."""

    provider_id = "free_livetiming"
    display_name = "F1 Live Timing (servicio local Node.js)"

    def __init__(self, base_url: str = "http://127.0.0.1:3000", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.endpoint = self.base_url
        self.timeout = timeout
        super().__init__()
        self._client: httpx.AsyncClient | None = None
        self._last_message_at: datetime | None = None
        self._raw_session: dict[str, Any] = {}

    # -- ciclo de vida ----------------------------------------------------- #

    async def connect(self) -> bool:
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=httpx.Timeout(self.timeout),
            follow_redirects=True,
            headers={"Accept": "application/json"},
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
        payload = await self._get_json("/api/status")
        latency_ms = (time.perf_counter() - started) * 1000.0

        is_connected = bool(payload.get("isConnected"))
        last_message_at = parse_timestamp(payload.get("lastMessageAt"))
        if last_message_at:
            self._last_message_at = last_message_at

        self.status.is_connected = is_connected
        self.status.state = "CONNECTED" if is_connected else "DISCONNECTED"
        self.status.latency_ms = round(latency_ms, 2)
        self.status.last_message_at = last_message_at
        self.status.data_age_seconds = self._data_age_seconds(last_message_at)
        self.status.last_error = None if is_connected else (
            "El servicio esta arrancado pero sin conexion al feed de cronometraje."
        )
        self.status.updated_at = datetime.now(timezone.utc)
        self.status.capabilities = await self.get_capabilities()
        return self.status

    def _data_age_seconds(self, last_message_at: datetime | None) -> float | None:
        if not last_message_at:
            return None
        delta = datetime.now(timezone.utc) - last_message_at
        return round(delta.total_seconds(), 3)

    async def get_capabilities(self) -> ProviderCapabilities:
        """Capacidades reales del proveedor live.

        Se declaran segun lo que el servicio expone efectivamente. La
        telemetria de vehiculo y las coordenadas GPS **no** estan disponibles
        en este feed, por lo que se marcan como no soportadas en lugar de
        inventarlas.
        """
        return ProviderCapabilities(
            provider_id=self.provider_id,
            live=True,
            historical=False,
            metadata=True,
            timing=True,
            laps=True,
            sectors=True,
            tyres=True,
            weather=True,
            race_control=True,
            telemetry=True,
            positions=True,
            notes=(
                "Cronometraje en vivo via SignalR, con posicion sobre el circuito y "
                "telemetria por auto (canal CarData)."
            ),
        )

    # -- transporte -------------------------------------------------------- #

    async def _get_json(self, path: str) -> dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=httpx.Timeout(self.timeout),
                follow_redirects=True,
                headers={"Accept": "application/json"},
            )
        try:
            response = await self._client.get(path)
        except httpx.HTTPError as exc:
            self._record_error(exc)
            raise ProviderError("Fallo de red hacia %s: %s" % (path, exc)) from exc

        if response.status_code == 404:
            raise ProviderError("El endpoint %s no existe en el proveedor live." % path)
        if response.status_code == 429:
            raise ProviderError("El proveedor live respondio 429 (limite de tasa) en %s." % path)
        if response.status_code >= 400:
            self._record_error(ProviderError("HTTP %s en %s" % (response.status_code, path)))
            raise ProviderError(
                "El proveedor live respondio HTTP %s en %s." % (response.status_code, path)
            )

        try:
            return response.json()
        except ValueError as exc:
            self._record_error(exc)
            raise ProviderError("Respuesta no-JSON del proveedor live en %s." % path) from exc

    # -- datos ------------------------------------------------------------- #

    async def get_session(self) -> SessionInfo | None:
        payload = await self._get_json("/api/session")
        session = payload.get("Session") or {}
        if not session:
            return None
        self._raw_session = session

        meeting = session.get("Meeting") or {}
        circuit = meeting.get("Circuit") or {}
        country = meeting.get("Country") or {}
        archive = session.get("ArchiveStatus") or {}

        start_time = self._combine_offset(session.get("StartDate"), session.get("GmtOffset"))
        end_time = self._combine_offset(session.get("EndDate"), session.get("GmtOffset"))

        session_key = session.get("Key")
        session_type = session.get("Type")
        session_name = session.get("Name")

        return SessionInfo(
            provider_id=self.provider_id,
            provider_session_id=str(session_key) if session_key is not None else "",
            meeting_name=meeting.get("Name"),
            official_name=meeting.get("OfficialName"),
            circuit_name=circuit.get("ShortName") or meeting.get("Location"),
            location=meeting.get("Location"),
            country_name=country.get("Name"),
            country_code=country.get("Code"),
            season=str(meeting.get("Year")) if meeting.get("Year") else None,
            round_number=to_int(meeting.get("Number")),
            meeting_key=to_int(meeting.get("Key")),
            circuit_key=to_int(circuit.get("Key")),
            session_type=session_type,
            session_name=session_name,
            session_number=to_int(session.get("Number")),
            start_time_utc=start_time,
            end_time_utc=end_time,
            state=session.get("SessionStatus"),
            archive_status=archive.get("Status"),
            gmt_offset=session.get("GmtOffset"),
            source_timestamp=self._last_message_at or datetime.now(timezone.utc),
        )

    @staticmethod
    def _combine_offset(local_naive: str | None, gmt_offset: str | None) -> datetime | None:
        """Convierte la hora local del circuito a UTC usando el GMT offset."""
        if not local_naive:
            return None
        base = parse_timestamp(local_naive)
        if base is None:
            return None
        if not gmt_offset:
            return base
        try:
            sign = -1 if gmt_offset.strip().startswith("-") else 1
            digits = gmt_offset.strip().lstrip("+-")
            parts = digits.split(":")
            hours = int(parts[0])
            minutes = int(parts[1]) if len(parts) > 1 else 0
            seconds = int(parts[2]) if len(parts) > 2 else 0
            offset_seconds = sign * (hours * 3600 + minutes * 60 + seconds)
        except (ValueError, IndexError):
            return base
        from datetime import timedelta

        return base - timedelta(seconds=offset_seconds)

    async def get_drivers(self) -> list[Driver]:
        payload = await self._get_json("/api/drivers")
        drivers_raw = payload.get("Drivers") or {}
        return [
            self._normalise_driver(number, data)
            for number, data in drivers_raw.items()
            if number not in _PLACEHOLDER_KEYS and isinstance(data, dict)
        ]

    def _normalise_driver(self, number: str, data: dict[str, Any]) -> Driver:
        return Driver(
            provider_id=self.provider_id,
            number=str(data.get("RacingNumber") or number),
            code=data.get("Tla"),
            full_name=data.get("FullName"),
            broadcast_name=data.get("BroadcastName"),
            first_name=data.get("FirstName"),
            last_name=data.get("LastName"),
            team_name=data.get("TeamName"),
            team_colour=data.get("TeamColour"),
            country_code=(data.get("CountryCode") or data.get("Nationality") or None),
            line=to_int(data.get("Line")),
            headshot_url=data.get("HeadshotUrl"),
            source_timestamp=self._last_message_at,
        )

    async def get_timing(self) -> list[TimingEntry]:
        standings_payload, leaderboard_payload = await asyncio.gather(
            self._get_json("/api/standings"),
            self._get_json("/api/leaderboard"),
            return_exceptions=False,
        )

        lines = standings_payload.get("Lines") or {}
        leaderboard_lines = leaderboard_payload.get("Lines") or {}
        order = standings_payload.get("Leaderboard") or list(lines.keys())

        entries: list[TimingEntry] = []
        for number in order:
            if number in _PLACEHOLDER_KEYS:
                continue
            line = lines.get(number)
            if not isinstance(line, dict):
                continue
            entries.append(self._normalise_entry(number, line, leaderboard_lines.get(number) or {}))

        # Pilotos presentes en el leaderboard pero no en la clasificacion.
        for number, line in leaderboard_lines.items():
            if number in _PLACEHOLDER_KEYS or not isinstance(line, dict):
                continue
            if any(entry.driver_number == number for entry in entries):
                continue
            entries.append(self._normalise_entry(number, line, line))

        return entries

    def _normalise_entry(
        self,
        number: str,
        line: dict[str, Any],
        app_line: dict[str, Any],
    ) -> TimingEntry:
        driver = self._normalise_driver(number, line)

        sectors = self._normalise_sectors(line.get("Sectors"))

        best_lap_raw = line.get("BestLapTime") or {}
        best_lap = parse_lap_time(best_lap_raw.get("Value") if isinstance(best_lap_raw, dict) else best_lap_raw)
        best_lap_lap = to_int(best_lap_raw.get("Lap")) if isinstance(best_lap_raw, dict) else None
        overall_fastest = bool(best_lap_raw.get("OverallFastest")) if isinstance(best_lap_raw, dict) else False

        best_lap_times = self._normalise_best_lap_times(line.get("BestLapTimes"))

        # La "mejor vuelta" que cuenta es la que publico el feed en
        # `BestLapTime`: en una eliminatoria, ese campo trae el tiempo del
        # **ultimo segmento alcanzado** (el Q3 de los que llegaron a Q3, el Q2
        # de los que se quedaron en Q2...), que es el tiempo con el que se
        # clasifican.
        #
        # No se puede tomar el mas rapido de todos los segmentos: en la
        # clasificacion de Austin 2026, el mejor tiempo de Norris (1:34.539 en
        # Q2) no cuenta porque se clasifica con su Q3 (1:35.049), y el de
        # Leclerc (1:34.198 en Q2) tampoco: se clasifica con su Q3 (1:34.267).
        # Con el minimo entre segmentos la app mostraba tiempos que no
        # existen en la clasificacion oficial.
        #
        # Durante el knockout (Q3) el feed vacia ese campo: pasa a
        # `{"Value": "", "Lap": N, "_deleted": ["Lap"]}` porque lo que cuenta
        # ahi es la vuelta de Q3. Si solo se mirara ese campo, los pilotos que
        # aun no hicieron su vuelta de Q3 aparecian sin mejor vuelta, aunque
        # tuvieran un Q1 o un Q2. Por eso, cuando viene vacio, se recurre a los
        # mejores por segmento y se queda el mas rapido de todos.
        if best_lap is None:
            for segmento, tiempo in best_lap_times.items():
                if tiempo is None:
                    continue
                if best_lap is None or tiempo < best_lap:
                    best_lap = tiempo
                    best_lap_lap = self._best_lap_number(line.get("BestLapTimes"), segmento)
        else:
            # El feed marca con `_deleted` el numero de vuelta cuando ya no es
            # confiable (en la eliminatoria quedo desfasado). En ese caso no
            # se muestra un numero de vuelta equivocado.
            if isinstance(best_lap_raw, dict) and "Lap" in (best_lap_raw.get("_deleted") or []):
                best_lap_lap = None

        last_lap_raw = line.get("LastLapTime") or {}
        last_lap = parse_lap_time(last_lap_raw.get("Value") if isinstance(last_lap_raw, dict) else last_lap_raw)

        gap = self._value_of(line.get("GapToLeader"))
        interval = self._value_of(line.get("IntervalToPositionAhead"))

        time_diff_fastest = self._clean_gap(line.get("TimeDiffToFastest"))
        time_diff_ahead = self._clean_gap(line.get("TimeDiffToPositionAhead"))
        fastest_segment: str | None = None
        ahead_segment: str | None = None

        # En clasificacion los gaps NO vienen en el nivel superior: vienen
        # dentro de `Stats`, y la clave del intervalo esta escrita con otra
        # grafia ("TimeDifftoPositionAhead", con la "to" en minuscula).
        #
        # El feed entrega `Stats` de dos formas y hay que soportar ambas:
        #   * dict  {"0": {...}}        -> una entrada por segmento ya corrido
        #   * lista [Q1, Q2, Q3]       -> una entrada por segmento de la quali
        # Ademas el valor util NO siempre esta en el indice 0: un piloto que
        # hizo su mejor tiempo en Q2 lo tiene en el indice 1. Por eso se
        # recorren todos los segmentos y se queda el ultimo con dato, que es
        # el gap mas reciente que publico F1 para ese piloto. El indice del
        # segmento del que viene el gap se expone aparte para poder etiquetar
        # la columna (Q1/Q2/Q3) y no mezclar gaps de segmentos distintos.
        for segment, stats_entry in self._stats_entries(line.get("Stats")):
            fastest = self._clean_gap(stats_entry.get("TimeDiffToFastest"))
            ahead = self._clean_gap(
                stats_entry.get("TimeDifftoPositionAhead")
                or stats_entry.get("TimeDiffToPositionAhead")
            )
            if fastest:
                time_diff_fastest = fastest
                fastest_segment = segment
            if ahead:
                time_diff_ahead = ahead
                ahead_segment = segment

        compound, tyre_age, tyre_new, grid_pos = self._tyre_from_app(app_line, line)

        speeds_raw = line.get("Speeds") or {}
        speeds = {
            key: to_float((value or {}).get("Value"))
            for key, value in speeds_raw.items()
            if isinstance(value, dict)
        }

        return TimingEntry(
            provider_id=self.provider_id,
            driver_number=str(number),
            driver=driver,
            position=to_int(line.get("Position")),
            show_position=bool(line.get("ShowPosition", True)),
            best_lap_time=best_lap,
            best_lap_number=best_lap_lap,
            best_lap_overall_fastest=overall_fastest,
            last_lap_time=last_lap,
            sectors=sectors,
            gap_to_leader=gap,
            interval_to_ahead=interval,
            time_diff_to_fastest=time_diff_fastest,
            time_diff_to_position_ahead=time_diff_ahead,
            time_diff_to_fastest_segment=fastest_segment,
            time_diff_to_position_ahead_segment=ahead_segment,
            number_of_laps=to_int(line.get("NumberOfLaps")),
            number_of_pit_stops=to_int(line.get("NumberOfPitStops")),
            in_pit=bool(line.get("InPit")),
            pit_out=bool(line.get("PitOut")),
            stopped=bool(line.get("Stopped")),
            retired=bool(line.get("Retired")),
            status_code=to_int(line.get("Status")),
            tyre_compound=compound,
            tyre_age=tyre_age,
            tyre_new=tyre_new,
            grid_position=grid_pos,
            best_lap_times=best_lap_times,
            speeds=speeds,
            source_timestamp=self._last_message_at,
        )

    @staticmethod
    def _stats_entries(raw: Any) -> list[tuple[str, dict[str, Any]]]:
        """Normaliza ``Stats`` a una lista de ``(indice, datos)``.

        El feed de cronometraje entrega ``Stats`` de dos formas indistintas:

        * como mapa indexado por segmento: ``{"0": {...}, "1": {...}}``
        * como lista de tres elementos: ``[Q1, Q2, Q3]``

        Las dos se normalizan aqui a la misma estructura ``(indice, datos)``,
        ordenada de menor a mayor, con el indice **crudo** del feed ("0", "1",
        "2"). El indice no se traduce a "Q1"/"Q2"/"Q3" en el backend a
        proposito: en carrera el indice "0" es la vuelta actual, no el
        segmento Q1, y etiquetarlo seria inventar. Quien sabe si la sesion es
        una clasificacion es el frontend, que ya distingue ambos casos.
        """
        entries: list[tuple[str, dict[str, Any]]] = []
        if isinstance(raw, dict):
            items = sorted(raw.items(), key=lambda kv: _sort_key(kv[0]))
            for key, value in items:
                if isinstance(value, dict):
                    entries.append((str(key), value))
        elif isinstance(raw, list):
            for index, value in enumerate(raw):
                if isinstance(value, dict):
                    entries.append((str(index), value))
        return entries

    @staticmethod
    def _value_of(raw: Any) -> str | None:
        """Extrae el texto de un campo que puede ser string u objeto."""
        if raw is None:
            return None
        if isinstance(raw, dict):
            value = raw.get("Value")
            return str(value) if value not in (None, "") else None
        text = str(raw).strip()
        return text or None

    @staticmethod
    def _clean_gap(raw: Any) -> str | None:
        """Normaliza un gap. Vacio significa "no hay dato", no un gap de 0."""
        if raw is None:
            return None
        text = str(raw).strip()
        if text in ("", "+0.000", "0.000", "-"):
            return None if text in ("", "-") else text
        return text

    def _normalise_sectors(self, raw: Any) -> list[Sector]:
        """Normaliza sectores. El feed los entrega como lista o como mapa."""
        sectors: list[Sector] = []
        if isinstance(raw, list):
            items = list(enumerate(raw))
        elif isinstance(raw, dict):
            items = sorted(raw.items(), key=lambda kv: _sort_key(kv[0]))
        else:
            return sectors

        for key, value in items:
            if not isinstance(value, dict):
                continue
            index = key if isinstance(key, int) else to_int(key)
            if index is None:
                continue
            sectors.append(
                Sector(
                    index=index,
                    time=parse_lap_time(value.get("Value")),
                    personal_fastest=bool(value.get("PersonalFastest")),
                    overall_fastest=bool(value.get("OverallFastest")),
                    stopped=bool(value.get("Stopped")),
                    valid=not bool(value.get("Stopped")),
                )
            )
        return sectors

    @staticmethod
    def _best_lap_times_items(raw: Any) -> list[tuple[int, Any]]:
        """Los `BestLapTimes` del feed, con el indice de su segmento.

        El feed los entrega de dos formas y hay que soportarlas las dos:

        * como **lista** (``[{...}, {...}, {...}]``), que es lo que llega por
          ``/api/standings`` y ``/api/leaderboard``: la posicion es el indice.
        * como **mapa** con clave ``"0"``/``"1"``/``"2"``, que es lo que usan
          algunos payloads.

        Con el mapa hay que respetar la clave: si falta un segmento, los que
        quedan **no** se corren de lugar (si no, el Q3 pasaria a leerse como
        Q2).
        """
        items: list[tuple[int, Any]] = []
        if isinstance(raw, dict):
            for key, value in raw.items():
                try:
                    indice = int(str(key))
                except (TypeError, ValueError):
                    continue
                items.append((indice, value))
            items.sort(key=lambda item: item[0])
            return items
        if isinstance(raw, list):
            return list(enumerate(raw))
        return []

    @staticmethod
    def _normalise_best_lap_times(raw: Any) -> dict[str, float | None]:
        """Separa las mejores vueltas por segmento de clasificacion.

        El feed de clasificacion entrega ``BestLapTimes`` con las claves
        ``"0"``/``"1"``/``"2"`` que corresponden a Q1/Q2/Q3.
        """
        result: dict[str, float | None] = {}
        for indice, value in FreeLiveTimingProvider._best_lap_times_items(raw):
            segment = _SEGMENT_BY_KEY.get(str(indice))
            if segment is None:
                continue
            if isinstance(value, dict):
                result[segment] = parse_lap_time(value.get("Value"))
            else:
                result[segment] = parse_lap_time(value)
        return result

    @staticmethod
    def _best_lap_number(raw: Any, segment: str) -> int | None:
        """Numero de vuelta del mejor tiempo de un segmento."""
        indice = next((k for k, v in _SEGMENT_BY_KEY.items() if v == segment), None)
        if indice is None:
            return None
        for posicion, value in FreeLiveTimingProvider._best_lap_times_items(raw):
            if posicion != int(indice):
                continue
            if not isinstance(value, dict):
                return None
            return to_int(value.get("Lap"))
        return None

    @staticmethod
    def _stint_list(stints: Any) -> list[dict[str, Any]]:
        """Normaliza los stints del feed a una lista ordenada.

        En el feed en vivo ``Stints`` es un **diccionario** con clave por
        stint (``{"0": {...}, "1": {...}}``), no una lista. Tratarlo como
        lista hacia que el recorrido por sus claves descartara todos los
        stints: por eso la columna de neumático salia vacia en vivo.
        """
        if isinstance(stints, dict):
            claves: list[tuple[int, Any]] = []
            for clave in stints.keys():
                try:
                    claves.append((int(clave), clave))
                except (TypeError, ValueError):
                    claves.append((0, clave))
            claves.sort(key=lambda item: item[0])
            return [
                stints[clave]
                for _, clave in claves
                if isinstance(stints[clave], dict)
            ]
        if isinstance(stints, list):
            return [stint for stint in stints if isinstance(stint, dict)]
        return []

    @staticmethod
    def _tyre_from_app(
        app_line: dict[str, Any],
        timing_line: dict[str, Any],
    ) -> tuple[str | None, int | None, bool | None, int | None]:
        """Extrae el pneumatico vigente del stint actual."""
        compound: str | None = None
        tyre_age: int | None = None
        tyre_new: bool | None = None

        stints = FreeLiveTimingProvider._stint_list(
            app_line.get("Stints") or timing_line.get("Stints")
        )
        if stints:
            current = stints[-1]
            compound = current.get("Compound")
            tyre_age = to_int(current.get("TotalLaps"))
            new_raw = current.get("New")
            tyre_new = _to_bool(new_raw)

        grid_pos = to_int(app_line.get("GridPos"))
        return compound, tyre_age, tyre_new, grid_pos

    async def get_tyres(self) -> list[Stint]:
        payload = await self._get_json("/api/tyres")
        lines = payload.get("Lines") or {}
        stints: list[Stint] = []
        for number, line in lines.items():
            if number in _PLACEHOLDER_KEYS or not isinstance(line, dict):
                continue
            for indice, stint in enumerate(self._stint_list(line.get("Stints"))):
                stints.append(
                    Stint(
                        provider_id=self.provider_id,
                        driver_number=str(number),
                        stint_number=indice,
                        compound=stint.get("Compound"),
                        lap_start=to_int(stint.get("StartLaps")),
                        lap_end=None,
                        tyre_age_at_start=to_int(stint.get("StartLaps")),
                        total_laps=to_int(stint.get("TotalLaps")),
                        is_new=_to_bool(stint.get("New")),
                        source_timestamp=self._last_message_at,
                    )
                )
        return stints

    async def get_stints(self) -> list[Stint]:
        return await self.get_tyres()

    async def get_laps(self) -> list[Lap]:
        """El feed live no expone el historico de vueltas por piloto.

        Se marca como no soportado en vez de devolver una lista vacia que
        pareceria "no hay vueltas".
        """
        raise self._unsupported("laps")

    async def get_weather(self) -> WeatherReport | None:
        payload = await self._get_json("/api/weather")
        weather = payload.get("Weather") or {}
        if not weather:
            return None
        return WeatherReport(
            provider_id=self.provider_id,
            air_temperature=to_float(weather.get("AirTemp")),
            track_temperature=to_float(weather.get("TrackTemp")),
            humidity=to_float(weather.get("Humidity")),
            pressure=to_float(weather.get("Pressure")),
            rainfall=to_float(weather.get("Rainfall")),
            wind_speed=to_float(weather.get("WindSpeed")),
            wind_direction=to_float(weather.get("WindDirection")),
            source_timestamp=self._last_message_at,
        )

    async def get_race_control(self) -> list[RaceControlEvent]:
        payload = await self._get_json("/api/race-control")
        events: list[RaceControlEvent] = []
        for item in payload.get("RaceControl") or []:
            if not isinstance(item, dict):
                continue
            message = item.get("Message")
            if not message:
                continue
            events.append(
                RaceControlEvent(
                    provider_id=self.provider_id,
                    message=str(message),
                    category=item.get("Category"),
                    flag=item.get("Flag"),
                    scope=item.get("Scope"),
                    utc=parse_timestamp(item.get("Utc")),
                    source_timestamp=self._last_message_at,
                )
            )
        events.sort(key=lambda event: (event.utc is None, event.utc))
        return events

    async def get_telemetry(self) -> list[TelemetrySample]:
        """Telemetria en vivo por auto (velocidad, RPM, marcha, DRS...).

        Viene del canal ``CarData`` del feed de cronometraje. El servicio Node
        local lo expone en ``/api/car-data``.
        """
        cars = await self._cars()
        samples: list[TelemetrySample] = []
        for car in cars:
            number = str(car.get("RacingNumber") or "")
            if not number:
                continue
            samples.append(
                TelemetrySample(
                    provider_id=self.provider_id,
                    driver_number=number,
                    timestamp=self._last_message_at,
                    speed=to_float(car.get("Speed")),
                    rpm=to_float(car.get("Rpm")),
                    gear=to_int(car.get("Gear")),
                    throttle=to_float(car.get("Throttle")),
                    brake=to_float(car.get("Brake")),
                    drs=to_int(car.get("Drs")),
                    x=to_float(car.get("X")),
                    y=to_float(car.get("Y")),
                    source_timestamp=self._last_message_at,
                )
            )
        return samples

    async def _cars(self) -> list[dict[str, Any]]:
        """Estado mas reciente de cada auto (posicion + telemetria).

        Son **dos canales distintos** del feed: las coordenadas X/Y/Z llegan
        por `Positions` y la telemetria (velocidad, rpm, marcha) por
        `CarData`. Se unen por numero de auto para poder dibujar el mapa y
        mostrar la telemetria a la vez.
        """
        telemetry: dict[str, dict[str, Any]] = {}
        try:
            payload = await self._get_json("/api/car-data")
            for car in payload.get("Cars") or []:
                if not isinstance(car, dict):
                    continue
                numero = str(car.get("RacingNumber") or "")
                if numero:
                    telemetry[numero] = car
        except Exception:
            pass

        cars: list[dict[str, Any]] = []
        try:
            payload = await self._get_json("/api/positions")
        except Exception:
            payload = {}

        for car in payload.get("Cars") or []:
            if not isinstance(car, dict):
                continue
            numero = str(car.get("RacingNumber") or "")
            if not numero:
                continue
            unido = dict(telemetry.get(numero) or {})
            unido.update(car)
            cars.append(unido)

        # Si las coordenadas no llegaron pero si la telemetria, al menos esa.
        for numero, car in telemetry.items():
            if not any(str(otro.get("RacingNumber")) == numero for otro in cars):
                cars.append(car)

        return cars

    async def get_positions(self) -> list[dict[str, Any]]:
        """Posicion de cada auto sobre el circuito, en vivo."""
        cars = await self._cars()
        positions: list[dict[str, Any]] = []
        for car in cars:
            number = str(car.get("RacingNumber") or "")
            x = to_float(car.get("X"))
            y = to_float(car.get("Y"))
            if not number or x is None or y is None:
                continue
            positions.append(
                {
                    "provider_id": self.provider_id,
                    "driver_number": number,
                    "x": x,
                    "y": y,
                    "z": to_float(car.get("Z")),
                    "speed": to_float(car.get("Speed")),
                    "gear": to_int(car.get("Gear")),
                    "status": car.get("Status"),
                    "source_timestamp": _iso(self._last_message_at),
                }
            )
        return positions

    async def get_track_status(self) -> dict[str, Any]:
        """Estado de la pista segun el canal TrackStatus del feed."""
        payload = await self._get_json("/api/track-status")
        status = payload.get("TrackStatus") or {}
        return {
            "provider_id": self.provider_id,
            "status": status.get("Status"),
            "message": status.get("Message"),
            "source_timestamp": _iso(self._last_message_at),
        }


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat()


def _sort_key(key: Any) -> tuple[int, str]:
    number = to_int(key)
    if number is None:
        return (9999, str(key))
    return (number, str(key))


def _to_bool(value: Any) -> bool | None:
    """Convierte "true"/"false"/1/0 del feed a bool, preservando el None."""
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("true", "1", "yes"):
        return True
    if text in ("false", "0", "no"):
        return False
    return None
