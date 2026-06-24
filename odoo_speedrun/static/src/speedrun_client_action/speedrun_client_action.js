/** @odoo-module **/

import { Component, useState, onWillUnmount, onWillStart } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { GameLobby } from "../components/game_lobby";
import { GameTimer } from "../components/game_timer";
import { GameResults } from "../components/game_results";
import { playSound, playCountdownBeep } from "../services/sound_service";

export class SpeedrunClientAction extends Component {
    static template = "odoo_speedrun.SpeedrunClientAction";
    static components = { GameLobby, GameTimer, GameResults };
    static props = ["*"];

    setup() {
        this.busService = useService("bus_service");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.user = user;

        this.state = useState({
            // lobby | countdown | playing | waiting_others | round_results | final_results
            phase: "lobby",
            game: null,
            countdown: 0,
            myFinished: false,
            myDurationMs: 0,
            myRank: 0,
            myPoints: 0,
            checkResult: null,
        });

        this._onBusNotification = this.onBusNotification.bind(this);
        this.busService.addEventListener("notification", this._onBusNotification);

        // Restore active game on mount
        onWillStart(async () => {
            await this._restoreActiveGame();
        });

        onWillUnmount(() => {
            this.busService.removeEventListener("notification", this._onBusNotification);
            if (this._countdownInterval) clearInterval(this._countdownInterval);
            if (this._lobbyPoll) clearInterval(this._lobbyPoll);
            if (this._roundEndPoll) clearInterval(this._roundEndPoll);
        });
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
                // Check if current user already finished this round
                const me = result.players?.find(p => p.user_id === this.user.userId);
                if (me && me.state === "finished") {
                    this.state.myFinished = true;
                    this.state.myDurationMs = me.duration_ms;
                    this.state.phase = "waiting_others";
                    this._waitForRoundEnd();
                } else {
                    this.state.phase = "playing";
                    this.state.myFinished = false;
                    this.state.checkResult = null;
                    // Notify systray and redirect to home
                    window.dispatchEvent(new CustomEvent("speedrun-update", {
                        detail: { type: "game_started", data: result },
                    }));
                    this.actionService.doAction("menu");
                }
                break;
            }
            case "round_finished":
                this.state.phase = "round_results";
                break;
            case "finished":
                this.state.phase = "final_results";
                break;
        }
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
            }
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
                    // Game started! Update state and redirect
                    for (const key of Object.keys(result)) {
                        this.state.game[key] = result[key];
                    }
                    this.state.phase = "playing";
                    this.state.myFinished = false;
                    this.state.checkResult = null;
                    window.dispatchEvent(new CustomEvent("speedrun-update", {
                        detail: { type: "game_started", data: result },
                    }));
                    this.actionService.doAction("menu");
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
        }
        this.state.phase = "final_results";
    }

    async createGame(name, totalRounds) {
        const result = await rpc("/odoo_speedrun/create_game", {
            name,
            total_rounds: totalRounds || 3,
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
            this.state.phase = "playing";
            this.state.myFinished = false;
            this.state.checkResult = null;
            // Notify systray directly (bus notifications don't reach the sender)
            window.dispatchEvent(new CustomEvent("speedrun-update", {
                detail: { type: "game_started", data: result },
            }));
            // Navigate to Odoo home so user can work on the task
            this.actionService.doAction("menu");
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
        this.state.game = null;
        this.state.phase = "lobby";
        this.state.myFinished = false;
        this.state.checkResult = null;
    }
}

registry.category("actions").add("odoo_speedrun.game_action", SpeedrunClientAction);
