/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

const TABS = [
    { key: "elo", icon: "📊", label: "ELO", unit: "ELO" },
    { key: "gear", icon: "⚔️", label: "Équipement", unit: "GS" },
    { key: "arena", icon: "🥊", label: "Arène", unit: "Rating" },
    { key: "tasks", icon: "⏱️", label: "Tâches", unit: "ELO" },
];

export class LeaderboardPanel extends Component {
    static template = "odoo_speedrun.LeaderboardPanel";
    static props = {
        onBack: Function,
    };

    setup() {
        this.notification = useService("notification");
        this.tabs = TABS;
        this.state = useState({
            loading: true,
            kind: "elo",
            rows: [],
            tasks: [],
            selectedTaskId: null,
        });
        onWillStart(() => this.load("elo"));
    }

    get unit() {
        return (this.tabs.find((t) => t.key === this.state.kind) || {}).unit || "";
    }

    async load(kind, taskId = null) {
        this.state.loading = true;
        this.state.kind = kind;
        try {
            const data = await rpc("/odoo_speedrun/leaderboard_data", {
                kind,
                task_id: taskId,
            });
            this.state.rows = data.rows || [];
            if (kind === "tasks") {
                this.state.tasks = data.tasks || [];
                this.state.selectedTaskId = data.selected_task_id || null;
            }
        } catch {
            this.notification.add("Impossible de charger le classement.", { type: "danger" });
            this.state.rows = [];
        } finally {
            this.state.loading = false;
        }
    }

    switchTab(kind) {
        if (kind !== this.state.kind) {
            this.load(kind);
        }
    }

    onSelectTask(ev) {
        this.load("tasks", parseInt(ev.target.value, 10));
    }

    medal(index) {
        return ["🥇", "🥈", "🥉"][index] || `${index + 1}`;
    }

    formatTime(ms) {
        if (!ms) return "—";
        const totalSeconds = Math.floor(ms / 1000);
        const minutes = Math.floor(totalSeconds / 60);
        const seconds = totalSeconds % 60;
        const millis = ms % 1000;
        return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}.${String(millis).padStart(3, "0")}`;
    }
}
