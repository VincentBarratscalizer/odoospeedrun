/** @odoo-module **/

import { Component, useState, onWillUnmount, onWillStart } from "@odoo/owl";
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
        this.actionService = useService("action");
        this.user = user;

        this.state = useState({
            // lobby | countdown | playing | round_results | final_results
            phase: "lobby",
            game: null,
            countdown: 0,
            myFinished: false,
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
        });
    }

    async _restoreActiveGame() {
        try {
            const result = await rpc("/odoo_speedrun/my_active_game", {});
            if (result && result.id) {
                this.state.game = result;
                this.busService.forceUpdateChannels();
                // Determine the correct phase based on game state
                switch (result.state) {
                    case "waiting":
                        this.state.phase = "lobby";
                        break;
                    case "countdown":
                        this.state.phase = "countdown";
                        break;
                    case "running":
                        this.state.phase = "playing";
                        break;
                    case "round_finished":
                        this.state.phase = "round_results";
                        break;
                    case "finished":
                        this.state.phase = "final_results";
                        break;
                }
            }
        } catch {
            // No active game, stay in lobby
        }
    }

    onBusNotification({ detail: notifications }) {
        for (const { type, payload } of notifications) {
            switch (type) {
                case "speedrun/player_joined":
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
        this._startCountdown(payload.countdown_seconds);
    }

    _startCountdown(seconds) {
        if (this._countdownInterval) clearInterval(this._countdownInterval);
        this.state.phase = "countdown";
        this.state.countdown = seconds;
        this._countdownInterval = setInterval(() => {
            this.state.countdown--;
            if (this.state.countdown <= 0) {
                clearInterval(this._countdownInterval);
                this._countdownInterval = null;
                if (this.state.game && this.state.game.host_id === this.user.userId) {
                    this.beginGame();
                }
            }
        }, 1000);
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
        this._startCountdown(3);
    }

    async nextRound() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/next_round", { game_id: this.state.game.id });
        if (result.error) {
            this.notification.add(result.error, { type: "danger" });
            return;
        }
        this._startCountdown(3);
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
            // Navigate to Odoo home so user can work on the task
            // The systray widget will show the timer
            this.actionService.doAction("menu");
        }
    }

    async checkCompletion() {
        if (!this.state.game) return;
        const result = await rpc("/odoo_speedrun/check_completion", { game_id: this.state.game.id });
        this.state.checkResult = result;
        if (result.success) {
            this.state.myFinished = true;
            if (result.is_round_winner && result.game_info) {
                // Round winner — update game info and go to results
                const gameInfo = result.game_info;
                for (const key of Object.keys(gameInfo)) {
                    this.state.game[key] = gameInfo[key];
                }
                if (this.state.game.state === "finished") {
                    this.state.phase = "final_results";
                } else {
                    this.state.phase = "round_results";
                }
            } else {
                this.notification.add(
                    `+${result.points} point${result.points !== 1 ? 's' : ''}! Rank #${result.rank}`,
                    { type: "success" }
                );
            }
        } else if (result.error) {
            this.notification.add(result.error, { type: "warning" });
        }
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

    playAgain() {
        this.state.game = null;
        this.state.phase = "lobby";
        this.state.myFinished = false;
        this.state.checkResult = null;
    }
}

registry.category("actions").add("odoo_speedrun.game_action", SpeedrunClientAction);
