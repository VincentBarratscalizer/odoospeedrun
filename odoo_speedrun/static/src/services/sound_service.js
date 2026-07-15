/** @odoo-module **/

/**
 * Speedrun Sound Service
 *
 * Plays sound effects during gameplay using both Odoo's existing audio files
 * and synthesized sounds via Web Audio API.
 */

const SOUNDS = {
    // Reuse Odoo's existing sound files
    playerJoined: { path: "/mail/static/src/audio/ting", volume: 0.4 },
    taskComplete: { path: "/point_of_sale/static/src/sounds/bell", volume: 0.6 },
    roundOver: { path: "/point_of_sale/static/src/sounds/notification", volume: 0.5 },
    error: { path: "/point_of_sale/static/src/sounds/error", volume: 0.3 },
    gameOver: { path: "/point_of_sale/static/src/sounds/order-receive-tone", volume: 0.6 },
};

function _getAudioExt() {
    const audio = new Audio();
    return audio.canPlayType("audio/ogg; codecs=vorbis") ? ".ogg" : ".mp3";
}

let _ext = null;

function getExt() {
    if (!_ext) _ext = _getAudioExt();
    return _ext;
}

const _cache = {};

/**
 * Play a named sound effect.
 */
export function playSound(name) {
    const def = SOUNDS[name];
    if (!def) return;
    try {
        const url = def.path + getExt();
        if (!_cache[name]) {
            _cache[name] = new Audio(url);
        }
        const audio = _cache[name];
        audio.volume = def.volume;
        audio.currentTime = 0;
        audio.play().catch(() => {});
    } catch {
        // Audio not available
    }
}

/**
 * Play a synthesized beep using Web Audio API.
 * Used for countdown (3-2-1-GO).
 * @param {number} frequency - Hz (e.g. 440)
 * @param {number} duration - seconds
 * @param {number} volume - 0-1
 */
export function playBeep(frequency = 440, duration = 0.15, volume = 0.3) {
    try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.frequency.value = frequency;
        osc.type = "square";
        gain.gain.value = volume;
        // Fade out
        gain.gain.setValueAtTime(volume, ctx.currentTime);
        gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + duration);
        osc.start(ctx.currentTime);
        osc.stop(ctx.currentTime + duration);
    } catch {
        // Web Audio not available
    }
}

/**
 * Play the countdown sequence sound.
 * @param {number} count - countdown value (3, 2, 1, 0=GO)
 */
export function playCountdownBeep(count) {
    if (count > 0) {
        // Regular beep - higher pitch as we get closer
        playBeep(300 + (4 - count) * 100, 0.12, 0.25);
    } else {
        // GO! - longer, higher pitched
        playBeep(880, 0.4, 0.4);
    }
}
