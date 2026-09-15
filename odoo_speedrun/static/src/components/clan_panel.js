/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { user } from "@web/core/user";
import { BattleArena } from "./battle_arena";
import { playSound } from "../services/sound_service";

export class ClanPanel extends Component {
    static template = "odoo_speedrun.ClanPanel";
    static components = { BattleArena };
    static props = {
        onBack: Function,
    };

    setup() {
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.user = user;

        this.state = useState({
            loading: true,
            clan: null,          // my clan info (or null)
            clans: [],           // browsable clans when I have none
            // create form
            form: { name: "", tag: "", emblem: "🛡️", motto: "" },
            // declare-war UI
            showDeclare: false,
            targets: [],
            // war task timers
            raidElapsed: "00:00.000",
            warRemaining: "",
            blitzCountdown: "",
            checking: false,
            fighting: false,
            battleReplay: null,
        });
        this._timers = {};
        this._pollInterval = null;

        onWillStart(() => this.load());
        onWillUnmount(() => this._clearTimers());
    }

    // ------------------------------------------------------------------
    // Data
    // ------------------------------------------------------------------
    async load() {
        this.state.loading = true;
        try {
            const data = await rpc("/odoo_speedrun/clan/my", {});
            this.state.clan = data.clan;
            this.state.clans = data.clans || [];
            this._syncWarTimers();
        } catch {
            this.notification.add("Impossible de charger les clans.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async reload() {
        try {
            const data = await rpc("/odoo_speedrun/clan/my", {});
            this.state.clan = data.clan;
            this.state.clans = data.clans || [];
            this._syncWarTimers();
        } catch {
            // ignore
        }
    }

    _apply(result) {
        if (result.error) {
            this.notification.add(result.error, { type: "warning" });
            return false;
        }
        if (result.clan !== undefined) {
            this.state.clan = result.clan;
            this._syncWarTimers();
        }
        return true;
    }

    // ------------------------------------------------------------------
    // Clan management
    // ------------------------------------------------------------------
    async createClan() {
        const f = this.state.form;
        const result = await rpc("/odoo_speedrun/clan/create", {
            name: f.name, tag: f.tag, emblem: f.emblem, motto: f.motto,
        });
        if (this._apply(result)) {
            this.notification.add("🛡️ Clan créé !", { type: "success" });
        }
    }

    async joinClan(clanId) {
        const result = await rpc("/odoo_speedrun/clan/join", { clan_id: clanId });
        if (this._apply(result)) {
            this.notification.add("Bienvenue dans le clan !", { type: "success" });
        }
    }

    async leaveClan() {
        const result = await rpc("/odoo_speedrun/clan/leave", {});
        if (result.error) {
            this.notification.add(result.error, { type: "warning" });
            return;
        }
        await this.load();
    }

    async disbandClan() {
        const result = await rpc("/odoo_speedrun/clan/disband", {});
        if (result.error) {
            this.notification.add(result.error, { type: "warning" });
            return;
        }
        await this.load();
    }

    async kickMember(profileId) {
        this._apply(await rpc("/odoo_speedrun/clan/kick", { profile_id: profileId }));
    }

    async transferLead(profileId) {
        this._apply(await rpc("/odoo_speedrun/clan/transfer_lead", { profile_id: profileId }));
    }

    // ------------------------------------------------------------------
    // Wars
    // ------------------------------------------------------------------
    async openDeclare() {
        this.state.showDeclare = true;
        try {
            const clans = await rpc("/odoo_speedrun/clan/list", {});
            this.state.targets = (clans || []).filter((c) => c.id !== this.state.clan.id);
        } catch {
            this.state.targets = [];
        }
    }

    closeDeclare() {
        this.state.showDeclare = false;
    }

    async declareWar(targetId) {
        const result = await rpc("/odoo_speedrun/clan/declare_war", { target_clan_id: targetId });
        if (this._apply(result)) {
            this.state.showDeclare = false;
            this.notification.add("⚔️ Guerre déclarée ! En attente de l'adversaire.", { type: "success" });
        }
    }

    async acceptWar() {
        const result = await rpc("/odoo_speedrun/clan/accept_war", { war_id: this.state.clan.war.id });
        if (this._apply(result)) {
            this.notification.add("⚔️ La guerre commence !", { type: "success" });
        }
    }

    async declineWar() {
        this._apply(await rpc("/odoo_speedrun/clan/decline_war", { war_id: this.state.clan.war.id }));
    }

    async cancelWar() {
        this._apply(await rpc("/odoo_speedrun/clan/cancel_war", { war_id: this.state.clan.war.id }));
    }

    async startTask(kind) {
        const result = await rpc("/odoo_speedrun/clan/war_task/start", {
            war_id: this.state.clan.war.id, kind,
        });
        if (result.error) {
            this.notification.add(result.error, { type: "warning" });
            return;
        }
        // Refresh the embedded war payload.
        await this.reload();
        // Show the floating systray widget (like a standard game task) so the
        // player can work anywhere in Odoo and validate from the systray.
        const war = this.state.clan && this.state.clan.war;
        window.dispatchEvent(new CustomEvent("speedrun-update", {
            detail: {
                type: "clan_raid_started",
                data: {
                    war_id: this.state.clan.war.id,
                    task_name: war && war.raid_task ? war.raid_task.name : "",
                    task_description: war && war.raid_task ? war.raid_task.description : "",
                    start_time: war && war.my_raid ? war.my_raid.start_time : null,
                },
            },
        }));
        // Jump to Odoo home to work on the task.
        this.actionService.doAction("menu");
    }

    async checkTask(kind) {
        if (this.state.checking) return;
        this.state.checking = true;
        try {
            const result = await rpc("/odoo_speedrun/clan/war_task/check", {
                war_id: this.state.clan.war.id, kind,
            });
            if (result.error) {
                this.notification.add(result.error, { type: "warning" });
                return;
            }
            if (result.success) {
                this.notification.add(
                    kind === "raid" ? "🛠️ Raid réussi !" : "⚡ Blitz réussi !",
                    { type: "success" });
            }
            await this.reload();
        } finally {
            this.state.checking = false;
        }
    }

    // ------------------------------------------------------------------
    // Arena — trigger my single attack (with the battle visual)
    // ------------------------------------------------------------------
    async fightArena() {
        if (this.state.fighting) return;
        this.state.fighting = true;
        try {
            const result = await rpc("/odoo_speedrun/clan/war/fight", {
                war_id: this.state.clan.war.id,
            });
            if (result.error) {
                this.notification.add(result.error, { type: "warning" });
                return;
            }
            playSound("playerJoined");
            this.state.battleReplay = result;
        } finally {
            this.state.fighting = false;
        }
    }

    async onBattleDone() {
        this.state.battleReplay = null;
        await this.reload();
    }

    // ------------------------------------------------------------------
    // Timers
    // ------------------------------------------------------------------
    _syncWarTimers() {
        this._clearTimers();
        const war = this.state.clan && this.state.clan.war;
        if (!war || war.state !== "running") return;
        // Raid elapsed timer
        const raid = war.my_raid;
        if (raid && raid.status === "in_progress" && raid.start_time) {
            const startMs = this._toMs(raid.start_time);
            this._timers.raid = setInterval(() => {
                this.state.raidElapsed = this.formatTime(Date.now() - startMs);
            }, 100);
        }
        // War + blitz countdowns
        const endMs = war.end_at ? this._toMs(war.end_at) : null;
        const blitzMs = war.blitz_at ? this._toMs(war.blitz_at) : null;
        const blitzEndMs = war.blitz_end ? this._toMs(war.blitz_end) : null;
        const tick = () => {
            const now = Date.now();
            if (endMs) {
                const left = endMs - now;
                this.state.warRemaining = left <= 0 ? "Terminé" : this._formatDuration(left);
            }
            if (blitzMs && now < blitzMs) {
                this.state.blitzCountdown = "dans " + this._formatDuration(blitzMs - now);
            } else if (blitzEndMs && now <= blitzEndMs) {
                this.state.blitzCountdown = "EN COURS — " + this._formatDuration(blitzEndMs - now) + " restant";
            } else {
                this.state.blitzCountdown = "terminé";
            }
        };
        tick();
        this._timers.war = setInterval(tick, 1000);
        // Poll for tally / state updates every 15s while a war runs
        this._pollInterval = setInterval(() => this.reload(), 15000);
    }

    _clearTimers() {
        for (const t of Object.values(this._timers)) clearInterval(t);
        this._timers = {};
        if (this._pollInterval) {
            clearInterval(this._pollInterval);
            this._pollInterval = null;
        }
    }

    _toMs(str) {
        return new Date(str + (str.endsWith("Z") ? "" : "Z")).getTime();
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------
    formatTime(ms) {
        if (!ms || ms < 0) return "00:00.000";
        const s = Math.floor(ms / 1000);
        const m = Math.floor(s / 60);
        return `${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}.${String(ms % 1000).padStart(3, "0")}`;
    }

    _formatDuration(ms) {
        const s = Math.floor(ms / 1000);
        const h = Math.floor(s / 3600);
        const m = Math.floor((s % 3600) / 60);
        const sec = s % 60;
        if (h > 0) return `${h}h ${String(m).padStart(2, "0")}m`;
        if (m > 0) return `${m}m ${String(sec).padStart(2, "0")}s`;
        return `${sec}s`;
    }

    roleLabel(role) {
        return { leader: "👑 Chef", officer: "Officier", member: "Membre" }[role] || "Membre";
    }

    get war() {
        return this.state.clan && this.state.clan.war;
    }

    get lastWar() {
        return this.state.clan && this.state.clan.last_war;
    }
}
