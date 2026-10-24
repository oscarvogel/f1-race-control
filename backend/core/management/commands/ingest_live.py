"""Comando de gestion: el proceso unico de ingesta.

Uso:

    python manage.py ingest_live              # bucle infinito
    python manage.py ingest_live --once       # un solo ciclo (util para tests)
    python manage.py ingest_live --interval 2 # cada 2 segundos
"""

from __future__ import annotations

import asyncio
import signal
import time

from django.core.management.base import BaseCommand

from core.ingest import Ingestor


class Command(BaseCommand):
    help = "Proceso unico de obtencion de datos de los proveedores."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true", help="Ejecuta un solo ciclo y sale.")
        parser.add_argument(
            "--interval",
            type=float,
            default=None,
            help="Segundos entre ciclos (por defecto INGEST_POLL_SECONDS).",
        )
        parser.add_argument(
            "--scope",
            default="live",
            choices=["live", "historical", "metadata"],
            help="Ambito semantico de los datos a obtener.",
        )

    def handle(self, *args, **options):
        from django.conf import settings

        interval = options["interval"] or settings.INGEST_POLL_SECONDS
        once = options["once"]
        scope = options["scope"]

        self.stdout.write(
            self.style.SUCCESS(
                "Race Center - ingesta %s (intervalo %.1fs)" % (scope, interval)
            )
        )

        if once:
            asyncio.run(self._single_cycle(scope))
            return

        asyncio.run(self._loop(scope, interval))

    async def _single_cycle(self, scope: str) -> None:
        ingestor = Ingestor(scope=scope)
        await ingestor.start()
        try:
            payload = await ingestor.run_once()
            if payload is None:
                self.stderr.write(self.style.ERROR("El ciclo fallo. Revisar el log."))
            else:
                self.stdout.write(
                    "Snapshot: estado=%s pilotos=%s fuente=%s"
                    % (
                        payload.get("data_state"),
                        len(payload.get("timing") or []),
                        (payload.get("sources") or {}).get("timing"),
                    )
                )
        finally:
            await ingestor.stop()

    async def _loop(self, scope: str, interval: float) -> None:
        ingestor = Ingestor(scope=scope)
        await ingestor.start()

        stop = {"flag": False}

        def _request_stop(*_args):
            stop["flag"] = True

        try:
            signal.signal(signal.SIGINT, _request_stop)
            signal.signal(signal.SIGTERM, _request_stop)
        except ValueError:  # pragma: no cover - fuera del hilo principal
            pass

        self.stdout.write(self.style.SUCCESS("Ingesta en marcha. Ctrl+C para detener."))
        try:
            while not stop["flag"]:
                started = time.perf_counter()
                payload = await ingestor.run_once()
                elapsed = time.perf_counter() - started
                if payload is not None:
                    self.stdout.write(
                        "[%s] estado=%s pilotos=%s proveedor=%s (%.2fs)"
                        % (
                            time.strftime("%H:%M:%S"),
                            payload.get("data_state"),
                            len(payload.get("timing") or []),
                            (payload.get("sources") or {}).get("timing"),
                            elapsed,
                        )
                    )
                else:
                    self.stderr.write(self.style.WARNING("Ciclo fallido; reintentando."))
                await asyncio.sleep(max(0.2, interval - elapsed))
        except asyncio.CancelledError:  # pragma: no cover
            pass
        finally:
            await ingestor.stop()
            self.stdout.write(self.style.SUCCESS("Ingesta detenida."))
