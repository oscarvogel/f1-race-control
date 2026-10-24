"""Acceso al sitio: login propio de la aplicacion.

El sitio desplegado sale de un repo publico, asi que la API tiene que estar
protegida. Antes se usaba HTTP basic de nginx y el problema era visible: el
navegador muestra su propio dialogo, ajeno al tema de la app, sin estilo y
sin forma de cerrar sesion.

Ahora el login es de la aplicacion: un formulario en espanol, con el tema
oscuro, y la proteccion real sigue estando en el borde (nginx), que le
pregunta a Django con ``auth_request``. Asi el codigo de la API y los datos no
quedan expuestos, pero la pantalla de acceso es parte de la app.

Como funciona:

* La credencial no se guarda en ninguna base: se compara, en tiempo constante,
  con la de las variables de entorno ``RACE_CENTER_USER`` y
  ``RACE_CENTER_PASSWORD``.
* La sesion es una cookie firmada con el ``SECRET_KEY`` de Django y con
  vencimiento. No hay tabla de usuarios.
* Si no hay credenciales configuradas (desarrollo local), no se pide nada y
  la API queda abierta, igual que antes.
* La respuesta 401 **no** lleva ``WWW-Authenticate``: por eso el navegador no
  abre su dialogo nativo y el frontend puede mostrar su propia pantalla de
  acceso.
"""

from __future__ import annotations

import json
import logging
import secrets
import time
from collections import defaultdict
from typing import Any

from django.conf import settings
from django.core import signing
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_GET, require_POST

logger = logging.getLogger("racecenter.auth")

COOKIE_NAME = "race_center_session"
SALT = "race-center-login"

# Freno de fuerza bruta: pocos intentos fallidos por IP en una ventana corta.
MAX_ATTEMPTS = 8
ATTEMPT_WINDOW_SECONDS = 300.0

# Intentos fallidos por IP: {ip: [momento, ...]}
_ATTEMPTS: dict[str, list[float]] = defaultdict(list)


def _json(payload: Any, status: int = 200) -> JsonResponse:
    return JsonResponse(payload, status=status, json_dumps_params={"ensure_ascii": False})


def auth_required() -> bool:
    """¿El sitio pide usuario y contrasena?"""
    return bool(settings.RACE_CENTER_USER and settings.RACE_CENTER_PASSWORD)


def _client_ip(request) -> str:
    """IP real del cliente, detras del proxy de nginx o de Coolify."""
    forwarded = request.META.get("HTTP_X_FORWARDED_FOR", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "") or ""


def _attempts_exceeded(ip: str) -> bool:
    now = time.monotonic()
    recent = [mark for mark in _ATTEMPTS.get(ip, []) if now - mark < ATTEMPT_WINDOW_SECONDS]
    _ATTEMPTS[ip] = recent
    return len(recent) >= MAX_ATTEMPTS


def _register_failure(ip: str) -> None:
    _ATTEMPTS[ip].append(time.monotonic())


def _clear_failures(ip: str) -> None:
    _ATTEMPTS.pop(ip, None)


def _issue_token(username: str) -> str:
    return signing.TimestampSigner(salt=SALT).sign(username)


def _read_token(request) -> str | None:
    """Usuario de la cookie de sesion, si la cookie es valida y no vencio."""
    token = request.COOKIES.get(COOKIE_NAME)
    if not token:
        return None
    try:
        username = signing.TimestampSigner(salt=SALT).unsign(
            token, max_age=settings.RACE_CENTER_SESSION_SECONDS
        )
    except signing.BadSignature:
        return None
    return username


