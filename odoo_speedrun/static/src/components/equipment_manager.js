/** @odoo-module **/
import { Component, useState, onWillStart } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { useService } from "@web/core/utils/hooks";

export class EquipmentManager extends Component {
    static template = "odoo_speedrun.EquipmentManager";
    static props = {
        onBack: Function,
    };

    setup() {
        this.notification = useService("notification");
        this.state = useState({
            loading: true,
            items: [],
            sets: [],
            gearScore: 0,
            activeTitle: '',
            equipped: { peripheral: null, display: null, tech: null, badge: null, module: null, desk: null },
            filter: 'all',  // all | common | rare | epic | legendary
            categoryFilter: 'all',  // all | peripheral | badge | module | cosmetic
            fusingId: null,
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
            this.state.activeTitle = data.active_title || '';
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
                return;
            }
            await this.loadEquipment();
            const stars = this.fusionStars(result.fusion_level);
            this.notification.add(`⚗️ Fusion réussie ! ${item.icon} ${item.name} ${stars}`, { type: 'success' });
        } finally {
            this.state.fusingId = null;
        }
    }

    setCompletionPercent(set) {
        if (!set.item_count) return 0;
        return Math.round((set.owned_count / set.item_count) * 100);
    }
}
