/** @odoo-module **/

import { Component } from "@odoo/owl";

export class GameResults extends Component {
    static template = "odoo_speedrun.GameResults";
    static props = {
        game: Object,
        userId: Number,
        onPlayAgain: Function,
    };

    formatTime(ms) {
        if (!ms) return "DNF";
        const totalSeconds = Math.floor(ms / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        const millis = ms % 1000;
        return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
    }

    get results() {
        if (!this.props.game || !this.props.game.results) return [];
        return this.props.game.results;
    }

    get isWinner() {
        return this.props.game && this.props.game.winner_id === this.props.userId;
    }

    getRankEmoji(index) {
        const emojis = ["\u{1F947}", "\u{1F948}", "\u{1F949}"];
        return emojis[index] || `#${index + 1}`;
    }
}
