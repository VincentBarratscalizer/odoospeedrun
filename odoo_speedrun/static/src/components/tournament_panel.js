/** @odoo-module **/

import { Component, useState } from "@odoo/owl";
import { TournamentBracket } from "./tournament_bracket";

export class TournamentPanel extends Component {
    static template = "odoo_speedrun.TournamentPanel";
    static components = { TournamentBracket };
    static props = {
        tournaments: { type: [Array, { value: null }], optional: true },
        tournament: { type: [Object, { value: null }], optional: true },
        userId: Number,
        onBack: Function,
        onOpen: Function,
        onCreate: Function,
        onRegister: Function,
        onUnregister: Function,
        onCloseRegistration: Function,
        onReopenRegistration: Function,
        onAutoSeed: Function,
        onMoveSeed: Function,
        onStart: Function,
        onPlayMatch: Function,
        onRefresh: { type: Function, optional: true },
        onCancel: { type: Function, optional: true },
    };

    setup() {
        this.formState = useState({
            name: "",
            matchBestOf: "3",
            seedingMethod: "elo",
            showCreate: false,
        });
    }

    get t() {
        return this.props.tournament;
    }

    get canSeed() {
        return this.t && this.t.is_organizer && ["registration", "seeding"].includes(this.t.state);
    }

    stateBadge(state) {
        return {
            registration: "text-bg-info",
            seeding: "text-bg-warning",
            running: "text-bg-primary",
            finished: "text-bg-success",
        }[state] || "text-bg-light";
    }

    stateLabel(state) {
        return {
            registration: "Registration Open",
            seeding: "Seeding",
            running: "Running",
            finished: "Finished",
        }[state] || state;
    }

    seedStateBadge(state) {
        return {
            registered: "text-bg-light border",
            active: "text-bg-primary",
            eliminated: "text-bg-secondary",
            champion: "text-bg-success",
        }[state] || "text-bg-light";
    }

    onClickCreate() {
        this.props.onCreate({
            name: this.formState.name || null,
            match_best_of: this.formState.matchBestOf,
            seeding_method: this.formState.seedingMethod,
        });
        this.formState.showCreate = false;
        this.formState.name = "";
    }
}
