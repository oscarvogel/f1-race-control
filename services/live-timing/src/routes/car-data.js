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
                .filter((entry) => entry && entry.Number !== undefined)
                .map((entry) => ({
                    RacingNumber: String(entry.Number),
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

module.exports = {
    createCarDataRouter,
    createTrackStatusRouter
};
