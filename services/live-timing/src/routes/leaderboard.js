/**
 * @file leaderboard.js
 * @description Express routes for retrieving live F1 driver standings and classification.
 * Returns exact SignalR Core PascalCase properties without renaming.
 */

const express = require('express');
const { getLiveLeaderboard, getDriverLeaderboard } = require('../services/leaderboard-service');

/**
 * Creates and configures the leaderboard Express router.
 * @param {F1LiveClient} f1Client - Active instance of F1LiveClient.
 * @returns {express.Router} Express router instance.
 */
function createLeaderboardRouter(f1Client) {
    const router = express.Router();

    /**
     * GET /api/leaderboard
     * Retrieves the current full session leaderboard, sorted driver list, and merged driver telemetry/metadata.
     */
    router.get('/', (req, res) => {
        try {
            const leaderboardData = getLiveLeaderboard(f1Client);
            res.status(200).json(leaderboardData);
        } catch (error) {
            console.error('[API Error] Failed to retrieve live leaderboard:', error);
            res.status(500).json({ error: 'Internal server error while compiling leaderboard data.' });
        }
    });

    /**
     * GET /api/leaderboard/:racingNumber
     * Retrieves live telemetry and classification data for a specific driver by their racing number (e.g., "1", "44").
     */
    router.get('/:racingNumber', (req, res) => {
        try {
            const { racingNumber } = req.params;
            const driverData = getDriverLeaderboard(f1Client, racingNumber);

            if (!driverData) {
                return res.status(404).json({
                    error: 'Driver not found in active live timing stream.',
                    racingNumber: racingNumber
                });
            }

            res.status(200).json(driverData);
        } catch (error) {
            console.error(`[API Error] Failed to retrieve data for driver ${req.params.racingNumber}:`, error);
            res.status(500).json({ error: 'Internal server error while compiling driver telemetry.' });
        }
    });

    return router;
}

module.exports = {
    createLeaderboardRouter
};
