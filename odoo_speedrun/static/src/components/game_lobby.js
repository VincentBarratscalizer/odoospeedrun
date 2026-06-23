/** @odoo-module **/

import { Component, useState } from "@odoo/owl";

export class GameLobby extends Component {
    static template = "odoo_speedrun.GameLobby";
    static props = {
        game: { type: [Object, { value: null }] },
        onCreateGame: Function,
        onJoinGame: Function,
        onLeaveGame: Function,
        onStartGame: Function,
        userId: Number,
    };

    setup() {
        this.formState = useState({
            gameName: "",
            joinCode: "",
        });
    }

    onClickCreate() {
        this.props.onCreateGame(this.formState.gameName || null);
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

    get isHost() {
        return this.props.game && this.props.game.host_id === this.props.userId;
    }

    get canStart() {
        return this.isHost && this.props.game && this.props.game.players.length >= 1;
    }
}
