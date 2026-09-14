import json
import random

from odoo import api, fields, models
from odoo.exceptions import UserError

# Arena ELO sensitivity
ARENA_K_FACTOR = 24

# Simulation tuning
MAX_ACTIONS = 100         # hard cap on number of strikes (avoids infinite fights)
ATB_THRESHOLD = 1000.0    # "action gauge" a fighter must fill to act
CRIT_MULTIPLIER = 1.7
FOCUS_CRIT_MULTIPLIER = 2.2   # display element passive
DAMAGE_VARIANCE = (0.9, 1.1)
MAX_DODGE = 25            # cap on dodge chance from speed advantage (%)

# ---------------------------------------------------------------------------
# Element / type advantage chart. The 6 categories form an advantage cycle:
# each element is STRONG against the next two elements in the order and WEAK
# against the previous two. The opposite element (3 apart) is neutral.
# ---------------------------------------------------------------------------
ELEMENT_ORDER = ['peripheral', 'display', 'badge', 'module', 'tech', 'desk']
TYPE_STRONG = 1.35
TYPE_WEAK = 0.70

# Passive granted by each element (see ELEMENT_META in speedrun_profile.py)
ELEMENT_PASSIVE = {
    'peripheral': 'combo',
    'display': 'focus',
    'badge': 'execute',
    'module': 'lifesteal',
    'tech': 'block',
    'desk': 'thorns',
}
BLOCK_CHANCE = 0.22       # tech: chance to greatly reduce an incoming hit
BLOCK_REDUCTION = 0.30    # blocked hits deal only 30% damage
LIFESTEAL_RATIO = 0.30    # module: heal this fraction of damage dealt
THORNS_RATIO = 0.22       # desk: reflect this fraction of damage taken
EXECUTE_BONUS = 0.6       # badge: up to +60% damage vs a 0-HP target
FOCUS_CRIT_BONUS = 8      # display: +8% crit chance


def _type_multiplier(att_el, def_el):
    """Damage multiplier from attacker element vs defender element."""
    if not att_el or not def_el or att_el == def_el:
        return 1.0, 'neutral'
    try:
        diff = (ELEMENT_ORDER.index(def_el) - ELEMENT_ORDER.index(att_el)) % 6
    except ValueError:
        return 1.0, 'neutral'
    if diff in (1, 2):
        return TYPE_STRONG, 'strong'
    if diff in (4, 5):
        return TYPE_WEAK, 'weak'
    return 1.0, 'neutral'

# Chest rarity awarded to the winner, weighted by how strong the opponent was.
# key = "power ratio bucket" -> {chest_rarity: weight}
WIN_CHEST_TABLE = {
    'underdog':  {'rare': 45, 'epic': 40, 'legendary': 15},   # beat someone stronger
    'even':      {'common': 45, 'rare': 40, 'epic': 13, 'legendary': 2},
    'favorite':  {'common': 75, 'rare': 22, 'epic': 3},        # beat someone weaker
}
DAILY_REWARD_CAP = 15     # max reward chests earned from the arena per day


