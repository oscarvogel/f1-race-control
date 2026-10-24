"""Modelos de persistencia de Race Center.

Reglas de almacenamiento:

* Un snapshot solo se persiste si su **contenido** cambio (huella SHA-256 del
  payload normalizado). Asi no se llenan la base de filas identicas.
* ``ProviderStatus`` y ``IngestionRun`` son historicos: permiten auditar
  cuando hubo cortes, que error y cuanto tardo cada llamada.
* La deduplicacion de eventos de control de carrera es por
  ``(provider_id, session, utc, message)``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from django.db import models


def payload_fingerprint(payload: Any) -> str:
    """Huella estable del **contenido significativo** de un snapshot.

    Se excluyen los campos que cambian en cada ciclo aunque los datos no
    cambien (``generated_at`` y el bloque de diagnóstico con latencias y
    estados). Sin esa exclusión, la huella sería distinta en cada poll y se
    escribiría una fila nueva cada 3 segundos, que es exactamente lo que la
    especificación pide evitar.
    """
    if isinstance(payload, dict):
        relevant = {
            key: payload.get(key)
            for key in (
                "session",
                "timing",
                "drivers",
                "weather",
                "race_control",
                "tyres",
                "sources",
                "data_state",
            )
            if key in payload
        }
    else:
        relevant = payload
    blob = json.dumps(relevant, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class Season(models.Model):
    year = models.PositiveIntegerField(unique=True)
    name = models.CharField(max_length=120, blank=True)

    class Meta:
        ordering = ["-year"]

    def __str__(self) -> str:
        return str(self.year)


class Meeting(models.Model):
    provider_id = models.CharField(max_length=64, db_index=True)
    provider_meeting_key = models.CharField(max_length=64, db_index=True)
    season = models.ForeignKey(Season, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=200)
    official_name = models.CharField(max_length=255, blank=True)
    circuit_name = models.CharField(max_length=160, blank=True)
    location = models.CharField(max_length=120, blank=True)
    country_name = models.CharField(max_length=120, blank=True)
    country_code = models.CharField(max_length=8, blank=True)
    round_number = models.IntegerField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider_id", "provider_meeting_key"],
                name="uniq_meeting_provider_key",
            )
        ]
        ordering = ["-start_date", "-round_number"]

    def __str__(self) -> str:
        return "%s %s" % (self.season_id or "", self.name)


class Session(models.Model):
    provider_id = models.CharField(max_length=64, db_index=True)
    provider_session_id = models.CharField(max_length=64, db_index=True)
    meeting = models.ForeignKey(Meeting, on_delete=models.CASCADE, null=True, blank=True)
    name = models.CharField(max_length=160, blank=True)
    session_type = models.CharField(max_length=60, blank=True)
    session_number = models.IntegerField(null=True, blank=True)
    start_time_utc = models.DateTimeField(null=True, blank=True)
    end_time_utc = models.DateTimeField(null=True, blank=True)
    state = models.CharField(max_length=60, blank=True)
    qualifying_segment = models.CharField(max_length=16, blank=True)
    source_timestamp = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider_id", "provider_session_id"],
                name="uniq_session_provider_key",
            )
        ]
        ordering = ["-start_time_utc"]

    def __str__(self) -> str:
        return "%s (%s %s)" % (self.name, self.provider_id, self.provider_session_id)


class Team(models.Model):
    name = models.CharField(max_length=160)
    colour = models.CharField(max_length=16, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["name", "colour"], name="uniq_team_name_colour"),
        ]

    def __str__(self) -> str:
        return self.name


class Driver(models.Model):
    number = models.CharField(max_length=8, db_index=True)
    code = models.CharField(max_length=8, blank=True)
    full_name = models.CharField(max_length=160)
    first_name = models.CharField(max_length=80, blank=True)
    last_name = models.CharField(max_length=80, blank=True)
    team = models.ForeignKey(Team, on_delete=models.SET_NULL, null=True, blank=True)
    country_code = models.CharField(max_length=8, blank=True)
    headshot_url = models.URLField(blank=True)
    season = models.ForeignKey(Season, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["number", "season"], name="uniq_driver_number_season"
            )
        ]
        ordering = ["number"]

    def __str__(self) -> str:
        return "%s %s" % (self.number, self.full_name)


class SessionEntry(models.Model):
    """Ultimo estado conocido de un piloto en una sesion."""

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="entries")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, null=True, blank=True)
    provider_id = models.CharField(max_length=64)
    position = models.IntegerField(null=True, blank=True)
    best_lap_time = models.FloatField(null=True, blank=True)
    best_lap_number = models.IntegerField(null=True, blank=True)
    last_lap_time = models.FloatField(null=True, blank=True)
    sector_1 = models.FloatField(null=True, blank=True)
    sector_2 = models.FloatField(null=True, blank=True)
    sector_3 = models.FloatField(null=True, blank=True)
    gap_to_leader = models.CharField(max_length=32, blank=True)
    interval_to_ahead = models.CharField(max_length=32, blank=True)
    number_of_laps = models.IntegerField(null=True, blank=True)
    number_of_pit_stops = models.IntegerField(null=True, blank=True)
    in_pit = models.BooleanField(default=False)
    retired = models.BooleanField(default=False)
    tyre_compound = models.CharField(max_length=24, blank=True)
    tyre_age = models.IntegerField(null=True, blank=True)
    q1_time = models.FloatField(null=True, blank=True)
    q2_time = models.FloatField(null=True, blank=True)
    q3_time = models.FloatField(null=True, blank=True)
    source_timestamp = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "driver"], name="uniq_entry_session_driver"
            )
        ]
        ordering = ["position"]

    def __str__(self) -> str:
        return "%s P%s" % (self.driver_id, self.position)


class Lap(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="laps")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, null=True, blank=True)
    provider_id = models.CharField(max_length=64)
    lap_number = models.IntegerField(null=True, blank=True)
    lap_duration = models.FloatField(null=True, blank=True)
    sector_1 = models.FloatField(null=True, blank=True)
    sector_2 = models.FloatField(null=True, blank=True)
    sector_3 = models.FloatField(null=True, blank=True)
    compound = models.CharField(max_length=24, blank=True)
    tyre_age_at_start = models.IntegerField(null=True, blank=True)
    is_pit_out_lap = models.BooleanField(null=True, blank=True)
    stint_number = models.IntegerField(null=True, blank=True)
    position = models.IntegerField(null=True, blank=True)
    deleted = models.BooleanField(null=True, blank=True)
    date = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "driver", "lap_number", "provider_id"],
                name="uniq_lap_session_driver_number",
            )
        ]
        ordering = ["lap_number"]


class Stint(models.Model):
    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="stints")
    driver = models.ForeignKey(Driver, on_delete=models.CASCADE, null=True, blank=True)
    provider_id = models.CharField(max_length=64)
    stint_number = models.IntegerField(null=True, blank=True)
    compound = models.CharField(max_length=24, blank=True)
    lap_start = models.IntegerField(null=True, blank=True)
    lap_end = models.IntegerField(null=True, blank=True)
    tyre_age_at_start = models.IntegerField(null=True, blank=True)
    is_new = models.BooleanField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "driver", "stint_number", "provider_id"],
                name="uniq_stint_session_driver_number",
            )
        ]
        ordering = ["stint_number"]


class RaceControlEvent(models.Model):
    provider_id = models.CharField(max_length=64)
    session = models.ForeignKey(Session, on_delete=models.CASCADE, null=True, blank=True)
    message = models.TextField()
    category = models.CharField(max_length=60, blank=True)
    flag = models.CharField(max_length=40, blank=True)
    scope = models.CharField(max_length=40, blank=True)
    utc = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["provider_id", "session", "utc", "message"],
                name="uniq_race_control_event",
            )
        ]
        ordering = ["-utc"]


class ProviderStatus(models.Model):
    provider_id = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=160)
    endpoint = models.CharField(max_length=255, blank=True)
    state = models.CharField(max_length=32)
    is_connected = models.BooleanField(default=False)
    last_message_at = models.DateTimeField(null=True, blank=True)
    data_age_seconds = models.FloatField(null=True, blank=True)
    latency_ms = models.FloatField(null=True, blank=True)
    last_error = models.TextField(blank=True)
    error_count = models.IntegerField(default=0)
    reconnect_count = models.IntegerField(default=0)
    capabilities = models.JSONField(default=dict, blank=True)
    recorded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-recorded_at"]


class IngestionRun(models.Model):
    """Bitacora de cada ciclo de ingesta."""

    provider_id = models.CharField(max_length=64)
    session_id = models.CharField(max_length=64, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    ok = models.BooleanField(default=True)
    duration_ms = models.FloatField(null=True, blank=True)
    entries_count = models.IntegerField(default=0)
    changed = models.BooleanField(default=False)
    data_state = models.CharField(max_length=16, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]


class SessionSnapshot(models.Model):
    """Snapshot completo del estado de una sesion.

    Solo se crea una fila nueva cuando el contenido cambio (huella).

    ``scope`` distingue el snapshot **en vivo** del **historico**. Sin ese
    campo, cargar una sesion historica desde el selector insertaba su fila
    como la mas reciente y el dashboard en vivo pasaba a servir datos
    historicos: el "ultimo snapshot" tiene que saber que ambito busca.
    """

    session = models.ForeignKey(Session, on_delete=models.CASCADE, related_name="snapshots")
    provider_id = models.CharField(max_length=64)
    scope = models.CharField(max_length=16, default="live")
    data_state = models.CharField(max_length=16)
    fingerprint = models.CharField(max_length=64)
    source_timestamp = models.DateTimeField(null=True, blank=True)
    payload = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["session", "fingerprint"], name="uniq_snapshot_fingerprint"
            )
        ]
        indexes = [
            models.Index(fields=["scope", "-created_at"], name="idx_snapshot_scope_created"),
        ]
        ordering = ["-created_at"]
