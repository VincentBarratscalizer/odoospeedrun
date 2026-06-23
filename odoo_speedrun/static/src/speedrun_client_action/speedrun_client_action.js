/** @odoo-module **/

import { Component, useState, onWillUnmount } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { GameLobby } from "../components/game_lobby";
import { GameTimer } from "../components/game_timer";
import { GameResults } from "../components/game_results";

export class SpeedrunClientAction extends Component {
    static template = "odoo_speedrun.SpeedrunClientAction";
    static components = { GameLobby, GameTimer, GameResults };
    static props = ["*"];

    setup() {
        this.busService = useService("bus_service");
        this.notification = useService("notification");
        this.user = user;

        this.state = useState({
            phase: "lobby", // lobby | countdown | playing | results
            game: null,
            countdown: 0,
            myFinished: false,
            checkResult: null,
        });

        // Subscribe to bus events
        this.busService.addEventListener("notification", this.onBusNotification.bind(this));

        onWillUnmount(() => {
            this.busService.removeEventListener("notification", this.onBusNotification.bind(this));
            if (this._countdownInterval) clearInterval(this._countdownInterval);
            if (this._timerInterval) clearInterval(this._timerInterval);
        });
    }

    onBusNotification({ detail: notifications }) {
        for (const { type, payload } of notifications) {
            switch (type) {
                case "speedrun/player_joined":
                    this.onPlayerJoined(payload);
                    break;
                case "speedrun/player_left":
                    this.onPlayerLeft(payload);
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
                case "speedrun/game_over":
                    this.onGameOver(payload);
                    break;
            }
        }
    }

    async onPlayerJoined(payload) {
        if (this.state.game) {
            await this.refreshGame();
        }
    }

    async onPlayerLeft(payload) {
        if (this.state.game) {
            await this.refreshGame();
        }
    }

    onCountdownStart(payload) {
        // Ignore if we already started countdown (host triggers it locally)
        if (this.state.phase === "countdown" || this.state.phase === "playing") {
            return;
        }
        this._startCountdown(payload.countdown_seconds);
    }

    _startCountdown(seconds) {
        if (this._countdownInterval) {
            clearInterval(this._countdownInterval);
        }
        this.state.phase = "countdown";
        this.state.countdown = seconds;
        this._countdownInterval = setInterval(() => {
            this.state.countdown--;
            if (this.state.countdown <= 0) {
                clearInterval(this._countdownInterval);
                this._countdownInterval = null;
                // Host triggers the begin on the server
                if (this.state.game && this.state.game.host_id === this.user.userId) {
                    this.beginGame();
                }
            }
        }, 1000);
    }

    async onGameStarted(payload) {
        // Update game info with task details from bus
        if (this.state.game) {
            this.state.game.task_name = payload.task_name;
            this.state.game.task_description = payload.task_description;
            this.state.game.start_time = payload.start_time;
            this.state.game.state = "running";
        }
        // Transition to playing (may already be there if host)
        this.state.phase = "playing";
        this.state.myFinished = false;
        this.state.checkResult = null;
    }

    onPlayerFinished(payload) {
        if (this.state.game) {
            const player = this.state.game.players.find(p => p.user_id === payload.user_id);
            if (player) {
                player.state = "finished";
                player.duration_ms = payload.duration_ms;
            }
        }
    }

    onGameOver(payload) {
        this.state.phase = "results";
        if (this.state.game) {
            this.state.game.state = "finished";
            this.state.game.winner_id = payload.winner_id;
            this.state.game.winner_name = payload.winner_name;
            this.state.game.results = payload.results;
        }
    }

    async createGame(name) {
        const result = await rpc("/odoo_speedrun/create_game", { name });
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        this.state.game = result;
        this.state.phase = "lobby";
        // Force bus channel refresh
        this.busService.forceUpdateChannels();
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
        // Host starts countdown immediately without waiting for bus
        this._startCountdown(3);
    }

    async beginGame() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/begin_game", { game_id: this.state.game.id });
        if (result && !result.error) {
            // Update game state locally (don't wait for bus)
            Object.assign(this.state.game, result);
            this.state.phase = "playing";
            this.state.myFinished = false;
            this.state.checkResult = null;
        }
    }

    async checkCompletion() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/check_completion", { game_id: this.state.game.id });
        this.state.checkResult = result;
        if (result.success) {
            this.state.myFinished = true;
            if (result.is_winner) {
                // Don't wait for bus — refresh game and go to results directly
                await this.refreshGame();
                this.state.game.results = this.state.game.players.map((p) => ({
                    user_id: p.user_id,
                    user_name: p.user_name,
                    state: p.state,
                    duration_ms: p.duration_ms,
                }));
                this.state.game.winner_id = this.user.userId;
                this.state.game.winner_name = this.user.name;
                this.state.phase = "results";
                this.notification.add("You win!", { type: "success" });
            } else {
                this.notification.add("Task completed!", { type: "success" });
            }
        } else if (result.error) {
            this.notification.add(result.error, { type: "warning" });
        }
    }

    async refreshGame() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/game_info", { game_id: this.state.game.id });
        if (result && !result.error) {
            this.state.game = result;
        }
    }

    playAgain() {
        this.state.game = null;
        this.state.phase = "lobby";
        this.state.myFinished = false;
        this.state.checkResult = null;
    }
}

registry.category("actions").add("odoo_speedrun.game_action", SpeedrunClientAction);
