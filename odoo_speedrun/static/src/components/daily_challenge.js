/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { useService } from "@web/core/utils/hooks";
import { rpc } from "@web/core/network/rpc";
import { user } from "@web/core/user";

export class DailyChallenge extends Component {
    static template = "odoo_speedrun.DailyChallenge";
    static props = {};

    setup() {
        this.actionService = useService("action");
        this.notification = useService("notification");
        this.user = user;

        this.state = useState({
            // loading | not_started | in_progress | completed | error
            phase: "loading",
            daily: null,
            elapsed: "00:00.000",
            checking: false,
            showLeaderboard: false,
        });

        this._timerInterval = null;

        onWillStart(async () => await this._load());
        onWillUnmount(() => this._stopTimer());
    }

    // ------------------------------------------------------------------
    // Data loading
    // ------------------------------------------------------------------

    async _load() {
        try {
            const data = await rpc("/odoo_speedrun/daily/today", {});
            if (!data || data.error) {
                this.state.phase = "error";
                return;
            }
            this.state.daily = data;
            this._applyStatus(data);
        } catch {
            this.state.phase = "error";
        }
    }

    _applyStatus(data) {
        switch (data.my_status) {
            case "completed":
                this._stopTimer();
                this.state.phase = "completed";
                break;
            case "in_progress":
                this.state.phase = "in_progress";
                this._startTimer(data.my_start_time);
                break;
            default:
                this.state.phase = "not_started";
        }
    }

    // ------------------------------------------------------------------
    // Actions
    // ------------------------------------------------------------------

    async onClickStart() {
        try {
            const data = await rpc("/odoo_speedrun/daily/start", {});
            if (data.error) {
                this.notification.add(data.error, { type: "warning" });
                return;
            }
            this.state.daily = data;
            this._applyStatus(data);
            // Navigate to Odoo home so the user can do the task
            this.actionService.doAction("menu");
        } catch (e) {
            this.notification.add("Could not start the daily challenge.", { type: "danger" });
        }
    }

    async onClickCheck() {
        if (this.state.checking) return;
        this.state.checking = true;
        try {
            const data = await rpc("/odoo_speedrun/daily/check", {});
            if (data.error) {
                this.notification.add(data.error, { type: "warning" });
                return;
            }
            if (data.success || data.already_completed) {
                this._stopTimer();
                this.state.daily = data;
                this.state.phase = "completed";
                if (data.success) {
                    this.notification.add("🏆 Daily challenge completed!", { type: "success", sticky: false });
                }
            } else {
                this.notification.add(data.error || "Task not completed yet. Keep going!", { type: "warning" });
            }
        } catch {
            this.notification.add("Could not verify the task.", { type: "danger" });
        } finally {
            this.state.checking = false;
        }
    }

    toggleLeaderboard() {
        this.state.showLeaderboard = !this.state.showLeaderboard;
    }

    // ------------------------------------------------------------------
    // Timer
    // ------------------------------------------------------------------

    _startTimer(startTimeStr) {
        this._stopTimer();
        if (!startTimeStr) return;
        const startMs = new Date(startTimeStr + (startTimeStr.endsWith("Z") ? "" : "Z")).getTime();
        this._timerInterval = setInterval(() => {
            const elapsed = Date.now() - startMs;
            this.state.elapsed = this._formatTime(elapsed);
        }, 47);
    }

    _stopTimer() {
        if (this._timerInterval) {
            clearInterval(this._timerInterval);
            this._timerInterval = null;
        }
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------

    _formatTime(ms) {
        if (!ms || ms < 0) return "00:00.000";
        const totalSeconds = Math.floor(ms / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        const millis = ms % 1000;
        return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
    }

    formatTime(ms) {
        return this._formatTime(ms);
    }

    getRankEmoji(rank) {
        const emojis = { 1: "🥇", 2: "🥈", 3: "🥉" };
        return emojis[rank] || `#${rank}`;
    }

    get myRankDisplay() {
        const rank = this.state.daily?.my_rank;
        if (!rank) return "";
        return this.getRankEmoji(rank);
    }
}
