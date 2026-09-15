/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

const STAT_META = {
    hp:   { icon: "❤️", label: "PV" },
    atk:  { icon: "⚔️", label: "ATQ" },
    def:  { icon: "🛡️", label: "DEF" },
    spd:  { icon: "⚡", label: "VIT" },
    crit: { icon: "🎯", label: "CRIT" },
};

export class EquipmentManager extends Component {
    static template = "odoo_speedrun.EquipmentManager";
    static props = {
        onBack: Function,
    };

    setup() {
        this.notification = useService("notification");
        this.STAT_META = STAT_META;
        this.statOrder = ["hp", "atk", "def", "spd", "crit"];
        this.state = useState({
            loading: true,
            items: [],
            sets: [],
            gearScore: 0,
            coins: 0,
            activeTitle: '',
            combat: null,
            classes: [],
            equipped: { peripheral: null, display: null, tech: null, badge: null, module: null, desk: null },
            filter: 'all',  // all | common | rare | epic | legendary
            categoryFilter: 'all',  // all | peripheral | badge | module | cosmetic
            fusingId: null,
            upgradingClass: null,
        });
        onWillStart(() => this.loadEquipment());
    }

    async loadEquipment() {
        this.state.loading = true;
        try {
            const data = await rpc('/odoo_speedrun/my_equipment', {});
            this.state.items = data.items || [];
            this.state.sets = data.sets || [];
            this.state.gearScore = data.gear_score || 0;
            this.state.coins = data.coins || 0;
            this.state.activeTitle = data.active_title || '';
            this.state.combat = data.combat || null;
            this.state.classes = data.classes || [];
            this.state.equipped = data.equipped || { peripheral: null, display: null, tech: null, badge: null, module: null, desk: null };
        } catch {
            this.notification.add('Failed to load equipment.', { type: 'danger' });
        } finally {
            this.state.loading = false;
        }
    }

    get filteredItems() {
        return this.state.items.filter(item => {
            if (this.state.filter !== 'all' && item.rarity !== this.state.filter) return false;
            if (this.state.categoryFilter !== 'all' && item.category !== this.state.categoryFilter) return false;
            return true;
        });
    }

    fusionStars(level) {
        return '★'.repeat(level) + '☆'.repeat(3 - level);
    }

    rarityLabel(r) {
        return { common: 'Commun', rare: 'Rare', epic: 'Épique', legendary: 'Légendaire' }[r] || r;
    }

    slotLabel(slot) {
        return {
            peripheral: '🎮 Périphérique',
            display:    '🖥️ Écran',
            tech:       '🔧 Hardware',
            badge:      '🏅 Badge',
            module:     '🔮 Module',
            desk:       '📋 Bureau',
        }[slot] || slot;
    }

    canFuse(item) {
        return item.count >= 3 && item.fusion_level < 3;
    }

    canAffordFuse(item) {
        return this.state.coins >= (item.fusion_cost || 0);
    }

    async equipItem(item) {
        const result = await rpc('/odoo_speedrun/equip_item', { player_equip_id: item.id });
        if (result.error) {
            this.notification.add(result.error, { type: 'danger' });
            return;
        }
        await this.loadEquipment();
        this.notification.add(`${item.icon} ${item.name} équipé !`, { type: 'success' });
    }

    async unequipSlot(slot) {
        const result = await rpc('/odoo_speedrun/unequip_slot', { slot });
        if (result.error) {
            this.notification.add(result.error, { type: 'danger' });
            return;
        }
        await this.loadEquipment();
    }

    async fuseItem(item) {
        this.state.fusingId = item.id;
        try {
            const result = await rpc('/odoo_speedrun/fuse_equipment', { player_equip_id: item.id });
            if (result.error) {
                this.notification.add(result.error, { type: 'danger' });
                if (result.coins !== undefined) {
                    this.state.coins = result.coins;
                }
                return;
            }
            if (result.coins !== undefined) {
                this.state.coins = result.coins;
            }
            await this.loadEquipment();
            const stars = this.fusionStars(result.fusion_level);
            this.notification.add(`⚗️ Fusion réussie ! ${item.icon} ${item.name} ${stars}`, { type: 'success' });
        } finally {
            this.state.fusingId = null;
        }
    }

    async upgradeClass(cls) {
        if (this.state.upgradingClass) return;
        if (cls.next_cost === null || this.state.coins < cls.next_cost) {
            this.notification.add("Pas assez de pièces pour améliorer cette classe.", { type: "warning" });
            return;
        }
        this.state.upgradingClass = cls.element;
        try {
            const result = await rpc("/odoo_speedrun/class/upgrade", { element: cls.element });
            if (result.error) {
                this.notification.add(result.error, { type: "warning" });
                if (result.coins !== undefined) this.state.coins = result.coins;
                return;
            }
            if (result.coins !== undefined) this.state.coins = result.coins;
            if (result.classes) this.state.classes = result.classes;
            this.notification.add(`${cls.icon} ${cls.label} amélioré au niveau ${result.level} !`, { type: "success" });
        } finally {
            this.state.upgradingClass = null;
        }
    }

    setCompletionPercent(set) {
        if (!set.item_count) return 0;
        return Math.round((set.owned_count / set.item_count) * 100);
    }

    /** Ordered list of non-zero stats for an item: [{key, icon, label, value}] */
    statChips(stats) {
        if (!stats) return [];
        return this.statOrder
            .filter((k) => stats[k])
            .map((k) => ({ key: k, icon: STAT_META[k].icon, label: STAT_META[k].label, value: stats[k] }));
    }
}
