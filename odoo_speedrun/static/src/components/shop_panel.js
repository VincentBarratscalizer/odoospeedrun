/** @odoo-module **/

import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";
import { playSound } from "../services/sound_service";

const RARITY_META = {
    common: { label: "Commun", cls: "o_rar_common" },
    rare: { label: "Rare", cls: "o_rar_rare" },
    epic: { label: "Épique", cls: "o_rar_epic" },
    legendary: { label: "Légendaire", cls: "o_rar_legendary" },
};

const CATEGORY_ICON = {
    peripheral: "🎮", display: "🖥️", tech: "🔧",
    badge: "🏅", module: "🔮", desk: "📋",
};

export class ShopPanel extends Component {
    static template = "odoo_speedrun.ShopPanel";
    static props = {
        onBack: Function,
    };

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            shop: null,
            buyingId: null,
        });
        onWillStart(() => this.load());
    }

    async load() {
        this.state.loading = true;
        try {
            this.state.shop = await rpc("/odoo_speedrun/shop/today", {});
        } catch {
            this.notification.add("Impossible de charger la boutique.", { type: "danger" });
        } finally {
            this.state.loading = false;
        }
    }

    async buy(item) {
        if (this.state.buyingId || this.state.shop.purchased_today) return;
        if (this.state.shop.coins < item.price) {
            this.notification.add("Pas assez de pièces pour cet article.", { type: "warning" });
            return;
        }
        this.state.buyingId = item.id;
        try {
            const result = await rpc("/odoo_speedrun/shop/buy", { equipment_id: item.id });
            if (result.error) {
                playSound("error");
                this.notification.add(result.error, { type: "warning" });
                return;
            }
            if (result.success) {
                playSound("taskComplete");
                this.notification.add(
                    `🛒 ${result.equipment.icon} ${result.equipment.name} acheté !`,
                    { type: "success" });
                if (result.shop) {
                    this.state.shop = result.shop;
                }
            }
        } finally {
            this.state.buyingId = null;
        }
    }

    rarity(r) {
        return RARITY_META[r] || RARITY_META.common;
    }

    catIcon(cat) {
        return CATEGORY_ICON[cat] || "📦";
    }

    canBuy(item) {
        return !this.state.shop.purchased_today && this.state.shop.coins >= item.price;
    }
}
