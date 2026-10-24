/**
 * @file tyres.js
 * @description Express routes for retrieving driver tyre compound allocations, stint histories, and strategy data.
 * Enriched with driver TLA, TeamColour, and BroadcastName without altering native PascalCase SignalR properties.
 */

const express = require('express');
const { getLiveTyres, getDriverTyres } = require('../services/leaderboard-service');

/**
 * Creates and configures the tyre strategy Express router.
 * @param {F1LiveClient} f1Client - Active instance of F1LiveClient.
 * @returns {express.Router} Express router instance.
 */
function createTyresRouter(f1Client) {
    const router = express.Router();

    /**
     * GET /api/tyres (also mounted at /api/stints)
     * Retrieves tyre compounds and stint chronologies for all active drivers sorted by live Position.
     */
    router.get('/', (req, res) => {
        try {
            const tyreData = getLiveTyres(f1Client);
            res.status(200).json(tyreData);
        } catch (error) {
            console.error('[API Error] Failed to retrieve live tyre stints:', error);
            res.status(500).json({ error: 'Internal server error while compiling tyre strategy data.' });
        }
    });

    /**
     * GET /api/tyres/:racingNumber
     * Retrieves tyre stint history and compound details for a specific driver.
     */
    router.get('/:racingNumber', (req, res) => {
        try {
            const { racingNumber } = req.params;
            const driverData = getDriverTyres(f1Client, racingNumber);

            if (!driverData) {
                return res.status(404).json({
                    error: 'Driver tyre data not found in active live stream.',
                    racingNumber: racingNumber
                });
            }

            res.status(200).json(driverData);
        } catch (error) {
            console.error(`[API Error] Failed to retrieve tyre data for driver ${req.params.racingNumber}:`, error);
            res.status(500).json({ error: 'Internal server error while compiling driver tyre stints.' });
        }
    });

    return router;
}

module.exports = {
    createTyresRouter
};
