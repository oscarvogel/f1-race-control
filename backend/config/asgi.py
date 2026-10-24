"""ASGI de Race Center.

Preparado para una migracion posterior a Django Channels + Redis (WebSockets).
Por ahora el frontend consume polling contra la API REST.
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
