/**
 * @file standings.js
 * @description Express routes for retrieving driver standings, positions, intervals, and lap timing metrics
 * decoupled from tyre stint histories and root session metadata.
 */

const express = require('express');
const { getLiveStandings, getDriverStandings } = require('../services/leaderboard-service');

/**
 * Creates and configures the dedicated standings Express router.
 * @param {F1LiveClient} f1Client - Active instance of F1LiveClient.
 * @returns {express.Router} Express router instance.
 */
function createStandingsRouter(f1Client) {
    const router = express.Router();

    /**
     * GET /api/standings
     * Retrieves classification table sorted by live Position, containing driver identity, positions, intervals, and timing speeds.
     */
    router.get('/', (req, res) => {
        try {
            const standingsData = getLiveStandings(f1Client);
            res.status(200).json(standingsData);
        } catch (error) {
            console.error('[API Error] Failed to retrieve live standings:', error);
            res.status(500).json({ error: 'Internal server error while compiling driver standings.' });
        }
    });

    /**
     * GET /api/standings/:racingNumber
     * Retrieves standings and timing data for a single specific driver by racing number.
     */
    router.get('/:racingNumber', (req, res) => {
        try {
            const { racingNumber } = req.params;
            const driverData = getDriverStandings(f1Client, racingNumber);

            if (!driverData) {
                return res.status(404).json({
                    error: 'Driver not found in active standings stream.',
                    racingNumber: racingNumber
                });
            }

            res.status(200).json(driverData);
        } catch (error) {
            console.error(`[API Error] Failed to retrieve standings for driver ${req.params.racingNumber}:`, error);
            res.status(500).json({ error: 'Internal server error while compiling driver standings.' });
        }
    });

    return router;
}

module.exports = {
    createStandingsRouter
};
