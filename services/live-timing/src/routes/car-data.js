/**
 * @file car-data.js
 * @description Express route exposing live car telemetry and track positions.
 *
 * [Race Center addition] The upstream service subscribes to timing channels but
 * not to `CarData`, which is the SignalR channel that carries per-car speed,
 * RPM, gear, throttle, brake, DRS and the X/Y/Z track coordinates.
 *
 * This route is a thin read-only view over that channel: it performs no
 * requests to Formula 1 servers and simply exposes the in-memory state.
 */

const express = require('express');

/**
 * Numero de dorsal de una entrada del feed.
 *
 * [Race Center addition] Segun el canal, el dorsal viene en `Number`
 * (CarData), en `CarNumber` o en `RacingNumber` (Position). Se aceptan los
 * tres: si se descarta la entrada por un nombre de campo distinto, el mapa
 * se queda vacio sin avisar.
 *
 * @param {Object} entry
 * @returns {string}
 */
function numeroDe(entry) {
    const valor = entry.Number ?? entry.CarNumber ?? entry.RacingNumber;
    return valor === undefined || valor === null ? '' : String(valor);
}

/**
 * Creates the CarData Express router.
 * @param {F1LiveClient} f1Client - Active instance of F1LiveClient.
 * @returns {express.Router} Express router instance.
 */
function createCarDataRouter(f1Client) {
    const router = express.Router();

    /**
     * GET /api/car-data
     * Returns the latest known state of every car: track coordinates and telemetry.
     */
    router.get('/', (req, res) => {
        try {
            const carData = f1Client.getCarData() || {};
            const entries = carData.Entries || [];

            const cars = (Array.isArray(entries) ? entries : Object.values(entries))
                .filter((entry) => entry && numeroDe(entry) !== '')
                .map((entry) => ({
                    RacingNumber: numeroDe(entry),
                    X: entry.X ?? null,
                    Y: entry.Y ?? null,
                    Z: entry.Z ?? null,
                    Speed: entry.Speed ?? null,
                    Rpm: entry.Rpm ?? null,
                    Gear: entry.Gear ?? null,
                    Throttle: entry.Throttle ?? null,
                    Brake: entry.Brake ?? null,
                    Drs: entry.Drs ?? null,
                    Status: entry.Status ?? null
                }));

            res.status(200).json({
                Cars: cars,
                LastMessageAt: f1Client.getConnectionStatus().lastMessageAt
            });
        } catch (error) {
            console.error('[API Error] Failed to retrieve car data:', error);
            res.status(500).json({ error: 'Internal server error while reading CarData.' });
        }
    });

    return router;
}

/**
 * Creates the TrackStatus Express router (track flags and safety car state).
 * @param {F1LiveClient} f1Client - Active instance of F1LiveClient.
 * @returns {express.Router} Express router instance.
 */
function createTrackStatusRouter(f1Client) {
    const router = express.Router();

    /**
     * GET /api/track-status
     * Returns the current track status (flags, safety car, DRS).
     */
    router.get('/', (req, res) => {
        try {
            const trackStatus = f1Client.getTrackStatus() || {};
            res.status(200).json({
                TrackStatus: trackStatus,
                LastMessageAt: f1Client.getConnectionStatus().lastMessageAt
            });
        } catch (error) {
            console.error('[API Error] Failed to retrieve track status:', error);
            res.status(500).json({ error: 'Internal server error while reading TrackStatus.' });
        }
    });

    return router;
}

/**
 * Creates the Positions Express router.
 *
 * [Race Center addition] `CarData` carries the telemetry of each car
 * (speed, rpm, gear, throttle, brake); the **coordinates on track** come in
 * their own channel, `Positions`. Without this route the map had no dots to
 * draw, because the upstream service did not subscribe to that channel.
 *
 * @param {F1LiveClient} f1Client - Active instance of F1LiveClient.
 * @returns {express.Router} Express router instance.
 */
function createPositionsRouter(f1Client) {
    const router = express.Router();

    /**
     * GET /api/positions
     * Returns the latest X/Y/Z position of every car on track.
     */
    router.get('/', (req, res) => {
        try {
            const positions = f1Client.getPositions() || {};
            const entries = positions.Entries || [];

            const cars = (Array.isArray(entries) ? entries : Object.values(entries))
                .filter((entry) => entry && numeroDe(entry) !== '')
                .map((entry) => ({
                    RacingNumber: numeroDe(entry),
                    X: entry.X ?? null,
                    Y: entry.Y ?? null,
                    Z: entry.Z ?? null,
                    Status: entry.Status ?? null
                }))
                .filter((car) => car.RacingNumber !== '');

            res.status(200).json({
                Cars: cars,
                LastMessageAt: f1Client.getConnectionStatus().lastMessageAt
            });
        } catch (error) {
            console.error('[API Error] Failed to retrieve car positions:', error);
            res.status(500).json({ error: 'Internal server error while reading Positions.' });
        }
    });

    return router;
}

module.exports = {
    createCarDataRouter,
    createTrackStatusRouter,
    createPositionsRouter
};
