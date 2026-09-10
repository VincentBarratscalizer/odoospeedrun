/** @odoo-module **/
import { Component, useState, useRef } from "@odoo/owl";
import { rpc } from "@web/core/network/rpc";
import { playSound } from "../services/sound_service";

export class ChestOpening extends Component {
    static template = "odoo_speedrun.ChestOpening";
    static props = {
        chest: Object,   // { id, rarity, source }
        onDone: Function, // called with equipment object after opening
        onSkip: Function, // called if user skips
    };

    setup() {
        this.state = useState({
            phase: "idle", // idle | shaking | opening | revealing | revealed
            equipment: null,
            error: null,
        });
        this.chestRef = useRef("chest");
        this.particleContainerRef = useRef("particles");
    }

    get chestEmoji() {
        const emojis = { common: "📦", rare: "🔷", epic: "🔮", legendary: "✨" };
        return emojis[this.props.chest.rarity] || "📦";
    }

    get rarityLabel() {
        const labels = { common: "Common", rare: "Rare", epic: "Epic", legendary: "Legendary" };
        return labels[this.props.chest.rarity] || this.props.chest.rarity;
    }

    get itemRarityLabel() {
        if (!this.state.equipment) return "";
        const labels = { common: "Common", rare: "Rare", epic: "Epic", legendary: "Legendary" };
        return labels[this.state.equipment.rarity] || this.state.equipment.rarity;
    }

    async openChest() {
        if (this.state.phase !== "idle") return;

        // Start shake
        this.state.phase = "shaking";

        // Fetch the item from server while shaking
        const fetchPromise = rpc("/odoo_speedrun/open_chest", { chest_id: this.props.chest.id });

        // Wait for shake animation (600ms)
        await new Promise(r => setTimeout(r, 600));

        // Start opening animation
        this.state.phase = "opening";

        // Wait for opening (500ms) then get result
        const [result] = await Promise.all([
            fetchPromise,
            new Promise(r => setTimeout(r, 500)),
        ]);

        if (result && result.equipment) {
            this.state.equipment = result.equipment;
            this.spawnParticles(this.props.chest.rarity);
            this.state.phase = "revealing";
            playSound("taskComplete");
            await new Promise(r => setTimeout(r, 600));
            this.state.phase = "revealed";
            // Extra effect for legendary
            if (result.equipment.rarity === "legendary") {
                playSound("gameOver");
            }
        } else {
            this.state.error = result?.error || "Failed to open chest.";
            this.state.phase = "idle";
        }
    }

    spawnParticles(rarity) {
        const container = this.particleContainerRef.el;
        if (!container) return;
        const colors = {
            common: ["#9e9e9e", "#bdbdbd", "#e0e0e0"],
            rare: ["#42a5f5", "#29b6f6", "#4dd0e1"],
            epic: ["#ab47bc", "#ce93d8", "#7c4dff"],
            legendary: ["#ffd700", "#ffeb3b", "#ff9800", "#ff6f00"],
        };
        const particleColors = colors[rarity] || colors.common;
        const count = rarity === "legendary" ? 60 : rarity === "epic" ? 40 : 25;

        for (let i = 0; i < count; i++) {
            const p = document.createElement("div");
            p.className = "o_gacha_particle";
            const color = particleColors[Math.floor(Math.random() * particleColors.length)];
            const angle = Math.random() * 360;
            const distance = 80 + Math.random() * 180;
            const size = 4 + Math.random() * 8;
            const duration = 800 + Math.random() * 800;
            const dx = Math.cos((angle * Math.PI) / 180) * distance;
            const dy = Math.sin((angle * Math.PI) / 180) * distance;

            p.style.cssText = `
                position: absolute;
                width: ${size}px;
                height: ${size}px;
                border-radius: 50%;
                background: ${color};
                left: 50%;
                top: 50%;
                transform: translate(-50%, -50%);
                pointer-events: none;
                animation: particleExplode ${duration}ms ease-out forwards;
                --dx: ${dx}px;
                --dy: ${dy}px;
                box-shadow: 0 0 ${size * 2}px ${color};
            `;
            container.appendChild(p);
            setTimeout(() => p.remove(), duration + 100);
        }
    }

    onContinue() {
        this.props.onDone(this.state.equipment);
    }
}
