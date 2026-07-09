/** @odoo-module **/

import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";

export class GameTimer extends Component {
    static template = "odoo_speedrun.GameTimer";
    static props = {
        game: Object,
        myFinished: Boolean,
        checkResult: { type: [Object, { value: null }] },
        onCheckCompletion: Function,
        onSurrender: Function,
    };

    setup() {
        this.timerState = useState({
            elapsed: "00:00.000",
            elapsedMs: 0,
            checking: false,
            surrendering: false,
        });

        this._interval = null;

        onMounted(() => {
            this.startTimer();
        });

        onWillUnmount(() => {
            if (this._interval) {
                clearInterval(this._interval);
            }
        });
    }

    startTimer() {
        if (!this.props.game || !this.props.game.start_time) return;
        const startTime = new Date(this.props.game.start_time + "Z").getTime();

        this._interval = setInterval(() => {
            const now = Date.now();
            const elapsed = now - startTime;
            this.timerState.elapsedMs = elapsed;
            this.timerState.elapsed = this.formatTime(elapsed);
        }, 47); // ~21fps, smooth enough
    }

    formatTime(ms) {
        const totalSeconds = Math.floor(ms / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        const millis = ms % 1000;
        return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
    }

    async onClickCheck() {
        if (this.timerState.checking) return;
        this.timerState.checking = true;
        try {
            await this.props.onCheckCompletion();
        } finally {
            this.timerState.checking = false;
        }
    }

    async onClickSurrender() {
        if (this.timerState.checking || this.timerState.surrendering) return;
        if (!window.confirm("Surrender this round? You will score no points.")) {
            return;
        }
        this.timerState.surrendering = true;
        try {
            await this.props.onSurrender();
        } finally {
            this.timerState.surrendering = false;
        }
    }
}
