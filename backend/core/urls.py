"""Rutas de la API interna de Race Center."""

from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health, name="health"),
    path("ping/", views.ping, name="ping"),
    path("providers/", views.providers, name="providers"),
    path("providers/status/", views.providers_status, name="providers-status"),
    path("meetings/", views.meetings, name="meetings"),
    path("sessions/", views.sessions, name="sessions"),
    path("sessions/catalog/", views.session_catalog, name="session-catalog"),
    path(
        "sessions/historical/<str:session_key>/",
        views.historical_snapshot,
        name="historical-snapshot",
    ),
    path("sessions/current/", views.sessions_current, name="sessions-current"),
    path("weather/forecast/", views.weather_forecast, name="weather-forecast"),
    path("sessions/<int:session_id>/snapshot/", views.session_snapshot, name="session-snapshot"),
    path("sessions/<int:session_id>/timing/", views.session_timing, name="session-timing"),
    path("sessions/<int:session_id>/drivers/", views.session_drivers, name="session-drivers"),
    path("sessions/<int:session_id>/laps/", views.session_laps, name="session-laps"),
    path("sessions/<int:session_id>/weather/", views.session_weather, name="session-weather"),
    path(
        "sessions/<int:session_id>/race-control/",
        views.session_race_control,
        name="session-race-control",
    ),
    path("sessions/<int:session_id>/telemetry/", views.session_telemetry, name="session-telemetry"),
    path("sessions/<int:session_id>/entries/", views.session_entries, name="session-entries"),
    path("track/outlines/", views.track_outlines, name="track-outlines"),
    path(
        "track/outlines/<int:circuit_key>/",
        views.track_outline,
        name="track-outline",
    ),
]
