/** @odoo-module **/
import { Component, useState, onMounted, onWillUnmount } from "@odoo/owl";
import { playSound, playBeep } from "../services/sound_service";

const INTRO_MS = 1600;

const STAT_META = {
    hp:   { icon: "❤️", label: "PV" },
    atk:  { icon: "⚔️", label: "ATQ" },
    def:  { icon: "🛡️", label: "DEF" },
    spd:  { icon: "⚡", label: "VIT" },
    crit: { icon: "🎯", label: "CRIT" },
};

const SLOT_META = {
    peripheral: "🎮",
    display: "🖥️",
    tech: "🔧",
    badge: "🏅",
    module: "🔮",
    desk: "📋",
};

export class BattleArena extends Component {
    static template = "odoo_speedrun.BattleArena";
    static props = {
        replay: Object,
        onDone: Function,        // () => back to arena
        onOpenChest: Function,   // (chest) => open reward chest
    };

    setup() {
        const r = this.props.replay;
        this.STAT_META = STAT_META;
        this.SLOT_META = SLOT_META;
        this.statOrder = ["hp", "atk", "def", "spd", "crit"];
        this.slotOrder = ["peripheral", "display", "tech", "badge", "module", "desk"];
        this._timers = [];
        this._floatSeq = 0;
        // Pace the whole fight into ~11-15s regardless of turn count.
        const nTurns = Math.max(1, r.turns.length);
        this.turnMs = Math.max(340, Math.min(900, Math.floor(13000 / nTurns)));

        this.state = useState({
            phase: "intro",                 // intro | fighting | result
            challengerHp: r.challenger.stats.hp,
            opponentHp: r.opponent.stats.hp,
            attacking: null,                // 'challenger' | 'opponent'
            hitSide: null,                  // side currently being hit (for shake)
            shake: false,
            floats: [],                     // floating damage numbers
            turnIndex: 0,
        });

        onMounted(() => {
            this._timer(() => this._startFight(), INTRO_MS);
        });
        onWillUnmount(() => this._clearTimers());
    }

    // --- helpers ------------------------------------------------------
    get replay() { return this.props.replay; }
    get iWon() { return this.replay.winner === "challenger"; }
    get maxC() { return this.replay.challenger.stats.hp; }
    get maxO() { return this.replay.opponent.stats.hp; }

    hpPercent(side) {
        const hp = side === "challenger" ? this.state.challengerHp : this.state.opponentHp;
        const max = side === "challenger" ? this.maxC : this.maxO;
        return Math.max(0, Math.min(100, (hp / max) * 100));
    }

    hpClass(side) {
        const p = this.hpPercent(side);
        if (p <= 25) return "o_hp_low";
        if (p <= 55) return "o_hp_mid";
        return "o_hp_high";
    }

    _timer(fn, ms) {
        const id = setTimeout(fn, ms);
        this._timers.push(id);
        return id;
    }
    _clearTimers() {
        this._timers.forEach(clearTimeout);
        this._timers = [];
    }

    // --- fight sequencing --------------------------------------------
    _startFight() {
        this.state.phase = "fighting";
        this._playTurn(0);
    }

    _playTurn(i) {
        const turns = this.replay.turns;
        if (i >= turns.length) {
            this._timer(() => this._finish(), 500);
            return;
        }
        const turn = turns[i];
        const defender = turn.attacker === "challenger" ? "opponent" : "challenger";
        this.state.turnIndex = i + 1;

        // 1. Lunge
        this.state.attacking = turn.attacker;

        // 2. Impact
        this._timer(() => {
            // update both HP values from the authoritative log (already includes
            // lifesteal heals and thorns reflection)
            this.state.challengerHp = turn.challenger_hp;
            this.state.opponentHp = turn.opponent_hp;
            this._spawnEffects(turn, defender);
            if (turn.dodge) {
                this._sfxMiss();
            } else {
                this.state.hitSide = defender;
                this.state.shake = turn.crit;
                turn.crit ? this._sfxCrit() : this._sfxHit();
            }
        }, this.turnMs * 0.28);

        // 3. Reset pose
        this._timer(() => {
            this.state.attacking = null;
            this.state.hitSide = null;
            this.state.shake = false;
        }, this.turnMs * 0.6);

        // 4. Next
        this._timer(() => this._playTurn(i + 1), this.turnMs);
    }

    _float(side, text, kind) {
        const id = ++this._floatSeq;
        this.state.floats.push({ id, side, text, kind });
        this._timer(() => {
            const idx = this.state.floats.findIndex((f) => f.id === id);
            if (idx !== -1) this.state.floats.splice(idx, 1);
        }, 950);
    }

    _spawnEffects(turn, defender) {
        const attacker = turn.attacker;
        if (turn.combo) {
            this._float(attacker, "COMBO!", "combo");
        }
        if (turn.dodge) {
            this._float(defender, "MISS", "miss");
            return;
        }
        // Main damage on the defender, decorated with crit / type advantage.
        const arrow = turn.type_mult === "strong" ? "🔺" : turn.type_mult === "weak" ? "🔻" : "";
        let text = `${arrow}-${turn.damage}`;
        let kind = turn.crit ? "crit" : "dmg";
        if (turn.crit) {
            text = `CRIT ${text}`;
        }
        this._float(defender, text, kind);
        if (turn.blocked) {
            this._float(defender, "BLOCK", "block");
        }
        // Attacker-side effects.
        if (turn.lifesteal) {
            this._float(attacker, `+${turn.lifesteal}`, "heal");
        }
        if (turn.thorns) {
            this._float(attacker, `-${turn.thorns}`, "thorns");
        }
    }

    floatsFor(side) {
        return this.state.floats.filter((f) => f.side === side);
    }

    // --- fighter detail helpers --------------------------------------
    card(side) {
        return side === "challenger" ? this.replay.challenger : this.replay.opponent;
    }

    statChips(side) {
        const stats = this.card(side).stats || {};
        return this.statOrder.map((k) => ({
            key: k,
            icon: STAT_META[k].icon,
            label: STAT_META[k].label,
            value: stats[k] || 0,
            suffix: k === "crit" ? "%" : "",
        }));
    }

    equippedList(side) {
        const equipped = this.card(side).equipped || {};
        return this.slotOrder.map((slot) => ({
            slot,
            slotIcon: SLOT_META[slot],
            item: equipped[slot] || null,
        }));
    }

    _finish() {
        this.state.phase = "result";
        this._clearTimers();
        if (this.iWon) {
            playSound("gameOver");
        } else {
            playSound("error");
        }
    }

    skip() {
        this._clearTimers();
        const last = this.replay.turns[this.replay.turns.length - 1];
        if (last) {
            this.state.challengerHp = last.challenger_hp;
            this.state.opponentHp = last.opponent_hp;
        }
        this.state.attacking = null;
        this.state.hitSide = null;
        this.state.floats = [];
        this._finish();
    }

    openReward() {
        const chest = this.replay.reward_chest;
        if (chest) {
            this.props.onOpenChest({ id: chest.id, rarity: chest.rarity, source: "arena_win" });
        }
    }

    // --- sound effects (synthesized) ---------------------------------
    _sfxHit() { playBeep(170, 0.07, 0.18); }
    _sfxCrit() { playBeep(90, 0.16, 0.32); this._timer(() => playBeep(240, 0.09, 0.25), 70); }
    _sfxMiss() { playBeep(520, 0.05, 0.08); }
}
