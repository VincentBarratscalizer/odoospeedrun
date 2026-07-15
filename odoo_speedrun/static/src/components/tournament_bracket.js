/** @odoo-module **/

import { Component } from "@odoo/owl";

export class TournamentBracket extends Component {
    static template = "odoo_speedrun.TournamentBracket";
    static props = {
        bracket: { type: [Object, { value: null }] },
        userId: Number,
        onPlayMatch: Function,
    };

    stateLabel(state) {
        return {
            waiting: "Waiting",
            ready: "Ready",
            running: "Live",
            done: "Done",
            bye: "Bye",
        }[state] || state;
    }

    stateClass(state) {
        return {
            waiting: "text-bg-light border",
            ready: "text-bg-primary",
            running: "text-bg-warning",
            done: "text-bg-success",
            bye: "text-bg-secondary",
        }[state] || "text-bg-light";
    }

    onPlay(matchId) {
        this.props.onPlayMatch(matchId);
    }
}
