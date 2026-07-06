/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

export class GameLobby extends Component {
    static template = "odoo_speedrun.GameLobby";
    static props = {
        game: { type: [Object, { value: null }] },
        stats: { type: [Object, { value: null }], optional: true },
        matchmaking: { type: Object, optional: true },
        onCreateGame: Function,
        onJoinGame: Function,
        onLeaveGame: Function,
        onStartGame: Function,
        onFindMatch: { type: Function, optional: true },
        onCancelMatch: { type: Function, optional: true },
        userId: Number,
    };

    setup() {
        this.formState = useState({
            gameName: "",
            joinCode: "",
            totalRounds: 3,
        });
    }

    onClickCreate() {
        this.props.onCreateGame(
            this.formState.gameName || null,
            this.formState.totalRounds,
        );
    }

    onClickJoin() {
        if (this.formState.joinCode.trim()) {
            this.props.onJoinGame(this.formState.joinCode.trim());
        }
    }

    onClickLeave() {
        this.props.onLeaveGame();
    }

    onClickStart() {
        this.props.onStartGame();
    }

    onClickFindMatch() {
        if (this.props.onFindMatch) this.props.onFindMatch();
    }

    onClickCancelMatch() {
        if (this.props.onCancelMatch) this.props.onCancelMatch();
    }

    get isHost() {
        return this.props.game && this.props.game.host_id === this.props.userId;
    }

    get canStart() {
        return this.isHost && this.props.game && this.props.game.players.length >= 1;
    }

    get isSearching() {
        return this.props.matchmaking && this.props.matchmaking.searching;
    }

    formatTime(ms) {
        if (!ms) return "-";
        const totalSeconds = Math.floor(ms / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        const millis = ms % 1000;
        return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
    }

    formatWait(seconds) {
        const m = Math.floor(seconds / 60);
        const s = seconds % 60;
        return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    }
}
