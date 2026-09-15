/** @odoo-module **/

import { Component, useState, onWillStart, onWillUnmount } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { BattleArena } from "./battle_arena";
import { playSound } from "../services/sound_service";

export class BossPanel extends Component {
    static template = "odoo_speedrun.BossPanel";
    static components = { BattleArena };
    static props = {
        onBack: Function,
    };

    setup() {
        this.notification = useService("notification");
        this.actionService = useService("action");
        this.state = useState({
            loading: true,
            ladder: null,
            battleReplay: null,
            fighting: false,
            cooldownText: "",
        });
        this._timer = null;
        onWillStart(() => this.load());
        onWillUnmount(() => this._stopTimer());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.ladder = await rpc("/odoo_speedrun/boss/ladder", {});
            this._syncCooldown();
        } catch {
            this.notification.add("Impossible de charger les boss.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    get current() {
        return this.state.ladder && this.state.ladder.current;
    }

    // ------------------------------------------------------------------
    // Combat objective
    // ------------------------------------------------------------------
    async fight() {
        if (this.state.fighting || !this.current) return;
        this.state.fighting = true;
        try {
            const result = await rpc("/odoo_speedrun/boss/fight", { boss_id: this.current.id });
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
        await this.load();
    }

    // ------------------------------------------------------------------
    // Épreuve objective — driven by the floating systray countdown
    // ------------------------------------------------------------------
    _dispatchSystray(status) {
        window.dispatchEvent(new CustomEvent("speedrun-update", {
            detail: {
                type: "boss_epreuve_started",
                data: {
                    boss_id: this.current.id,
                    task_name: status.task_name,
                    task_description: status.task_description,
                    attempts: status.attempts,
                    max_attempts: status.max_attempts,
                    epreuve_deadline: status.epreuve_deadline,
                },
            },
        }));
    }

    async epreuveStart() {
        if (!this.current) return;
        const r = await rpc("/odoo_speedrun/boss/epreuve/start", { boss_id: this.current.id });
        if (r.error) {
            this.notification.add(r.error, { type: "warning" });
            await this.load();
            return;
        }
        this._dispatchSystray(r);
        this.actionService.doAction("menu");
    }

    resumeEpreuve() {
        if (!this.current || !this.current.in_progress) return;
        this._dispatchSystray(this.current);
        this.actionService.doAction("menu");
    }

    // ------------------------------------------------------------------
    // Cooldown countdown (boss won this round)
    // ------------------------------------------------------------------
    _syncCooldown() {
        this._stopTimer();
        const c = this.current;
        if (!c || !c.cooldown_remaining) {
            this.state.cooldownText = "";
            return;
        }
        const endMs = Date.now() + c.cooldown_remaining * 1000;
        const tick = () => {
            const left = endMs - Date.now();
            if (left <= 0) {
                this.state.cooldownText = "";
                this._stopTimer();
                this.load();
                return;
            }
            const s = Math.floor(left / 1000);
            this.state.cooldownText = `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
        };
        tick();
        this._timer = setInterval(tick, 1000);
    }

    _stopTimer() {
        if (this._timer) {
            clearInterval(this._timer);
            this._timer = null;
        }
    }

    // ------------------------------------------------------------------
    // Helpers
    // ------------------------------------------------------------------
    rarityLabel(r) {
        return { common: "commun", rare: "rare", epic: "épique", legendary: "légendaire" }[r] || r;
    }

    get progressPercent() {
        const l = this.state.ladder;
        if (!l || !l.total) return 0;
        return Math.round((l.defeated_count / l.total) * 100);
    }
}
