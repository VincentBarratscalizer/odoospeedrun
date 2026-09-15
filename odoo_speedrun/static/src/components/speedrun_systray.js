/** @odoo-module **/

import { Component, useState, onWillUnmount, onMounted } from "@odoo/owl";
import { registry } from "@web/core/registry";
import { useService } from "@web/core/utils/hooks";
import { useHotkey } from "@web/core/hotkeys/hotkey_hook";
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
            mode: "game", // "game" | "raid" (clan war raid)
            gameId: null,
            warId: null,
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

        // Global shortcut Alt+Shift+D: click the "Done!" button (check task completion).
        // "global" so it works from any screen, "bypassEditableProtection" so it
        // also fires while typing in an input (the player is doing the task).
        useHotkey(
            "alt+shift+d",
            () => {
                if (this.state.phase === "playing" && !this.state.myFinished) {
                    this.onClickCheck();
                }
            },
            { global: true, bypassEditableProtection: true }
        );

        // Global shortcut Alt+Shift+S: surrender the current round (score no points).
        useHotkey(
            "alt+shift+s",
            () => {
                if (this.state.phase === "playing" && !this.state.myFinished) {
                    this.onClickSurrender();
                }
            },
            { global: true, bypassEditableProtection: true }
        );

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
            if (this._systrayPoll) clearInterval(this._systrayPoll);
        });
    }

    async _checkActiveGame() {
        try {
            const result = await rpc("/odoo_speedrun/my_active_game", {});
            if (result && result.id) {
                this.state.gameId = result.id;
                if (result.state === "running") {
                    this._showPlaying(result);
                } else if (result.state === "countdown") {
                    this.state.visible = true;
                    this.state.phase = "countdown";
                    this.state.taskName = result.task_name || "";
                    this.state.currentRound = result.current_round;
                    this.state.totalRounds = result.total_rounds;
                    // Navigate to game screen if not already there
                    if (!document.querySelector(".o_speedrun_container")) {
                        this._goToGame();
                    }
                    this._runCountdownSounds(result.countdown_remaining || 5);
                } else if (result.state === "round_finished") {
                    this.state.visible = true;
                    this.state.phase = "round_finished";
                    this.state.currentRound = result.current_round;
                    this.state.totalRounds = result.total_rounds;
                } else if (result.state === "waiting") {
                    // Start polling for state changes
                    this._startSystrayPoll(result.id);
                }
            } else {
                // No active game — resume a clan war raid or a daily challenge.
                const shown = await this._checkActiveRaid();
                if (!shown) {
                    await this._checkActiveDaily();
                }
            }
        } catch {
            // Ignore errors silently
        }
    }

    async _checkActiveRaid() {
        try {
            const raid = await rpc("/odoo_speedrun/clan/active_raid", {});
            if (raid && raid.war_id) {
                this._showRaid(raid);
                return true;
            }
        } catch {
            // Ignore
        }
        return false;
    }

    async _checkActiveDaily() {
        try {
            const daily = await rpc("/odoo_speedrun/daily/today", {});
            if (daily && !daily.error && daily.my_status === "in_progress") {
                this._showDaily({
                    task_name: daily.task_name,
                    task_description: daily.task_description,
                    start_time: daily.my_start_time,
                });
                return true;
            }
        } catch {
            // Ignore
        }
        return false;
    }

    _showDaily(data) {
        this.state.visible = true;
        this.state.mode = "daily";
        this.state.phase = "playing";
        this.state.taskName = data.task_name || "";
        this.state.taskDescription = data.task_description || "";
        this.state.startTime = data.start_time;
        this.state.currentRound = 0;
        this.state.totalRounds = 0;
        this.state.myFinished = false;
        this.state.checking = false;
        this._startTimer();
    }

    _showRaid(data) {
        this.state.visible = true;
        this.state.mode = "raid";
        this.state.phase = "playing";
        this.state.warId = data.war_id;
        this.state.taskName = data.task_name || "";
        this.state.taskDescription = data.task_description || "";
        this.state.startTime = data.start_time;
        this.state.currentRound = 0;
        this.state.totalRounds = 0;
        this.state.myFinished = false;
        this.state.checking = false;
        this._startTimer();
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
                this.state.mode = "game";
                this.state.gameId = data.id || this.state.gameId;
                this._showPlaying(data);
                break;
            case "clan_raid_started":
                this._showRaid(data);
                break;
            case "daily_started":
                this._showDaily(data);
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
        this.state.mode = "game";
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

    _startSystrayPoll(gameId) {
        if (this._systrayPoll) clearInterval(this._systrayPoll);
        this._systrayPoll = setInterval(async () => {
            try {
                const result = await rpc("/odoo_speedrun/game_info", { game_id: gameId });
                if (result && !result.error && result.state !== "waiting") {
                    clearInterval(this._systrayPoll);
                    this._systrayPoll = null;
                    if (result.state === "countdown") {
                        this.state.visible = true;
                        this.state.phase = "countdown";
                        this.state.taskName = result.task_name || "";
                        this.state.currentRound = result.current_round;
                        this.state.totalRounds = result.total_rounds;
                        this.state.gameId = gameId;
                        if (!document.querySelector(".o_speedrun_container")) {
                            this._goToGame();
                        }
                        this._runCountdownSounds(result.countdown_remaining || 5);
                    } else if (result.state === "running") {
                        this.state.gameId = gameId;
                        this._showPlaying(result);
                        this.actionService.doAction("menu");
                    }
                }
            } catch {
                // Ignore
            }
        }, 2000);
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
        if (this.state.checking) return;
        if (this.state.mode === "raid") {
            return this._checkRaid();
        }
        if (this.state.mode === "daily") {
            return this._checkDaily();
        }
        if (!this.state.gameId) return;
        this.state.checking = true;
        try {
            const result = await rpc("/odoo_speedrun/check_completion", {
                game_id: this.state.gameId,
            });
            if (result.success) {
                playSound("taskComplete");
                this.state.myFinished = true;
                if (this._interval) clearInterval(this._interval);
                // Always redirect to game screen to see time + waiting screen
                this._goToGame();
            } else if (result.error) {
                playSound("error");
                this.notification.add(result.error, { type: "warning" });
            }
        } finally {
            this.state.checking = false;
        }
    }

    async _checkRaid() {
        if (!this.state.warId) return;
        this.state.checking = true;
        try {
            const result = await rpc("/odoo_speedrun/clan/war_task/check", {
                war_id: this.state.warId,
                kind: "raid",
            });
            if (result.success) {
                playSound("taskComplete");
                this.state.myFinished = true;
                if (this._interval) clearInterval(this._interval);
                this.notification.add("🛠️ Raid de guerre de clan terminé !", {
                    type: "success",
                });
                // Auto-hide the widget shortly after completion.
                setTimeout(() => {
                    if (this.state.mode === "raid") {
                        this.state.visible = false;
                        this.state.phase = null;
                    }
                }, 4000);
            } else if (result.error) {
                playSound("error");
                this.notification.add(result.error, { type: "warning" });
            }
        } finally {
            this.state.checking = false;
        }
    }

    async _checkDaily() {
        this.state.checking = true;
        try {
            const result = await rpc("/odoo_speedrun/daily/check", {});
            if (result.success) {
                playSound("taskComplete");
                this.state.myFinished = true;
                if (this._interval) clearInterval(this._interval);
                this.notification.add("🗓️ Daily challenge terminé !", { type: "success" });
                if (result.streak_reward) {
                    const r = result.streak_reward;
                    let label = r.type === "equipment"
                        ? `${r.icon} ${r.name} (${r.rarity})`
                        : `${r.icon} Coffre ${r.rarity}`;
                    if (r.coins) {
                        label += ` + ${r.coins} 💰`;
                    }
                    const prefix = r.is_new_cycle ? "🎁 Nouveau cycle ! Jour" : "🎁 Jour";
                    this.notification.add(`${prefix} ${r.day} : ${label}`, {
                        type: "success", sticky: true,
                    });
                }
                setTimeout(() => {
                    if (this.state.mode === "daily") {
                        this.state.visible = false;
                        this.state.phase = null;
                    }
                }, 4000);
            } else if (result.error) {
                playSound("error");
                this.notification.add(result.error, { type: "warning" });
            }
        } finally {
            this.state.checking = false;
        }
    }

    async onClickSurrender() {
        if (this.state.mode !== "game") return; // no surrender for raids / daily
        if (this.state.checking || !this.state.gameId) return;
        if (!window.confirm("Surrender this round? You will score no points.")) {
            return;
        }
        this.state.checking = true;
        try {
            const result = await rpc("/odoo_speedrun/surrender", {
                game_id: this.state.gameId,
            });
            if (result.success) {
                playSound("error");
                this.state.myFinished = true;
                if (this._interval) clearInterval(this._interval);
                // Redirect to game screen to see the waiting screen
                this._goToGame();
            } else if (result.error) {
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

    onClickSystray() {
        this._goToGame();
    }
}

export const speedrunSystrayItem = {
    Component: SpeedrunSystray,
};

registry.category("systray").add("odoo_speedrun.systray", speedrunSystrayItem, { sequence: 50 });
