/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

const TABS = [
    { key: "elo", icon: "📊", label: "ELO", unit: "ELO" },
    { key: "gear", icon: "⚔️", label: "Équipement", unit: "GS" },
    { key: "arena", icon: "🥊", label: "Arène", unit: "Rating" },
    { key: "clans", icon: "🛡️", label: "Clans", unit: "ELO" },
    { key: "tasks", icon: "⏱️", label: "Tâches", unit: "ELO" },
    { key: "perf", icon: "⏲️", label: "Perf tâche", unit: "/100" },
    { key: "domains", icon: "🎯", label: "Domaines", unit: "/100" },
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
            categories: [],
            selectedCategoryId: null,
        });
        onWillStart(() => this.load("elo"));
    }

    get unit() {
        return (this.tabs.find((t) => t.key === this.state.kind) || {}).unit || "";
    }

    async load(kind, id = null) {
        this.state.loading = true;
        this.state.kind = kind;
        try {
            const params = { kind };
            if (kind === "domains") {
                params.category_id = id;
            } else {
                params.task_id = id;
            }
            const data = await rpc("/odoo_speedrun/leaderboard_data", params);
            this.state.rows = data.rows || [];
            if (kind === "tasks" || kind === "perf") {
                this.state.tasks = data.tasks || [];
                this.state.selectedTaskId = data.selected_task_id || null;
            }
            if (kind === "domains") {
                this.state.categories = data.categories || [];
                this.state.selectedCategoryId = data.selected_category_id || null;
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
        this.load(this.state.kind, parseInt(ev.target.value, 10));
    }

    onSelectCategory(ev) {
        this.load("domains", parseInt(ev.target.value, 10));
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
