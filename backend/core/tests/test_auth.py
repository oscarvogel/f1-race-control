"""Pruebas del acceso al sitio (login propio de la aplicacion).

Lo importante no es solo que el login funcione: es que la API quede
protegida y que el 401 **no** lleve ``WWW-Authenticate``. Si lo llevara, el
navegador abriria su dialogo nativo de usuario y contrasena, que es
justamente lo que se cambio.
"""

from __future__ import annotations

import json

import pytest
from django.test import Client
from django.test.utils import override_settings

CREDENCIALES = {
    "RACE_CENTER_USER": "piloto",
    "RACE_CENTER_PASSWORD": "clave123",
    "RACE_CENTER_SESSION_SECONDS": 86400,
}


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def con_clave(db):
    with override_settings(**CREDENCIALES):
        yield


def _login(client: Client, usuario: str = "piloto", clave: str = "clave123"):
    return client.post(
        "/api/auth/login/",
        data=json.dumps({"username": usuario, "password": clave}),
        content_type="application/json",
    )


# --------------------------------------------------------------------------- #
# Modo desarrollo: sin credenciales no se pide nada
# --------------------------------------------------------------------------- #


def test_sin_credenciales_la_api_no_pide_nada(client):
    """En desarrollo local (sin variables de entorno) no hay login."""
    respuesta = client.get("/api/auth/session/")
    assert respuesta.status_code == 200
    assert respuesta.json()["required"] is False
    assert respuesta.json()["authenticated"] is True
    # El chequeo de nginx responde 200: la API queda abierta.
    assert client.get("/api/auth/check/").status_code == 200


# --------------------------------------------------------------------------- #
# Con credenciales: el login protege la API
# --------------------------------------------------------------------------- #


def test_sin_sesion_la_api_responde_401(client, con_clave):
    respuesta = client.get("/api/health/")
    assert respuesta.status_code == 401
    # El 401 va sin WWW-Authenticate: asi el navegador no abre su dialogo.
    assert "WWW-Authenticate" not in respuesta.headers


def test_el_login_correcto_abre_sesion(client, con_clave):
    respuesta = _login(client)
    assert respuesta.status_code == 200
    assert respuesta.json()["ok"] is True

    estado = client.get("/api/auth/session/").json()
    assert estado["required"] is True
    assert estado["authenticated"] is True
    assert estado["username"] == "piloto"

    # Y con la sesion, la API responde.
    assert client.get("/api/health/").status_code == 200
    assert client.get("/api/auth/check/").status_code == 200


def test_la_cookie_de_sesion_no_es_legible_desde_javascript(client, con_clave):
    respuesta = _login(client)
    cookie = respuesta.cookies["race_center_session"]
    assert cookie["httponly"] is True
    assert cookie["samesite"] == "Lax"


def test_una_contrasena_incorrecta_no_abre_sesion(client, con_clave):
    respuesta = _login(client, clave="malaclave")
    assert respuesta.status_code == 401
    assert respuesta.json()["ok"] is False
    assert client.get("/api/auth/session/").json()["authenticated"] is False


def test_un_usuario_inexistente_no_abre_sesion(client, con_clave):
    respuesta = _login(client, usuario="otro")
    assert respuesta.status_code == 401


def test_logout_cierra_la_sesion(client, con_clave):
    _login(client)
    assert client.get("/api/auth/check/").status_code == 200
    client.post("/api/auth/logout/")
    assert client.get("/api/auth/check/").status_code == 401


def test_despues_de_demasiados_intentos_fallidos_se_bloquea(client, con_clave):
    """Freno de fuerza bruta: no se puede adivinar la clave probando."""
    for _ in range(8):
        _login(client, clave="malaclave")
    respuesta = _login(client, clave="malaclave")
    assert respuesta.status_code == 429
    # Y con la clave correcta tampoco: esta bloqueado por ahora.
    assert _login(client).status_code == 429


def test_una_cookie_inventada_no_habilita_nada(client, con_clave):
    client.cookies["race_center_session"] = "pepino-inventado"
    assert client.get("/api/auth/check/").status_code == 401
