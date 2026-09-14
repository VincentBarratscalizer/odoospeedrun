/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { playSound } from "../services/sound_service";

export class GameTimeAttack extends Component {
    static template = "odoo_speedrun.GameTimeAttack";
    static props = {
        game: Object,
        userId: Number,
        isHost: Boolean,
        onEnd: Function,
    };

    setup() {
        const g = this.props.game;

        // Compute remaining time from the server's start_time
        let elapsed = 0;
        if (g.start_time) {
            // start_time arrives as "YYYY-MM-DD HH:MM:SS" (UTC) from the server
            const startMs = new Date(g.start_time.replace(" ", "T") + "Z").getTime();
            elapsed = Math.floor((Date.now() - startMs) / 1000);
        }
        const timeLeft = Math.max(0, (g.ta_duration || 120) - elapsed);

        this.localState = useState({
            timeLeft,
            currentTaskName: g.ta_current_task_name || "",
            currentTaskDesc: g.ta_current_task_description || "",
            checkResult: null,
            checking: false,
        });

        onWillStart(() => {
            if (timeLeft > 0) this._startTimer();
        });

        onWillUnmount(() => this._stopTimer());
    }

    _startTimer() {
        this._timerInterval = setInterval(() => {
            if (this.localState.timeLeft > 0) {
                this.localState.timeLeft--;
            }
            if (this.localState.timeLeft <= 0) {
                this._stopTimer();
                if (this.props.isHost) {
                    this.props.onEnd();
                }
            }
        }, 1000);
    }

    _stopTimer() {
        if (this._timerInterval) {
            clearInterval(this._timerInterval);
            this._timerInterval = null;
        }
    }

    async onCheckCompletion() {
        if (this.localState.checking || this.localState.timeLeft <= 0) return;
        this.localState.checking = true;
        this.localState.checkResult = null;
        try {
            const result = await rpc("/odoo_speedrun/time_attack/check", {
                game_id: this.props.game.id,
            });
            this.localState.checkResult = result;
            if (result.success) {
                playSound("taskComplete");
                this.localState.currentTaskName = result.next_task_name || "";
                this.localState.currentTaskDesc = result.next_task_description || "";
            } else {
                playSound("error");
            }
        } catch {
            this.localState.checkResult = { success: false, error: "Connection error." };
            playSound("error");
        } finally {
            this.localState.checking = false;
        }
    }

    /** Called by the parent's bus event handler to update leaderboard counts. */
    onScoreUpdate(payload) {
        // Parent mutates props.game.players directly (reactive via useState)
        // so this method is a no-op — the template reacts automatically.
        // We only need to update current task if it's for ourselves.
        if (payload.user_id === this.props.userId) {
            this.localState.currentTaskName = payload.next_task_name || "";
            this.localState.currentTaskDesc = payload.next_task_description || "";
            this.localState.checkResult = null;
        }
    }

    get timeDisplay() {
        const t = this.localState.timeLeft;
        const m = Math.floor(t / 60);
        const s = t % 60;
        return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    }

    get timerClass() {
        const t = this.localState.timeLeft;
        if (t <= 10) return "text-danger";
        if (t <= 30) return "text-warning";
        return "text-primary";
    }

    get timerStyle() {
        const t = this.localState.timeLeft;
        if (t <= 10) return "background: #fff5f5;";
        if (t <= 30) return "background: #fffbf0;";
        return "";
    }

    get sortedPlayers() {
        return [...(this.props.game.players || [])].sort(
            (a, b) => (b.ta_completed_count || 0) - (a.ta_completed_count || 0),
        );
    }

    get myCount() {
        const me = (this.props.game.players || []).find(
            (p) => p.user_id === this.props.userId,
        );
        return me ? me.ta_completed_count || 0 : 0;
    }

    get isTimeUp() {
        return this.localState.timeLeft <= 0;
    }
}
