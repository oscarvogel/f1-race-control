"""URLs raiz de Race Center."""

from django.urls import include, path

urlpatterns = [
    path("api/", include("core.urls")),
]
