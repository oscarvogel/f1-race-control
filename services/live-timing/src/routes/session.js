/**
 * @file session.js
 * @description Express routes exposing specialized session state, meteorological telemetry, lap progress,
 * race control messages, and team radio transmissions.
 */

const express = require('express');
const { getEnrichedTeamRadio } = require('../services/leaderboard-service');

/**
 * Creates and configures the session and environmental data Express router.
 * @param {F1LiveClient} f1Client - Active instance of F1LiveClient.
 * @returns {express.Router} Express router instance.
 */
function createSessionRouter(f1Client) {
    const router = express.Router();

    /**
     * GET /api/session
     * Retrieves current meeting and session metadata (SessionInfo channel).
     */
    router.get('/session', (req, res) => {
        try {
            const sessionInfo = f1Client.getSessionInfo() || {};
            res.status(200).json({ Session: sessionInfo });
        } catch (error) {
            console.error('[API Error] Failed to retrieve session info:', error);
            res.status(500).json({ error: 'Internal server error while querying SessionInfo.' });
        }
    });

    /**
     * GET /api/lap-count (also accessible via /api/laps)
     * Retrieves current lap counter and total scheduled distance (LapCount channel).
     */
    const getLapsHandler = (req, res) => {
        try {
            const lapCount = f1Client.getLapCount() || {};
            res.status(200).json({ LapCount: lapCount });
        } catch (error) {
            console.error('[API Error] Failed to retrieve lap count:', error);
            res.status(500).json({ error: 'Internal server error while querying LapCount.' });
        }
    };
    router.get('/lap-count', getLapsHandler);
    router.get('/laps', getLapsHandler);

    /**
     * GET /api/weather
     * Retrieves atmospheric and track environmental measurements (WeatherData channel).
     */
    router.get('/weather', (req, res) => {
        try {
            const weather = f1Client.getWeatherData() || {};
            res.status(200).json({ Weather: weather });
        } catch (error) {
            console.error('[API Error] Failed to retrieve weather telemetry:', error);
            res.status(500).json({ error: 'Internal server error while querying WeatherData.' });
        }
    });

    /**
     * GET /api/race-control (also accessible via /api/flags)
     * Retrieves official FIA race control messages, flags, safety car deployments, and track warnings.
     */
    const getRaceControlHandler = (req, res) => {
        try {
            const messages = f1Client.getRaceControlMessages() || [];
            res.status(200).json({ RaceControl: messages });
        } catch (error) {
            console.error('[API Error] Failed to retrieve race control messages:', error);
            res.status(500).json({ error: 'Internal server error while querying RaceControlMessages.' });
        }
    };
    router.get('/race-control', getRaceControlHandler);
    router.get('/flags', getRaceControlHandler);

    /**
     * GET /api/radio (also accessible via /api/team-radio)
     * Retrieves recent broadcast team radio transmissions enriched with driver identity.
     */
    const getRadioHandler = (req, res) => {
        try {
            const radioData = getEnrichedTeamRadio(f1Client);
            res.status(200).json(radioData);
        } catch (error) {
            console.error('[API Error] Failed to retrieve team radio transmissions:', error);
            res.status(500).json({ error: 'Internal server error while querying TeamRadio.' });
        }
    };
    router.get('/radio', getRadioHandler);
    router.get('/team-radio', getRadioHandler);

    return router;
}

module.exports = {
    createSessionRouter
};
