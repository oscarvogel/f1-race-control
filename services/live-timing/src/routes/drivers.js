/**
 * @file drivers.js
 * @description Express routes for querying the official Formula 1 DriverList directory and metadata.
 */

const express = require('express');
const { getDriversDirectory } = require('../services/leaderboard-service');

/**
 * Creates and configures the driver directory Express router.
 * @param {F1LiveClient} f1Client - Active instance of F1LiveClient.
 * @returns {express.Router} Express router instance.
 */
function createDriversRouter(f1Client) {
    const router = express.Router();

    /**
     * GET /api/drivers
     * Retrieves official team and driver metadata for the session (names, acronyms, team colors, country codes).
     */
    router.get('/', (req, res) => {
        try {
            const directory = getDriversDirectory(f1Client);
            res.status(200).json(directory);
        } catch (error) {
            console.error('[API Error] Failed to retrieve driver directory:', error);
            res.status(500).json({ error: 'Internal server error while retrieving DriverList data.' });
        }
    });

    /**
     * GET /api/drivers/:racingNumber
     * Retrieves metadata for an individual driver by racing number.
     */
    router.get('/:racingNumber', (req, res) => {
        try {
            const { racingNumber } = req.params;
            const directory = getDriversDirectory(f1Client);
            const driverMeta = directory.Drivers[racingNumber];

            if (!driverMeta) {
                return res.status(404).json({
                    error: 'Driver metadata not found in active session DriverList.',
                    racingNumber: racingNumber
                });
            }

            res.status(200).json({
                RacingNumber: racingNumber,
                Data: driverMeta
            });
        } catch (error) {
            console.error(
                `[API Error] Failed to retrieve driver directory entry for ${req.params.racingNumber}:`,
                error
            );
            res.status(500).json({ error: 'Internal server error while retrieving driver metadata.' });
        }
    });

    return router;
}

module.exports = {
    createDriversRouter
};
