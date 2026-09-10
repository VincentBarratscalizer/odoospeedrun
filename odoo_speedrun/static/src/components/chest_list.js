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
        } catch {
            this.state.chests = [];
        } finally {
            this.state.loading = false;
        }
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
