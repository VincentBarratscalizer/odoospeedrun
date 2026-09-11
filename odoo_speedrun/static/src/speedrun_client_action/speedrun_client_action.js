/** @odoo-module **/

import { Component, useState, onWillUnmount, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { GameLobby } from "../components/game_lobby";
import { GameTimer } from "../components/game_timer";
import { GameResults } from "../components/game_results";
import { TournamentPanel } from "../components/tournament_panel";
import { DailyChallenge } from "../components/daily_challenge";
import { GameTimeAttack } from "../components/game_time_attack";
import { playSound, playCountdownBeep } from "../services/sound_service";

export class SpeedrunClientAction extends Component {
    static template = "odoo_speedrun.SpeedrunClientAction";
    static components = { GameLobby, GameTimer, GameResults, TournamentPanel, DailyChallenge, GameTimeAttack };
    static props = ["*"];

    setup() {
        this.busService = useService("bus_service");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.user = user;

        this.state = useState({
            // lobby | countdown | playing | waiting_others | round_results | final_results | time_attack
            phase: "lobby",
            game: null,
            countdown: 0,
            myFinished: false,
            mySurrendered: false,
            myDurationMs: 0,
            myRank: 0,
            myPoints: 0,
            checkResult: null,
            stats: null,
            taskGroups: [],
            matchmaking: { searching: false, waitSeconds: 0, queueSize: 0 },
            // Tournaments
            tournaments: null,
            tournament: null,
        });
        // Id of a tournament to return to after a bracket match finishes
        this._returnTournamentId = null;

        this._onBusNotification = this.onBusNotification.bind(this);
        this.busService.addEventListener("notification", this._onBusNotification);

        // Restore active game on mount
        onWillStart(async () => {
            await this._restoreActiveGame();
            await this._loadStats();
            await this._loadTaskGroups();
            await this._restoreQueue();
        });

        onWillUnmount(() => {
            this.busService.removeEventListener("notification", this._onBusNotification);
            if (this._countdownInterval) clearInterval(this._countdownInterval);
            if (this._lobbyPoll) clearInterval(this._lobbyPoll);
            if (this._roundResultsPoll) clearInterval(this._roundResultsPoll);
            if (this._roundEndPoll) clearInterval(this._roundEndPoll);
            if (this._queuePoll) clearInterval(this._queuePoll);
            if (this._tournamentPoll) clearInterval(this._tournamentPoll);
            // ta_end is handled client-side inside GameTimeAttack
        });
    }

    async _loadStats() {
        try {
            this.state.stats = await rpc("/odoo_speedrun/my_stats", {});
        } catch {
            // Stats are optional, ignore failures
        }
    }

    async _loadTaskGroups() {
        try {
            this.state.taskGroups = await rpc("/odoo_speedrun/task_groups", {});
        } catch {
            this.state.taskGroups = [];
        }
    }

    async _restoreQueue() {
        if (this.state.game) return;
        try {
            const status = await rpc("/odoo_speedrun/matchmaking/status", {});
            if (status.in_queue) {
                this.state.matchmaking.searching = true;
                this.state.matchmaking.waitSeconds = status.wait_seconds || 0;
                this.state.matchmaking.queueSize = status.queue_size || 0;
                this._startQueuePoll();
            } else if (status.matched && status.game_info) {
                this._onMatchFound(status.game_info);
            }
        } catch {
            // Ignore
        }
    }

    async _restoreActiveGame() {
        try {
            const result = await rpc("/odoo_speedrun/my_active_game", {});
            if (result && result.id) {
                this.state.game = result;
                this.busService.forceUpdateChannels();
                this._applyGameState(result);
            }
        } catch {
            // No active game, stay in lobby
        }
    }

    _applyGameState(result) {
        switch (result.state) {
            case "waiting":
                this.state.phase = "lobby";
                // Poll for game state changes (backup for bus)
                this._startLobbyPoll();
                break;
            case "countdown":
                this._startCountdown(result.countdown_remaining || 5);
                break;
            case "running": {
                // Time Attack: dedicated phase — no redirect to home
                if (result.game_mode === "time_attack") {
                    this.state.phase = "time_attack";
                    break;
                }
                // Check if current user already finished this round
                const me = result.players?.find(p => p.user_id === this.user.userId);
                if (me && (me.state === "finished" || me.state === "dnf")) {
                    this.state.myFinished = true;
                    this.state.mySurrendered = me.state === "dnf";
                    this.state.myDurationMs = me.duration_ms;
                    this.state.phase = "waiting_others";
                    this._waitForRoundEnd();
                } else {
                    this.state.phase = "playing";
                    this.state.myFinished = false;
                    this.state.mySurrendered = false;
                    this.state.checkResult = null;
                    // Notify systray
                    window.dispatchEvent(new CustomEvent("speedrun-update", {
                        detail: { type: "game_started", data: result },
                    }));
                    // Only redirect to home if coming from lobby/countdown (first time)
                    // If user clicked systray, they want to see the task — don't redirect
                    if (this._redirectToHome) {
                        this._redirectToHome = false;
                        this.actionService.doAction("menu");
                    }
                }
                break;
            }
            case "round_finished":
                this.state.phase = "round_results";
                this._startRoundResultsPoll();
                break;
            case "finished":
                this.state.phase = "final_results";
                break;
        }
    }

    _startRoundResultsPoll() {
        if (this._roundResultsPoll) clearInterval(this._roundResultsPoll);
        this._roundResultsPoll = setInterval(async () => {
            if (this.state.phase !== "round_results" || !this.state.game) {
                clearInterval(this._roundResultsPoll);
                this._roundResultsPoll = null;
                return;
            }
            try {
                const result = await rpc("/odoo_speedrun/game_info", { game_id: this.state.game.id });
                if (result && !result.error && result.state !== "round_finished") {
                    clearInterval(this._roundResultsPoll);
                    this._roundResultsPoll = null;
                    for (const key of Object.keys(result)) {
                        this.state.game[key] = result[key];
                    }
                    this._redirectToHome = true;
                    this._applyGameState(result);
                }
            } catch {
                // Ignore
            }
        }, 2000);
    }

    _startLobbyPoll() {
        if (this._lobbyPoll) clearInterval(this._lobbyPoll);
        this._lobbyPoll = setInterval(async () => {
            if (this.state.phase !== "lobby" || !this.state.game) {
                clearInterval(this._lobbyPoll);
                this._lobbyPoll = null;
                return;
            }
            try {
                const result = await rpc("/odoo_speedrun/game_info", { game_id: this.state.game.id });
                if (result && !result.error) {
                    // Update players list
                    this.state.game.players = result.players;
                    this.state.game.player_count = result.player_count;
                    // Detect state change
                    if (result.state !== "waiting") {
                        clearInterval(this._lobbyPoll);
                        this._lobbyPoll = null;
                        for (const key of Object.keys(result)) {
                            this.state.game[key] = result[key];
                        }
                        // First transition from lobby — redirect to home after countdown
                        this._redirectToHome = true;
                        this._applyGameState(result);
                    }
                }
            } catch {
                // Ignore polling errors
            }
        }, 2000);
    }

    onBusNotification({ detail: notifications }) {
        for (const { type, payload } of notifications) {
            switch (type) {
                case "speedrun/player_joined":
                    playSound("playerJoined");
                    if (this.state.game) this.refreshGame();
                    break;
                case "speedrun/player_left":
                    if (this.state.game) this.refreshGame();
                    break;
                case "speedrun/countdown_start":
                    this.onCountdownStart(payload);
                    break;
                case "speedrun/game_started":
                    this.onGameStarted(payload);
                    break;
                case "speedrun/player_finished":
                    this.onPlayerFinished(payload);
                    break;
                case "speedrun/round_over":
                    this.onRoundOver(payload);
                    break;
                case "speedrun/game_over":
                    this.onGameOver(payload);
                    break;
                case "speedrun/ta_game_started":
                    this.onTAGameStarted(payload);
                    break;
                case "speedrun/ta_score_update":
                    this.onTAScoreUpdate(payload);
                    break;
                case "speedrun/match_found":
                    this._onMatchFound(payload.game_info);
                    break;
                case "speedrun/tournament_update":
                    if (this.state.tournament && this.state.tournament.id === payload.tournament_id) {
                        this.refreshTournament();
                    }
                    if (this.state.tournaments) {
                        this._loadTournaments();
                    }
                    break;
                case "speedrun/badge_earned":
                    playSound("taskComplete");
                    this.notification.add(
                        `${payload.badge_icon} Badge earned: ${payload.badge_name}` +
                        (payload.xp_reward ? ` (+${payload.xp_reward} XP)` : ""),
                        { type: "success", sticky: true },
                    );
                    this._loadStats();
                    break;
                case "speedrun/level_up":
                    playSound("gameOver");
                    this.notification.add(
                        `🎉 Level up! You are now level ${payload.level} — ${payload.level_title}`,
                        { type: "success", sticky: true },
                    );
                    this._loadStats();
                    break;
            }
        }
    }

    // ------------------------------------------------------------------
    // Matchmaking
    // ------------------------------------------------------------------
    async joinMatchmaking() {
        const result = await rpc("/odoo_speedrun/matchmaking/join", {});
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        if (result.matched && result.game_info) {
            this._onMatchFound(result.game_info);
            return;
        }
        this.state.matchmaking.searching = true;
        this.state.matchmaking.waitSeconds = result.wait_seconds || 0;
        this.state.matchmaking.queueSize = result.queue_size || 1;
        this._startQueuePoll();
    }

    async cancelMatchmaking() {
        await rpc("/odoo_speedrun/matchmaking/leave", {});
        this._stopQueuePoll();
        this.state.matchmaking.searching = false;
        this.state.matchmaking.waitSeconds = 0;
    }

    _startQueuePoll() {
        this._stopQueuePoll();
        this._queuePoll = setInterval(async () => {
            if (!this.state.matchmaking.searching) {
                this._stopQueuePoll();
                return;
            }
            try {
                const status = await rpc("/odoo_speedrun/matchmaking/status", {});
                if (status.matched && status.game_info) {
                    this._onMatchFound(status.game_info);
                } else if (status.in_queue) {
                    this.state.matchmaking.waitSeconds = status.wait_seconds || 0;
                    this.state.matchmaking.queueSize = status.queue_size || 0;
                } else {
                    // Kicked out of the queue (e.g. cancelled elsewhere)
                    this.state.matchmaking.searching = false;
                    this._stopQueuePoll();
                }
            } catch {
                // Ignore polling errors
            }
        }, 2000);
    }

    _stopQueuePoll() {
        if (this._queuePoll) {
            clearInterval(this._queuePoll);
            this._queuePoll = null;
        }
    }

    // ------------------------------------------------------------------
    // Tournaments
    // ------------------------------------------------------------------
    async openTournaments() {
        this.state.tournament = null;
        this.state.phase = "tournaments";
        await this._loadTournaments();
    }

    async _loadTournaments() {
        try {
            this.state.tournaments = await rpc("/odoo_speedrun/tournament/list", {});
        } catch {
            this.state.tournaments = [];
        }
    }

    backToArena() {
        this._stopTournamentPoll();
        this.state.phase = "lobby";
        this.state.tournament = null;
        if (!this.state.game) {
            this._startLobbyPoll?.();
        }
    }

    async openTournament(tournamentId) {
        if (!tournamentId) {
            // null => return to the list
            this._stopTournamentPoll();
            this.state.tournament = null;
            this.state.phase = "tournaments";
            await this._loadTournaments();
            return;
        }
        const result = await rpc("/odoo_speedrun/tournament/get", { tournament_id: tournamentId });
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        this.state.tournament = result;
        this.state.phase = "tournament";
        this._startTournamentPoll();
    }

    async refreshTournament() {
        if (!this.state.tournament) return;
        const result = await rpc("/odoo_speedrun/tournament/get", {
            tournament_id: this.state.tournament.id,
        });
        if (result && !result.error) {
            this.state.tournament = result;
        }
    }

    _startTournamentPoll() {
        this._stopTournamentPoll();
        this._tournamentPoll = setInterval(async () => {
            if (this.state.phase !== "tournament" || !this.state.tournament) {
                this._stopTournamentPoll();
                return;
            }
            await this.refreshTournament();
            // If one of my matches has started, jump into it.
            if (!this.state.game) {
                try {
                    const active = await rpc("/odoo_speedrun/my_active_game", {});
                    if (active && active.id && active.tournament_id) {
                        this._onMatchFound(active);
                    }
                } catch {
                    // ignore
                }
            }
        }, 3000);
    }

    _stopTournamentPoll() {
        if (this._tournamentPoll) {
            clearInterval(this._tournamentPoll);
            this._tournamentPoll = null;
        }
    }

    async createTournament(vals) {
        const result = await rpc("/odoo_speedrun/tournament/create", vals);
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        this.state.tournament = result;
        this.state.phase = "tournament";
        this._startTournamentPoll();
    }

    async _tournamentAction(url, extra = {}) {
        if (!this.state.tournament) return;
        const result = await rpc(url, { tournament_id: this.state.tournament.id, ...extra });
        if (result && result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        if (result && result.id) {
            this.state.tournament = result;
        }
    }

    registerTournament() {
        return this._tournamentAction("/odoo_speedrun/tournament/register");
    }
    unregisterTournament() {
        return this._tournamentAction("/odoo_speedrun/tournament/unregister");
    }
    closeRegistration() {
        return this._tournamentAction("/odoo_speedrun/tournament/close_registration");
    }
    reopenRegistration() {
        return this._tournamentAction("/odoo_speedrun/tournament/reopen_registration");
    }
    autoSeed(method) {
        return this._tournamentAction("/odoo_speedrun/tournament/auto_seed", { method });
    }
    moveSeed(userId, direction) {
        return this._tournamentAction("/odoo_speedrun/tournament/move_seed", {
            user_id: userId,
            direction,
        });
    }
    startTournament() {
        return this._tournamentAction("/odoo_speedrun/tournament/start");
    }

    async cancelTournament() {
        if (!this.state.tournament) return;
        const result = await rpc("/odoo_speedrun/tournament/cancel", {
            tournament_id: this.state.tournament.id,
        });
        if (result && result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        this._stopTournamentPoll();
        this.state.tournament = null;
        this.state.phase = "tournaments";
        await this._loadTournaments();
    }

    async playMatch(matchId) {
        const result = await rpc("/odoo_speedrun/tournament/play_match", { match_id: matchId });
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        if (result.game_info) {
            this._onMatchFound(result.game_info);
        }
    }

    _onMatchFound(gameInfo) {
        if (this.state.game && this.state.game.id === gameInfo.id) return;
        // Remember the tournament so we can return to its bracket afterwards.
        this._returnTournamentId = gameInfo.tournament_id || null;
        this._stopTournamentPoll();
        this._stopQueuePoll();
        this.state.matchmaking.searching = false;
        this.state.matchmaking.waitSeconds = 0;
        playSound("playerJoined");
        this.notification.add("Match found! Get ready...", { type: "success" });
        this.state.game = gameInfo;
        this.busService.forceUpdateChannels();
        this._redirectToHome = true;
        this._applyGameState(gameInfo);
        // Ranked matches auto-start: if still waiting/countdown info missing, poll
        if (gameInfo.state === "waiting") {
            this._startLobbyPoll();
        }
    }

    onCountdownStart(payload) {
        if (this.state.phase === "countdown" || this.state.phase === "playing") return;
        // Update task info from bus payload
        if (this.state.game && payload.task_name) {
            this.state.game.task_name = payload.task_name;
            this.state.game.task_description = payload.task_description || "";
            this.state.game.current_round = payload.current_round;
            this.state.game.total_rounds = payload.total_rounds;
        }
        this._startCountdown(payload.countdown_seconds || 5);
    }

    _startCountdown(seconds) {
        if (this._countdownInterval) clearInterval(this._countdownInterval);
        this.state.phase = "countdown";
        this.state.countdown = seconds;
        playCountdownBeep(seconds);
        this._countdownInterval = setInterval(() => {
            this.state.countdown--;
            playCountdownBeep(this.state.countdown);
            if (this.state.countdown <= 0) {
                clearInterval(this._countdownInterval);
                this._countdownInterval = null;
                if (this.state.game && this.state.game.host_id === this.user.userId) {
                    // Host: trigger game start on server
                    this.beginGame();
                } else {
                    // Non-host: poll until game is running, then redirect
                    this._waitForGameStart();
                }
            }
        }, 1000);
    }

    async _waitForGameStart() {
        // Poll until game transitions to "running" state
        const gameId = this.state.game.id;
        const poll = async () => {
            if (this.state.phase !== "countdown") return; // Already transitioned
            try {
                const result = await rpc("/odoo_speedrun/game_info", { game_id: gameId });
                if (result && !result.error && result.state === "running") {
                    for (const key of Object.keys(result)) {
                        this.state.game[key] = result[key];
                    }
                    if (result.game_mode === "time_attack") {
                        // Time Attack: stay in the speedrun UI
                        this.state.phase = "time_attack";
                    } else {
                        this.state.phase = "playing";
                        this.state.myFinished = false;
                        this.state.mySurrendered = false;
                        this.state.checkResult = null;
                        window.dispatchEvent(new CustomEvent("speedrun-update", {
                            detail: { type: "game_started", data: result },
                        }));
                        this.actionService.doAction("menu");
                    }
                } else {
                    // Not yet running, try again in 500ms
                    setTimeout(poll, 500);
                }
            } catch {
                setTimeout(poll, 500);
            }
        };
        poll();
    }

    onGameStarted(payload) {
        if (this.state.game) {
            this.state.game.task_name = payload.task_name;
            this.state.game.task_description = payload.task_description;
            this.state.game.start_time = payload.start_time;
            this.state.game.current_round = payload.current_round;
            this.state.game.total_rounds = payload.total_rounds;
            this.state.game.state = "running";
        }
        this.state.phase = "playing";
        this.state.myFinished = false;
        this.state.mySurrendered = false;
        this.state.checkResult = null;
        // Navigate to Odoo home so user can work on the task
        this.actionService.doAction("menu");
    }

    onPlayerFinished(payload) {
        if (!this.state.game) return;
        const player = this.state.game.players.find(p => p.user_id === payload.user_id);
        if (player) {
            player.state = "finished";
            player.duration_ms = payload.duration_ms;
        }
    }

    onRoundOver(payload) {
        if (this.state.phase === "round_results" || this.state.phase === "final_results") return;
        playSound("roundOver");
        if (this.state.game) {
            this.state.game.standings = payload.standings;
            this.state.game.round_results = payload.round_results;
            this.state.game.current_round = payload.current_round;
            this.state.game.state = "round_finished";
            // Battle Royale: carry life changes and sync players' lives from standings
            this.state.game.life_changes = payload.life_changes || [];
            if (payload.standings) {
                for (const s of payload.standings) {
                    const p = this.state.game.players?.find(pl => pl.user_id === s.user_id);
                    if (p) p.lives_remaining = s.lives_remaining || 0;
                }
            }
        }
        this.state.phase = "round_results";
    }

    onGameOver(payload) {
        if (this.state.phase === "final_results") return;
        playSound("gameOver");
        if (this.state.game) {
            this.state.game.state = "finished";
            this.state.game.winner_id = payload.winner_id;
            this.state.game.winner_name = payload.winner_name;
            this.state.game.standings = payload.standings;
            this.state.game.life_changes = payload.life_changes || [];
        }
        this.state.phase = "final_results";
        this._loadStats();
    }

    onTAGameStarted(payload) {
        if (this.state.game) {
            this.state.game.start_time = payload.start_time;
            this.state.game.state = "running";
            this.state.game.ta_duration = payload.ta_duration;
            this.state.game.ta_current_task_name = payload.task_name;
            this.state.game.ta_current_task_description = payload.task_description;
        }
        this.state.phase = "time_attack";
    }

    onTAScoreUpdate(payload) {
        if (!this.state.game) return;
        const p = this.state.game.players?.find(pl => pl.user_id === payload.user_id);
        if (p) {
            p.ta_completed_count = payload.ta_completed_count;
        }
        // The GameTimeAttack component handles its own current-task display
        // via the check result, but we also update game state for restoration.
        if (payload.user_id === this.user.userId && this.state.game) {
            this.state.game.ta_current_task_name = payload.next_task_name;
            this.state.game.ta_current_task_description = payload.next_task_description;
        }
    }

    async endTimeAttack() {
        if (!this.state.game) return;
        try {
            const result = await rpc("/odoo_speedrun/time_attack/end", {
                game_id: this.state.game.id,
            });
            if (result && result.error) {
                // Not an error worth showing — server may have already ended it
                // or there's a slight timing difference; game_over bus will arrive
            }
        } catch {
            // Ignore; game_over bus event will handle transition
        }
    }

    // Battle Royale helpers used by the template
    get brActivePlayers() {
        if (!this.state.game || this.state.game.game_mode !== "battle_royale") return 0;
        return (this.state.game.players || []).filter(p => (p.lives_remaining || 0) > 0).length;
    }

    get myLivesRemaining() {
        if (!this.state.game || this.state.game.game_mode !== "battle_royale") return null;
        const me = (this.state.game.players || []).find(p => p.user_id === this.user.userId);
        return me !== undefined ? (me.lives_remaining ?? 0) : null;
    }

    livesDisplay(n) {
        if (n === null || n === undefined) return "";
        if (n <= 0) return "💀 Éliminé";
        const hearts = "❤️".repeat(Math.min(n, 5));
        return n > 5 ? `❤️×${n}` : hearts;
    }

    async createGame(name, totalRounds, groupIds, gameMode, brLives, brCutoff, taDuration) {
        const result = await rpc("/odoo_speedrun/create_game", {
            name,
            total_rounds: totalRounds || 3,
            group_ids: groupIds || [],
            game_mode: gameMode || "points",
            br_lives: brLives || 3,
            br_cutoff: brCutoff || 1,
            ta_duration: taDuration || 120,
        });
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        this.state.game = result;
        this.state.phase = "lobby";
        this.busService.forceUpdateChannels();
        this._startLobbyPoll();
    }

    async joinGame(code) {
        const result = await rpc("/odoo_speedrun/join_game", { code });
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        this.state.game = result;
        this.state.phase = "lobby";
        this.busService.forceUpdateChannels();
        this._startLobbyPoll();
    }

    async leaveGame() {
        if (!this.state.game) return;
        await rpc("/odoo_speedrun/leave_game", { game_id: this.state.game.id });
        this.state.game = null;
        this.state.phase = "lobby";
    }

    async startGame() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/start_game", { game_id: this.state.game.id });
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        // Store task info before countdown
        this.state.game.task_name = result.task_name;
        this.state.game.task_description = result.task_description;
        this.state.game.current_round = result.current_round;
        this.state.game.total_rounds = result.total_rounds;
        // Notify systray of countdown with task info
        window.dispatchEvent(new CustomEvent("speedrun-update", {
            detail: { type: "countdown", data: result },
        }));
        this._startCountdown(result.countdown_seconds || 5);
    }

    async nextRound() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/next_round", { game_id: this.state.game.id });
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        // Store task info before countdown
        this.state.game.task_name = result.task_name;
        this.state.game.task_description = result.task_description;
        this.state.game.current_round = result.current_round;
        this.state.game.total_rounds = result.total_rounds;
        // Notify systray of countdown with task info
        window.dispatchEvent(new CustomEvent("speedrun-update", {
            detail: { type: "countdown", data: result },
        }));
        this._startCountdown(result.countdown_seconds || 5);
    }

    async beginGame() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/begin_game", { game_id: this.state.game.id });
        if (result && !result.error) {
            for (const key of Object.keys(result)) {
                this.state.game[key] = result[key];
            }
            if (result.game_mode === "time_attack") {
                // Time Attack: stay in the speedrun UI, no redirect
                this.state.phase = "time_attack";
            } else {
                this.state.phase = "playing";
                this.state.myFinished = false;
                this.state.mySurrendered = false;
                this.state.checkResult = null;
                // Notify systray directly (bus notifications don't reach the sender)
                window.dispatchEvent(new CustomEvent("speedrun-update", {
                    detail: { type: "game_started", data: result },
                }));
                // Navigate to Odoo home so user can work on the task
                this.actionService.doAction("menu");
            }
        }
    }

    async checkCompletion() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/check_completion", { game_id: this.state.game.id });
        this.state.checkResult = result;
        if (result.success) {
            this.state.myFinished = true;
            this.state.myDurationMs = result.duration_ms;
            this.state.myRank = result.rank;
            this.state.myPoints = result.points;
            playSound("taskComplete");
            if (result.all_done && result.game_info) {
                // All players finished — go straight to results
                this._showRoundResults(result.game_info);
            } else {
                // Show waiting screen with my time, poll for round end
                this.state.phase = "waiting_others";
                window.dispatchEvent(new CustomEvent("speedrun-update", {
                    detail: { type: "player_done" },
                }));
                this._waitForRoundEnd();
            }
        } else if (result.error) {
            playSound("error");
            this.notification.add(result.error, { type: "warning" });
        }
    }

    async surrender() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/surrender", { game_id: this.state.game.id });
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        if (result.success) {
            this.state.myFinished = true;
            this.state.mySurrendered = true;
            this.state.myDurationMs = 0;
            this.state.myRank = 0;
            this.state.myPoints = 0;
            playSound("error");
            if (result.all_done && result.game_info) {
                // Everyone is done — go straight to results
                this._showRoundResults(result.game_info);
            } else {
                // Show waiting screen, poll for round end
                this.state.phase = "waiting_others";
                window.dispatchEvent(new CustomEvent("speedrun-update", {
                    detail: { type: "player_done" },
                }));
                this._waitForRoundEnd();
            }
        }
    }

    _showRoundResults(gameInfo) {
        for (const key of Object.keys(gameInfo)) {
            this.state.game[key] = gameInfo[key];
        }
        const isFinal = this.state.game.state === "finished";
        this.state.phase = isFinal ? "final_results" : "round_results";
        if (isFinal) playSound("gameOver");
        else playSound("roundOver");
        window.dispatchEvent(new CustomEvent("speedrun-update", {
            detail: { type: isFinal ? "game_over" : "round_over", data: gameInfo },
        }));
    }

    async _waitForRoundEnd() {
        if (this._roundEndPoll) clearInterval(this._roundEndPoll);
        this._roundEndPoll = setInterval(async () => {
            if (!this.state.game || (this.state.phase !== "playing" && this.state.phase !== "waiting_others")) {
                clearInterval(this._roundEndPoll);
                this._roundEndPoll = null;
                return;
            }
            try {
                const result = await rpc("/odoo_speedrun/game_info", { game_id: this.state.game.id });
                if (result && !result.error) {
                    // Update players list in waiting_others phase
                    if (this.state.phase === "waiting_others") {
                        this.state.game.players = result.players;
                    }
                    if (result.state === "round_finished" || result.state === "finished") {
                        clearInterval(this._roundEndPoll);
                        this._roundEndPoll = null;
                        this._showRoundResults(result);
                    }
                }
            } catch {
                // Ignore
            }
        }, 2000);
    }

    async refreshGame() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/game_info", { game_id: this.state.game.id });
        if (result && !result.error) {
            for (const key of Object.keys(result)) {
                this.state.game[key] = result[key];
            }
        }
    }

    formatTime(ms) {
        if (!ms) return "DNF";
        const totalSeconds = Math.floor(ms / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        const millis = ms % 1000;
        return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
    }

    playAgain() {
        const returnTo = this._returnTournamentId;
        // Tell the server we've left the results screen so a refresh doesn't
        // restore the finished game and drop us back into final results.
        if (this.state.game) {
            rpc("/odoo_speedrun/dismiss_game", { game_id: this.state.game.id }).catch(() => {});
        }
        this.state.game = null;
        this.state.myFinished = false;
        this.state.mySurrendered = false;
        this.state.checkResult = null;
        this._loadStats();
        if (returnTo) {
            this._returnTournamentId = null;
            this.openTournament(returnTo);
        } else {
            this.state.phase = "lobby";
        }
    }
}

registry.category("actions").add("odoo_speedrun.game_action", SpeedrunClientAction);
