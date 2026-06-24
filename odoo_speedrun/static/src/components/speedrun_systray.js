/** @odoo-module **/

import { Component, useState, onWillUnmount, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";
import { playSound, playCountdownBeep } from "../services/sound_service";

export class SpeedrunSystray extends Component {
    static template = "odoo_speedrun.SpeedrunSystray";
    static props = {};

    setup() {
        this.busService = useService("bus_service");
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.user = user;

        this.state = useState({
            visible: false,
            gameId: null,
            taskName: "",
            taskDescription: "",
            startTime: null,
            elapsed: "00:00",
            currentRound: 0,
            totalRounds: 0,
            myFinished: false,
            checking: false,
            phase: null, // "playing" | "round_finished"
        });

        this._interval = null;
        this._onBusNotification = this.onBusNotification.bind(this);
        this.busService.addEventListener("notification", this._onBusNotification);

        // Listen for direct events from SpeedrunClientAction (same tab)
        this._onSpeedrunUpdate = this.onSpeedrunUpdate.bind(this);
        window.addEventListener("speedrun-update", this._onSpeedrunUpdate);

        onMounted(() => {
            this._checkActiveGame();
        });

        onWillUnmount(() => {
            this.busService.removeEventListener("notification", this._onBusNotification);
            window.removeEventListener("speedrun-update", this._onSpeedrunUpdate);
            if (this._interval) clearInterval(this._interval);
            if (this._countdownSoundInterval) clearInterval(this._countdownSoundInterval);
        });
    }

    async _checkActiveGame() {
        try {
            const result = await rpc("/odoo_speedrun/my_active_game", {});
            if (result && result.id) {
                this.state.gameId = result.id;
                if (result.state === "running") {
                    this._showPlaying(result);
                } else if (result.state === "round_finished") {
                    this.state.visible = true;
                    this.state.phase = "round_finished";
                    this.state.currentRound = result.current_round;
                    this.state.totalRounds = result.total_rounds;
                }
            }
        } catch {
            // Ignore errors silently
        }
    }

    onSpeedrunUpdate(ev) {
        const { type, data } = ev.detail;
        switch (type) {
            case "countdown":
                this.state.visible = true;
                this.state.phase = "countdown";
                this.state.taskName = data.task_name || "";
                this.state.taskDescription = data.task_description || "";
                this.state.currentRound = data.current_round;
                this.state.totalRounds = data.total_rounds;
                this.state.gameId = data.game_id || this.state.gameId;
                break;
            case "game_started":
                this.state.gameId = data.id || this.state.gameId;
                this._showPlaying(data);
                break;
            case "round_over":
                if (this._interval) clearInterval(this._interval);
                this.state.phase = "round_finished";
                this.state.currentRound = data.current_round;
                this.state.totalRounds = data.total_rounds;
                break;
            case "game_over":
                if (this._interval) clearInterval(this._interval);
                this.state.visible = false;
                this.state.phase = null;
                break;
        }
    }

    _showPlaying(data) {
        this.state.visible = true;
        this.state.phase = "playing";
        this.state.taskName = data.task_name || "";
        this.state.taskDescription = data.task_description || "";
        this.state.startTime = data.start_time;
        this.state.currentRound = data.current_round;
        this.state.totalRounds = data.total_rounds;
        this.state.myFinished = false;
        this.state.checking = false;
        this._startTimer();
    }

    _startTimer() {
        if (this._interval) clearInterval(this._interval);
        if (!this.state.startTime) return;
        const startMs = new Date(this.state.startTime + "Z").getTime();
        this._interval = setInterval(() => {
            const elapsed = Date.now() - startMs;
            const totalSec = Math.floor(elapsed / 1000);
            const min = Math.floor(totalSec / 60);
            const sec = totalSec % 60;
            this.state.elapsed = `${String(min).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
        }, 250);
    }

    onBusNotification({ detail: notifications }) {
        for (const { type, payload } of notifications) {
            switch (type) {
                case "speedrun/countdown_start":
                    this.state.visible = true;
                    this.state.phase = "countdown";
                    this.state.taskName = payload.task_name || "";
                    this.state.taskDescription = payload.task_description || "";
                    this.state.currentRound = payload.current_round;
                    this.state.totalRounds = payload.total_rounds;
                    this.state.gameId = payload.game_id || this.state.gameId;
                    // Only navigate if game screen is NOT already open
                    // (to avoid destroying an active countdown)
                    if (!document.querySelector(".o_speedrun_container")) {
                        this._goToGame();
                    }
                    this._runCountdownSounds(payload.countdown_seconds || 5);
                    break;
                case "speedrun/game_started":
                    this.state.gameId = payload.game_id;
                    this._showPlaying(payload);
                    // Navigate to home so user can do the task
                    this.actionService.doAction("menu");
                    break;
                case "speedrun/player_finished":
                    if (payload.user_id === this.user.userId) {
                        this.state.myFinished = true;
                    }
                    break;
                case "speedrun/round_over":
                    if (this._interval) clearInterval(this._interval);
                    playSound("roundOver");
                    this.state.phase = "round_finished";
                    this.state.currentRound = payload.current_round;
                    this.state.totalRounds = payload.total_rounds;
                    this._goToGame();
                    break;
                case "speedrun/game_over":
                    if (this._interval) clearInterval(this._interval);
                    playSound("gameOver");
                    this.state.visible = false;
                    this.state.phase = null;
                    this._goToGame();
                    break;
            }
        }
    }

    _runCountdownSounds(seconds) {
        // Play countdown beeps in sync (for non-host players)
        if (this._countdownSoundInterval) clearInterval(this._countdownSoundInterval);
        let remaining = seconds;
        playCountdownBeep(remaining);
        this._countdownSoundInterval = setInterval(() => {
            remaining--;
            playCountdownBeep(remaining);
            if (remaining <= 0) {
                clearInterval(this._countdownSoundInterval);
                this._countdownSoundInterval = null;
            }
        }, 1000);
    }

    async onClickCheck() {
        if (this.state.checking || !this.state.gameId) return;
        this.state.checking = true;
        try {
            const result = await rpc("/odoo_speedrun/check_completion", {
                game_id: this.state.gameId,
            });
            if (result.success) {
                playSound("taskComplete");
                this.state.myFinished = true;
                if (result.is_round_winner) {
                    if (this._interval) clearInterval(this._interval);
                    playSound("roundOver");
                    this._goToGame();
                } else {
                    this.notification.add(
                        `+${result.points} pts! Rank #${result.rank}`,
                        { type: "success" }
                    );
                }
            } else if (result.error) {
                playSound("error");
                this.notification.add(result.error, { type: "warning" });
            }
        } finally {
            this.state.checking = false;
        }
    }

    _goToGame() {
        this.actionService.doAction("odoo_speedrun.speedrun_client_action", {
            clearBreadcrumbs: true,
        });
    }

    onClickGoToGame() {
        this._goToGame();
    }
}

export const speedrunSystrayItem = {
    Component: SpeedrunSystray,
};

registry.category("systray").add("odoo_speedrun.systray", speedrunSystrayItem, { sequence: 50 });
