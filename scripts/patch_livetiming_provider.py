"""Race Center: parche minimo y documentado sobre f1-livetiming-api.

Correcciones de seguridad autorizadas por la especificacion (seccion 15):
"Si el proveedor Node abre 0.0.0.0 por defecto, corregir la configuracion
local o aplicar una restriccion equivalente" y "Sin CORS abierto
indiscriminadamente".

Ampliacion funcional (peticion explicita del usuario: vista del circuito con
la posicion de cada piloto en vivo): el upstream no se suscribe al canal
`CarData` de SignalR, que es el que trae las coordenadas X/Y/Z y la
telemetria por auto. El parche:
  1. anade 'CarData' a la lista de canales,
  2. guarda ese canal en memoria con el mismo deep-merge del resto,
  3. expone una lectura de solo lectura en /api/car-data.

No se altera la logica de cronometraje existente. Se preserva el CRLF/LF
original del archivo.
"""
import io
import os
import shutil
import sys

DEFAULT_ROOT = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "services",
    "live-timing",
    "src",
)
TARGETS = ["server.js", "f1-client.js"]
MARKER = "Race Center patch"
MARKER_ADD = "Race Center addition"


def read(path):
    with io.open(path, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def write(path, src):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        fh.write(src)


def nl_of(src):
    return "\r\n" if "\r\n" in src else "\n"


def replace_once(src, old, new, label):
    """Reemplaza una vez, adaptando el estilo de fin de linea del archivo.

    Los patrones se escriben con '\\n'; si el archivo usa CRLF se convierten
    antes de buscar, asi el parche funciona igual en los dos casos.
    """
    nl = nl_of(src)
    if nl == "\r\n":
        old = old.replace("\r\n", "\n").replace("\n", "\r\n")
        new = new.replace("\r\n", "\n").replace("\n", "\r\n")
    if src.count(old) != 1:
        print("FALLO (%s): encontrado %d veces -> %r" % (label, src.count(old), old[:70]))
        sys.exit(1)
    return src.replace(old, new)


def patch_server(path):
    src = read(path)
    if MARKER in src:
        print("server.js ya parcheado (seguridad).")
    else:
        NL = nl_of(src)
        src = replace_once(
            src,
            "const PORT = process.env.PORT || 3000;",
            NL.join([
                "const PORT = process.env.PORT || 3000;",
                "// [Race Center patch] Upstream calls app.listen(PORT) with no host, which binds 0.0.0.0.",
                "// We bind loopback by default so the live-timing service is NOT reachable from the LAN.",
                "// Set HOST=0.0.0.0 to restore the upstream behaviour.",
                "const HOST = process.env.HOST || '127.0.0.1';",
            ]),
            "server:PORT",
        )
        src = replace_once(
            src,
            "app.use(cors());",
            NL.join([
                "// [Race Center patch] Restrict CORS to loopback origins instead of cors() (allows any origin).",
                "// Requests without an Origin header (server-to-server, i.e. the Django backend) are allowed.",
                "const CORS_ORIGINS = (",
                "    process.env.CORS_ORIGINS ||",
                "    'http://127.0.0.1:5174,http://localhost:5174,http://127.0.0.1:8000,http://localhost:8000'",
                ")",
                "    .split(',')",
                "    .map((origin) => origin.trim())",
                "    .filter(Boolean);",
                "app.use(",
                "    cors({",
                "        origin: (origin, callback) => {",
                "            if (!origin) return callback(null, true);",
                "            if (CORS_ORIGINS.includes(origin)) return callback(null, true);",
                "            return callback(null, false);",
                "        },",
                "    })",
                ");",
            ]),
            "server:CORS",
        )
        src = replace_once(
            src,
            "const server = app.listen(PORT, () => {",
            "const server = app.listen(PORT, HOST, () => {",
            "server:listen",
        )
        src = replace_once(
            src,
            "    console.log(`  Port: http://localhost:${PORT}`);",
            NL.join([
                "    console.log(`  Bind: http://${HOST}:${PORT}`);",
                "    console.log(`  CORS origins: ${CORS_ORIGINS.join(', ')}`);",
            ]),
            "server:banner",
        )
        write(path, src)
        print("server.js parcheado (loopback + CORS).")

    # Montaje de las rutas de CarData y TrackStatus (cada una por separado).
    if "car-data" not in src:
        NL = nl_of(src)
        src = replace_once(
            src,
            "const { createSessionRouter } = require('./routes/session');",
            NL.join([
                "const { createSessionRouter } = require('./routes/session');",
                "// [Race Center addition] Routes for the CarData and TrackStatus channels.",
                "const { createCarDataRouter, createTrackStatusRouter } = require('./routes/car-data');",
            ]),
            "server:import",
        )
        src = replace_once(
            src,
            "app.use('/api', createSessionRouter(f1Client));",
            NL.join([
                "app.use('/api', createSessionRouter(f1Client));",
                "",
                "// [Race Center addition] Live car positions, telemetry and track status.",
                "app.use('/api/car-data', createCarDataRouter(f1Client));",
                "app.use('/api/track-status', createTrackStatusRouter(f1Client));",
            ]),
            "server:mount",
        )
        write(path, src)
        print("server.js parcheado (rutas /api/car-data y /api/track-status).")
    elif "track-status" not in src:
        NL = nl_of(src)
        src = replace_once(
            src,
            "const { createCarDataRouter } = require('./routes/car-data');",
            "const { createCarDataRouter, createTrackStatusRouter } = require('./routes/car-data');",
            "server:import-status",
        )
        src = replace_once(
            src,
            "app.use('/api/car-data', createCarDataRouter(f1Client));",
            NL.join([
                "app.use('/api/car-data', createCarDataRouter(f1Client));",
                "app.use('/api/track-status', createTrackStatusRouter(f1Client));",
            ]),
            "server:mount-status",
        )
        write(path, src)
        print("server.js parcheado (ruta /api/track-status).")
    else:
        print("server.js ya expone /api/car-data y /api/track-status.")


def patch_client(path):
    src = read(path)
    NL = nl_of(src)

    # --- CarData: canal con posiciones X/Y/Z y telemetria por auto --------- #
    if "[Race Center addition] CarData" not in src:
        src = replace_once(
            src,
            "    'TeamRadio'\n];",
            NL.join([
                "    'TeamRadio',",
                "    // [Race Center addition] CarData carries per-car X/Y/Z track coordinates and telemetry.",
                "    'CarData'",
                "];",
            ]),
            "client:channels",
        )

        src = replace_once(
            src,
            "        this.teamRadio = [];",
            NL.join([
                "        this.teamRadio = [];",
                "        // [Race Center addition] Live car positions and telemetry (X/Y/Z, speed, rpm, gear...).",
                "        this.carData = {};",
            ]),
            "client:state",
        )

        src = replace_once(
            src,
            "            case 'TeamRadio':",
            NL.join([
                "            case 'CarData':",
                "                // [Race Center addition] The Entries array is replaced wholesale by the merge",
                "                // engine, which is exactly what we want: the latest state of every car.",
                "                deepMerge(this.carData, data);",
                "                this.broadcast({ type: 'CarData', data: this.carData });",
                "                break;",
                "            case 'TeamRadio':",
            ]),
            "client:route",
        )

        src = replace_once(
            src,
            "        if (result.TeamRadio) this.routeData('TeamRadio', result.TeamRadio);",
            NL.join([
                "        if (result.TeamRadio) this.routeData('TeamRadio', result.TeamRadio);",
                "        // [Race Center addition] Initial snapshot may already contain car positions.",
                "        if (result.CarData) this.routeData('CarData', result.CarData);",
            ]),
            "client:snapshot",
        )

        src = replace_once(
            src,
            "    getTeamRadio() {\n        return this.teamRadio;\n    }",
            NL.join([
                "    getTeamRadio() {",
                "        return this.teamRadio;",
                "    }",
                "",
                "    /**",
                "     * [Race Center addition] Latest known state of every car (positions + telemetry).",
                "     * @returns {Object} The in-memory CarData channel state.",
                "     */",
                "    getCarData() {",
                "        return this.carData;",
                "    }",
            ]),
            "client:getter",
        )
        write(path, src)
        print("f1-client.js parcheado (suscripcion al canal CarData).")
    else:
        print("f1-client.js ya suscribe al canal CarData.")

    # --- TrackStatus: banderas de pista y safety car ----------------------- #
    if "[Race Center addition] TrackStatus" not in src:
        src = read(path)
        NL = nl_of(src)

        src = replace_once(
            src,
            "    'CarData'\n];",
            NL.join([
                "    'CarData',",
                "    // [Race Center addition] TrackStatus carries the track flags and safety car state.",
                "    'TrackStatus'",
                "];",
            ]),
            "client:channels-status",
        )

        src = replace_once(
            src,
            "        this.carData = {};",
            NL.join([
                "        this.carData = {};",
                "        // [Race Center addition] Track flags and safety car state.",
                "        this.trackStatus = {};",
            ]),
            "client:state-status",
        )

        src = replace_once(
            src,
            "            case 'TeamRadio':",
            NL.join([
                "            case 'TrackStatus':",
                "                // [Race Center addition] Track flags and safety car state.",
                "                deepMerge(this.trackStatus, data);",
                "                this.broadcast({ type: 'TrackStatus', data: this.trackStatus });",
                "                break;",
                "            case 'TeamRadio':",
            ]),
            "client:route-status",
        )

        src = replace_once(
            src,
            "        if (result.CarData) this.routeData('CarData', result.CarData);",
            NL.join([
                "        if (result.CarData) this.routeData('CarData', result.CarData);",
                "        // [Race Center addition] Track status may arrive in the initial snapshot.",
                "        if (result.TrackStatus) this.routeData('TrackStatus', result.TrackStatus);",
            ]),
            "client:snapshot-status",
        )

        src = replace_once(
            src,
            "    getCarData() {\n        return this.carData;\n    }",
            NL.join([
                "    getCarData() {",
                "        return this.carData;",
                "    }",
                "",
                "    /**",
                "     * [Race Center addition] Track flags and safety car state.",
                "     * @returns {Object} The in-memory TrackStatus channel state.",
                "     */",
                "    getTrackStatus() {",
                "        return this.trackStatus;",
                "    }",
            ]),
            "client:getter-status",
        )
        write(path, src)
        print("f1-client.js parcheado (suscripcion al canal TrackStatus).")
    else:
        print("f1-client.js ya suscribe al canal TrackStatus.")


def main():
    root = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_ROOT
    if not os.path.isdir(root):
        print("No existe el directorio del proveedor: %s" % root)
        sys.exit(1)

    # Copia de seguridad una sola vez, para poder revertir.
    backup = os.path.join(os.path.dirname(root), ".race-center-backup")
    if not os.path.isdir(backup):
        os.makedirs(backup)
        for name in TARGETS:
            source = os.path.join(root, name)
            if os.path.exists(source):
                shutil.copy2(source, os.path.join(backup, name))
        print("Copia de seguridad creada en %s" % backup)

    patch_server(os.path.join(root, "server.js"))
    patch_client(os.path.join(root, "f1-client.js"))
    print("OK: proveedor actualizado.")


if __name__ == "__main__":
    main()
