/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

const ELEMENT_ORDER = ["peripheral", "display", "badge", "module", "tech", "desk"];

// Mirrors ELEMENT_META (backend) + used to build the in-game rules page.
const ELEMENTS = [
    { key: "peripheral", icon: "🎮", label: "Vitesse",  passive: "Combo",      desc: "Chance de frapper une seconde fois dans le tour." },
    { key: "display",    icon: "🖥️", label: "Précision", passive: "Focus",      desc: "Coups critiques renforcés (+chance & +dégâts)." },
    { key: "badge",      icon: "🏅", label: "Bourreau",  passive: "Exécution",  desc: "Dégâts accrus sur les cibles à faible PV." },
    { key: "module",     icon: "🔮", label: "Arcane",    passive: "Vol de vie", desc: "Récupère des PV proportionnels aux dégâts infligés." },
    { key: "tech",       icon: "🔧", label: "Blindage",  passive: "Blocage",    desc: "Chance de bloquer une attaque et d'encaisser peu." },
    { key: "desk",       icon: "📋", label: "Épines",    passive: "Épines",     desc: "Renvoie une partie des dégâts subis à l'attaquant." },
];

const STAT_GUIDE = [
    { icon: "❤️", label: "PV",   desc: "Points de vie : quand ils tombent à 0, c'est perdu." },
    { icon: "⚔️", label: "ATQ",  desc: "Attaque : dégâts bruts infligés à chaque coup." },
    { icon: "🛡️", label: "DEF",  desc: "Défense : réduit les dégâts que vous subissez." },
    { icon: "⚡", label: "VIT",  desc: "Vitesse : agir plus souvent (ordre des tours + combos)." },
    { icon: "🎯", label: "CRIT", desc: "Critique : chance d'un coup critique (~×1.7 dégâts)." },
];

const STAT_META = {
    hp:   { icon: "❤️", label: "PV",  max: 600, color: "#e74c3c" },
    atk:  { icon: "⚔️", label: "ATQ", max: 120, color: "#e67e22" },
    def:  { icon: "🛡️", label: "DEF", max: 90,  color: "#3498db" },
    spd:  { icon: "⚡", label: "VIT", max: 90,  color: "#f1c40f" },
    crit: { icon: "🎯", label: "CRIT", max: 60, color: "#9b59b6" },
};

export class ArenaPanel extends Component {
    static template = "odoo_speedrun.ArenaPanel";
    static props = {
        onBack: Function,
        onFight: Function,   // (opponentProfileId) => Promise
    };

    setup() {
        this.notification = useService("notification");
        this.STAT_META = STAT_META;
        this.STAT_GUIDE = STAT_GUIDE;
        this.statOrder = ["hp", "atk", "def", "spd", "crit"];
        this.elementGuide = ELEMENTS.map((e, i) => ({
            ...e,
            strongVs: [ELEMENTS[(i + 1) % 6], ELEMENTS[(i + 2) % 6]],
            weakVs: [ELEMENTS[(i + 4) % 6], ELEMENTS[(i + 5) % 6]],
        }));
        this.state = useState({
            loading: true,
            tab: "opponents",   // opponents | ranking
            me: null,
            opponents: [],
            leaderboard: [],
            fightingId: null,
        });
        onWillStart(() => this.loadArena());
    }

    async loadArena() {
        this.state.loading = true;
        try {
            const data = await rpc("/odoo_speedrun/arena_opponents", {});
            this.state.me = data.me;
            this.state.opponents = data.opponents || [];
        } catch {
            this.notification.add("Impossible de charger l'arène.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async openRanking() {
        this.state.tab = "ranking";
        if (!this.state.leaderboard.length) {
            try {
                this.state.leaderboard = await rpc("/odoo_speedrun/arena_leaderboard", {});
            } catch {
                this.state.leaderboard = [];
            }
        }
    }

    statPercent(value, key) {
        return Math.min(100, Math.round((value / STAT_META[key].max) * 100));
    }

    powerVerdict(opp) {
        if (!this.state.me) return "even";
        const r = opp.power / Math.max(1, this.state.me.power);
        if (r >= 1.15) return "strong";
        if (r <= 0.85) return "weak";
        return "even";
    }

    verdictLabel(v) {
        return { strong: "Coriace", weak: "Facile", even: "Équilibré" }[v] || "";
    }

    /** Type matchup of MY element attacking the opponent's element. */
    typeVerdict(opp) {
        const a = this.state.me?.element;
        const b = opp.element;
        if (!a || !b) return "neutral";
        const i = ELEMENT_ORDER.indexOf(a);
        const j = ELEMENT_ORDER.indexOf(b);
        if (i < 0 || j < 0) return "neutral";
        const diff = (((j - i) % 6) + 6) % 6;
        if (diff === 1 || diff === 2) return "advantage";
        if (diff === 4 || diff === 5) return "disadvantage";
        return "neutral";
    }

    typeIcon(v) {
        return { advantage: "🔺", disadvantage: "🔻", neutral: "" }[v] || "";
    }

    get quota() {
        return this.state.me?.arena_quota || { used: 0, quota: 0, remaining: 0 };
    }

    async fight(opp) {
        if (this.state.fightingId) return;
        if (this.quota.remaining <= 0) {
            this.notification.add("Quota de combats journalier atteint. Revenez demain !", { type: "warning" });
            return;
        }
        this.state.fightingId = opp.profile_id;
        try {
            await this.props.onFight(opp.profile_id);
        } finally {
            this.state.fightingId = null;
        }
    }
}