class SpeedrunBattle(models.Model):
    _name = 'speedrun.battle'
    _description = 'Speedrun Arena Battle'
    _order = 'create_date desc, id desc'

    challenger_id = fields.Many2one(
        'speedrun.profile', required=True, ondelete='cascade', index=True, string='Challenger Profile')
    opponent_id = fields.Many2one(
        'speedrun.profile', required=True, ondelete='cascade', index=True, string='Opponent Profile')
    challenger_user_id = fields.Many2one(
        related='challenger_id.user_id', store=True, index=True, string='Challenger')
    opponent_user_id = fields.Many2one(
        related='opponent_id.user_id', store=True, string='Opponent')
    winner_id = fields.Many2one('speedrun.profile', ondelete='set null')
    challenger_won = fields.Boolean()

    rating_change_challenger = fields.Integer()
    rating_change_opponent = fields.Integer()
    reward_chest_id = fields.Many2one('speedrun.player.chest', ondelete='set null')

    log = fields.Text(help='JSON-encoded replay of the fight.')

    # ------------------------------------------------------------------
    # Public entry point
    # ------------------------------------------------------------------
    @api.model
    def _fight(self, challenger, opponent):
        """Run a battle between two profiles, persist it, apply rating & rewards.

        :return: the full replay dict for the frontend to animate.
        """
        if challenger.id == opponent.id:
            raise UserError('You cannot challenge yourself.')

        replay = self._simulate(challenger, opponent)
        challenger_won = replay['winner'] == 'challenger'
        winner = challenger if challenger_won else opponent

        # --- Arena ELO update (both profiles move) ---
        rc, ro = self._apply_rating(challenger, opponent, challenger_won)

        # --- Stats ---
        challenger.arena_battles += 1
        opponent.arena_battles += 1
        if challenger_won:
            challenger.arena_wins += 1
            opponent.arena_losses += 1
        else:
            challenger.arena_losses += 1
            opponent.arena_wins += 1

        battle = self.create({
            'challenger_id': challenger.id,
            'opponent_id': opponent.id,
            'winner_id': winner.id,
            'challenger_won': challenger_won,
            'rating_change_challenger': rc,
            'rating_change_opponent': ro,
            'log': json.dumps(replay),
        })

        # --- Reward: winner gets a chest (daily-capped for the challenger) ---
        reward = None
        if challenger_won:
            reward = challenger._grant_arena_chest(opponent, battle)
            if reward:
                battle.reward_chest_id = reward.id

        # --- Notify the opponent they were attacked ---
        opponent.user_id._bus_send('speedrun/arena_attacked', {
            'challenger_name': challenger.user_id.name,
            'challenger_won': challenger_won,
            'rating_change': ro,
        })

        replay.update({
            'battle_id': battle.id,
            'rating_change': rc,
            'new_rating': challenger.arena_rating,
            'reward_chest': (
                {'id': reward.id, 'rarity': reward.rarity} if reward else None
            ),
        })
        return replay

    # ------------------------------------------------------------------
    # Simulation
    # ------------------------------------------------------------------
    def _simulate(self, challenger, opponent):
        """Pure turn-based auto-battle with elements & passives. Returns a replay dict."""
        def fighter(profile, side):
            element = profile.combat_element or None
            return {
                'side': side,
                'name': profile.user_id.name,
                'hp': profile.combat_hp,
                'max_hp': profile.combat_hp,
                'atk': profile.combat_atk,
                'def': profile.combat_def,
                'spd': max(1, profile.combat_spd),
                'crit': profile.combat_crit,
                'element': element,
                'passive': ELEMENT_PASSIVE.get(element),
                'gauge': 0.0,
            }

        c = fighter(challenger, 'challenger')
        o = fighter(opponent, 'opponent')
        state = {'c': c, 'o': o}

        turns = []
        actions = 0
        while c['hp'] > 0 and o['hp'] > 0 and actions < MAX_ACTIONS:
            # Advance the action gauges until someone is ready to strike.
            time_c = (ATB_THRESHOLD - c['gauge']) / c['spd']
            time_o = (ATB_THRESHOLD - o['gauge']) / o['spd']
            advance = min(time_c, time_o)
            c['gauge'] += advance * c['spd']
            o['gauge'] += advance * o['spd']

            attacker, defender = (c, o) if c['gauge'] >= o['gauge'] else (o, c)
            attacker['gauge'] -= ATB_THRESHOLD

            turns.append(self._strike(attacker, defender, state, combo=False))
            actions += 1

            # Combo passive (peripheral): a chance at an immediate second strike.
            if (attacker['passive'] == 'combo' and defender['hp'] > 0 and attacker['hp'] > 0
                    and actions < MAX_ACTIONS
                    and random.random() < min(0.28, attacker['spd'] / 420.0)):
                turns.append(self._strike(attacker, defender, state, combo=True))
                actions += 1

        if c['hp'] <= 0 and o['hp'] > 0:
            winner = 'opponent'
        elif o['hp'] <= 0 and c['hp'] > 0:
            winner = 'challenger'
        else:
            # timeout / double KO -> higher remaining HP ratio wins (challenger on tie)
            winner = 'challenger' if (c['hp'] / c['max_hp']) >= (o['hp'] / o['max_hp']) else 'opponent'

        return {
            'challenger': self._card(challenger, 'challenger'),
            'opponent': self._card(opponent, 'opponent'),
            'turns': turns,
            'winner': winner,
        }

    def _strike(self, attacker, defender, state, combo=False):
        """Resolve one attack, mutate hp of both fighters, return a log entry."""
        c, o = state['c'], state['o']
        event = {
            'attacker': attacker['side'],
            'combo': combo,
            'crit': False,
            'dodge': False,
            'blocked': False,
            'damage': 0,
            'lifesteal': 0,
            'thorns': 0,
            'type_mult': 'neutral',
        }

        # Dodge from speed advantage
        dodge_chance = min(MAX_DODGE, max(0.0, (defender['spd'] - attacker['spd']) * 0.4))
        if random.random() * 100 < dodge_chance:
            event['dodge'] = True
            event['challenger_hp'], event['opponent_hp'] = c['hp'], o['hp']
            return event

        # Block passive (tech, defender)
        blocked = defender['passive'] == 'block' and random.random() < BLOCK_CHANCE
        event['blocked'] = blocked

        # Focus passive (display, attacker): more crit chance & damage
        crit_chance = attacker['crit'] + (FOCUS_CRIT_BONUS if attacker['passive'] == 'focus' else 0)
        crit = random.random() * 100 < crit_chance
        event['crit'] = crit

        mitigation = 100.0 / (100.0 + defender['def'])
        raw = attacker['atk'] * mitigation * random.uniform(*DAMAGE_VARIANCE)

        # Type advantage
        mult, tag = _type_multiplier(attacker['element'], defender['element'])
        raw *= mult
        event['type_mult'] = tag

        if crit:
            raw *= FOCUS_CRIT_MULTIPLIER if attacker['passive'] == 'focus' else CRIT_MULTIPLIER

        # Execute passive (badge, attacker): bonus vs low-HP targets
        if attacker['passive'] == 'execute':
            missing = 1.0 - defender['hp'] / defender['max_hp']
            raw *= 1.0 + EXECUTE_BONUS * missing

        if blocked:
            raw *= BLOCK_REDUCTION

        damage = max(1, int(round(raw)))
        defender['hp'] = max(0, defender['hp'] - damage)
        event['damage'] = damage

        # Lifesteal passive (module, attacker)
        if attacker['passive'] == 'lifesteal' and damage > 0:
            heal = int(round(damage * LIFESTEAL_RATIO))
            if heal > 0:
                attacker['hp'] = min(attacker['max_hp'], attacker['hp'] + heal)
                event['lifesteal'] = heal

        # Thorns passive (desk, defender): reflect part of the damage taken
        if defender['passive'] == 'thorns' and damage > 0 and not blocked:
            reflect = int(round(damage * THORNS_RATIO))
            if reflect > 0:
                attacker['hp'] = max(0, attacker['hp'] - reflect)
                event['thorns'] = reflect

        event['challenger_hp'], event['opponent_hp'] = c['hp'], o['hp']
        return event

    def _card(self, profile, side):
        payload = profile._combat_payload()
        payload['side'] = side
        return payload

    # ------------------------------------------------------------------
    # Rating & rewards
    # ------------------------------------------------------------------
    def _apply_rating(self, challenger, opponent, challenger_won):
        ec = 1.0 / (1.0 + 10 ** ((opponent.arena_rating - challenger.arena_rating) / 400.0))
        eo = 1.0 - ec
        actual_c = 1.0 if challenger_won else 0.0
        change_c = round(ARENA_K_FACTOR * (actual_c - ec))
        change_o = round(ARENA_K_FACTOR * ((1.0 - actual_c) - eo))

        challenger.arena_rating += change_c
        opponent.arena_rating += change_o
        challenger.arena_peak = max(challenger.arena_peak, challenger.arena_rating)
        opponent.arena_peak = max(opponent.arena_peak, opponent.arena_rating)
        return change_c, change_o
