/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";

export class ChestList extends Component {
    static template = "odoo_speedrun.ChestList";
    static props = {
        onOpenChest: Function,  // called with chest object
        onClaimDaily: Function,
        onBack: Function,
    };

    setup() {
        this.state = useState({
            chests: [],
            dailyAvailable: false,
            loading: true,
            pity: null,
        });
        onWillStart(async () => {
            await this.loadChests();
        });
    }

    async loadChests() {
        try {
            const result = await rpc("/odoo_speedrun/my_chests", {});
            this.state.chests = result.chests || [];
            this.state.dailyAvailable = result.daily_available || false;
            this.state.pity = result.pity || null;
        } catch {
            this.state.chests = [];
        } finally {
            this.state.loading = false;
        }
    }

    /** Openings left before the next guaranteed legendary (or null). */
    get legendaryPity() {
        const p = this.state.pity;
        if (!p || !p.enabled || !p.legendary_hard) return null;
        const remaining = Math.max(0, p.legendary_hard - p.legendary_counter);
        return {
            remaining,
            percent: Math.min(100, Math.round((p.legendary_counter / p.legendary_hard) * 100)),
            soft: p.soft_start && p.legendary_counter >= p.soft_start,
        };
    }

    get epicPity() {
        const p = this.state.pity;
        if (!p || !p.enabled || !p.epic_hard) return null;
        const remaining = Math.max(0, p.epic_hard - p.epic_counter);
        return {
            remaining,
            percent: Math.min(100, Math.round((p.epic_counter / p.epic_hard) * 100)),
        };
    }

    rarityLabel(rarity) {
        const labels = { common: "Common", rare: "Rare", epic: "Epic", legendary: "Legendary" };
        return labels[rarity] || rarity;
    }

    chestEmoji(rarity) {
        const emojis = { common: "📦", rare: "🔷", epic: "🔮", legendary: "✨" };
        return emojis[rarity] || "📦";
    }

    async claimDaily() {
        const result = await rpc("/odoo_speedrun/daily_chest", {});
        if (result.error) return;
        this.state.dailyAvailable = false;
        // Open the daily chest immediately
        await this.loadChests();
        if (result.chest_id) {
            this.props.onClaimDaily({ id: result.chest_id, rarity: result.rarity, source: "daily" });
        }
    }
}