@require_POST
@csrf_exempt
def login(request):
    """Inicio de sesion: recibe usuario y contrasena, devuelve la cookie.

    El cuerpo es JSON: ``{"username": "...", "password": "..."}``.
    """
    if not auth_required():
        return _json({"ok": True, "authenticated": True, "required": False})

    ip = _client_ip(request)
    if _attempts_exceeded(ip):
        return _json(
            {
                "ok": False,
                "error": "Demasiados intentos fallidos. Espera unos minutos e intenta de nuevo.",
            },
            status=429,
        )

    try:
        payload = json.loads(request.body or b"{}")
    except (ValueError, TypeError):
        payload = {}
    if not isinstance(payload, dict):
        payload = {}

    usuario = str(payload.get("username") or "")
    clave = str(payload.get("password") or "")

    # Comparacion en tiempo constante: no filtrar cuanto se tarda.
    coincide = secrets.compare_digest(usuario, settings.RACE_CENTER_USER) and secrets.compare_digest(
        clave, settings.RACE_CENTER_PASSWORD
    )

    if not coincide:
        _register_failure(ip)
        logger.warning("Intento de acceso fallido desde %s", ip)
        return _json({"ok": False, "error": "Usuario o contrasena incorrectos."}, status=401)

    _clear_failures(ip)
    response = _json({"ok": True, "authenticated": True, "username": usuario})
    response.set_cookie(
        COOKIE_NAME,
        _issue_token(usuario),
        httponly=True,
        samesite="Lax",
        # "Secure" solo si la peticion llego por HTTPS: si se pone siempre y
        # alguien entra por HTTP, el navegador no manda la cookie y el login
        # parece funcionar pero la API responde 401.
        secure=request.is_secure(),
        max_age=settings.RACE_CENTER_SESSION_SECONDS,
        path="/",
    )
    logger.info("Acceso concedido a %s desde %s", usuario, ip)
    return response


@require_POST
def logout(request):
    """Cierra la sesion: borra la cookie."""
    response = _json({"ok": True, "authenticated": False})
    response.delete_cookie(COOKIE_NAME, path="/")
    return response


@require_GET
def session(request):
    """Estado de la sesion, para que el frontend sepa si mostrar el login."""
    if not auth_required():
        return _json({"required": False, "authenticated": True, "username": None})

    usuario = _read_token(request)
    return _json(
        {
            "required": True,
            "authenticated": usuario is not None,
            "username": usuario,
        }
    )


@require_GET
def check(request):
    """Comprobacion de sesion para el ``auth_request`` de nginx.

    Responde 200 si la sesion es valida y 401 si no. El 401 va **sin**
    ``WWW-Authenticate``: si lo llevara, el navegador abriria su dialogo
    nativo y se pierde la pantalla de acceso de la aplicacion.
    """
    if not auth_required():
        return HttpResponse(status=200)
    if _read_token(request) is not None:
        return HttpResponse(status=200)
    return HttpResponse(status=401)


# --------------------------------------------------------------------------- #
# Defensa en profundidad
# --------------------------------------------------------------------------- #


# Rutas que se pueden consultar sin sesion:
#  - /api/ping/       : health check del orquestador.
#  - /api/auth/*      : el login no puede depender de la sesion.
#
# Todo lo demas (incluido /api/health/) exige sesion: el diagnostico se ve
# desde la app, que ya esta autenticada.
RUTAS_LIBRES = frozenset(
    {
        "/api/ping/",
        "/api/auth/login/",
        "/api/auth/logout/",
        "/api/auth/session/",
        "/api/auth/check/",
    }
)


class SessionAuthMiddleware:
    """Exige sesion valida para la API.

    La proteccion principal esta en el borde (nginx, con ``auth_request``),
    pero el backend no deberia confiar en que ese filtro este bien puesto:
    si la API quedara expuesta por un error de configuracion, esta capa sigue
    cerrando la puerta. En desarrollo (sin credenciales) no molesta.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not auth_required():
            return self.get_response(request)
        if request.path in RUTAS_LIBRES:
            return self.get_response(request)
        if _read_token(request) is None:
            return JsonResponse(
                {"ok": False, "error": "Sesion no iniciada o vencida."},
                status=401,
                json_dumps_params={"ensure_ascii": False},
            )
        return self.get_response(request)
