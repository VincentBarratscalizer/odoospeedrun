import math

from odoo import api, fields, models

K_FACTOR = 32

# Level thresholds: level = isqrt(xp / 100) + 1
# => level 1: 0 xp, level 2: 100 xp, level 3: 400 xp, level 4: 900 xp...
LEVEL_TITLES = [
    (15, 'Legend'),
    (10, 'Grandmaster'),
    (7, 'Master'),
    (5, 'Expert'),
    (4, 'Sprinter'),
    (3, 'Runner'),
    (2, 'Apprentice'),
    (1, 'Rookie'),
]

# XP rewards
XP_PER_POINT = 15
XP_ROUND_FINISHED = 10
XP_GAME_WON = 50


class SpeedrunProfile(models.Model):
    _name = 'speedrun.profile'
    _description = 'Speedrun Player Profile'
    _order = 'elo desc'
    _rec_name = 'user_id'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    elo = fields.Integer(string='ELO Rating', default=1000)
    peak_elo = fields.Integer(string='Peak ELO', default=1000)
    xp = fields.Integer(string='Experience Points', default=0)
    level = fields.Integer(compute='_compute_level', store=True)
    level_title = fields.Char(compute='_compute_level', store=True)

    games_played = fields.Integer(default=0)
    games_won = fields.Integer(default=0)
    rounds_played = fields.Integer(default=0)
    rounds_won = fields.Integer(default=0)
    best_time_ms = fields.Integer(string='Best Time (ms)', default=0)
    win_rate = fields.Float(string='Win Rate (%)', compute='_compute_win_rate')

    elo_history_ids = fields.One2many('speedrun.elo.history', 'profile_id', string='ELO History')
    badge_award_ids = fields.One2many('speedrun.badge.award', 'profile_id', string='Badges')
    badge_count = fields.Integer(compute='_compute_badge_count')
    chest_ids = fields.One2many('speedrun.player.chest', 'profile_id', string='Chests')
    equipment_collection_ids = fields.One2many('speedrun.player.equipment', 'profile_id')
    last_daily_chest = fields.Date(string='Last Daily Chest')
    pending_chest_count = fields.Integer(compute='_compute_pending_chest_count', store=False)

    # Equipment slots (one per category)
    equipped_peripheral_id = fields.Many2one(
        'speedrun.player.equipment',
        domain="[('profile_id', '=', id), ('equipment_id.category', '=', 'peripheral')]",
        ondelete='set null', string='Equipped Peripheral',
    )
    equipped_badge_id = fields.Many2one(
        'speedrun.player.equipment',
        domain="[('profile_id', '=', id), ('equipment_id.category', '=', 'badge')]",
        ondelete='set null', string='Equipped Badge',
    )
    equipped_module_id = fields.Many2one(
        'speedrun.player.equipment',
        domain="[('profile_id', '=', id), ('equipment_id.category', '=', 'module')]",
        ondelete='set null', string='Equipped Module',
    )
    equipped_cosmetic_id = fields.Many2one(
        'speedrun.player.equipment',
        domain="[('profile_id', '=', id), ('equipment_id.category', '=', 'cosmetic')]",
        ondelete='set null', string='Equipped Cosmetic',
    )

    # Gear score and sets
    gear_score = fields.Integer(compute='_compute_gear_score', store=True)
    unlocked_set_ids = fields.Many2many(
        'speedrun.equipment.set', 'speedrun_profile_unlocked_set_rel', 'profile_id', 'set_id',
        compute='_compute_unlocked_sets', store=True,
        string='Unlocked Sets',
    )
    active_title = fields.Char(compute='_compute_active_title', store=True)

    _unique_user_profile = models.Constraint(
        'UNIQUE(user_id)',
        'A user can only have one speedrun profile.',
    )

    @api.depends('xp')
    def _compute_level(self):
        for profile in self:
            level = math.isqrt(max(profile.xp, 0) // 100) + 1
            profile.level = level
            profile.level_title = next(
                (title for min_level, title in LEVEL_TITLES if level >= min_level),
                'Rookie',
            )

    @api.depends('games_played', 'games_won')
    def _compute_win_rate(self):
        for profile in self:
            profile.win_rate = (
                profile.games_won * 100.0 / profile.games_played
                if profile.games_played else 0.0
            )

    @api.depends('badge_award_ids')
    def _compute_badge_count(self):
        for profile in self:
            profile.badge_count = len(profile.badge_award_ids)

    @api.depends('chest_ids.state')
    def _compute_pending_chest_count(self):
        for profile in self:
            profile.pending_chest_count = len(profile.chest_ids.filtered(lambda c: c.state == 'pending'))

    @api.depends('equipment_collection_ids.item_score')
    def _compute_gear_score(self):
        for profile in self:
            profile.gear_score = sum(profile.equipment_collection_ids.mapped('item_score'))

    @api.depends('equipment_collection_ids.equipment_id')
    def _compute_unlocked_sets(self):
        all_sets = self.env['speedrun.equipment.set'].search([])
        for profile in self:
            owned_ids = set(profile.equipment_collection_ids.mapped('equipment_id').ids)
            unlocked = all_sets.filtered(
                lambda s: s.item_ids and all(item.id in owned_ids for item in s.item_ids)
            )
            profile.unlocked_set_ids = [(6, 0, unlocked.ids)]

    @api.depends('unlocked_set_ids')
    def _compute_active_title(self):
        for profile in self:
            titles = profile.unlocked_set_ids.sorted('sequence').mapped('title')
            profile.active_title = ' · '.join(titles) if titles else ''

    @api.model
    def _get_or_create(self, users):
        """Return (and create if missing) profiles for the given users."""
        profiles = self.search([('user_id', 'in', users.ids)])
        missing = users - profiles.user_id
        if missing:
            profiles |= self.create([{'user_id': user.id} for user in missing])
        return profiles

    def _recompute_stats(self):
        """Recompute aggregate stats from game history (idempotent)."""
        for profile in self:
            uid = profile.user_id.id
            players = self.env['speedrun.player'].search([
                ('user_id', '=', uid),
                ('game_id.state', '=', 'finished'),
            ])
            games = players.game_id
            results = self.env['speedrun.round.result'].search([
                ('user_id', '=', uid),
                ('rank', '>', 0),
            ])
            durations = [r.duration_ms for r in results if r.duration_ms > 0]
            profile.write({
                'games_played': len(games),
                'games_won': len(games.filtered(lambda g: g.winner_id.id == uid)),
                'rounds_played': len(results),
                'rounds_won': len(results.filtered(lambda r: r.rank == 1)),
                'best_time_ms': min(durations) if durations else 0,
            })

    # ------------------------------------------------------------------
    # Game end processing: ELO, XP, stats, badges, level ups
    # ------------------------------------------------------------------
    @api.model
    def _process_game_results(self, game):
        """Process a finished game: update ELO, XP, stats and badges.

        :return: dict {user_id: {'elo_before': int, 'elo_after': int, 'elo_change': int}}
        """
        players = game.player_ids
        profiles = self._get_or_create(players.user_id)
        profile_by_user = {p.user_id.id: p for p in profiles}
        old_levels = {p.user_id.id: p.level for p in profiles}

        # --- ELO (only meaningful with 2+ players) ---
        elo_changes = {}
        if game.game_mode == 'best_of':
            # Best-of: round wins decide, points break ties (tuple comparison)
            scores = {p.user_id.id: (p.round_wins, p.score) for p in players}
        else:
            scores = {p.user_id.id: p.score for p in players}
        if len(players) >= 2:
            elos = {uid: profile_by_user[uid].elo for uid in scores}
            n = len(players)
            for uid in scores:
                delta = 0.0
                for other_uid in scores:
                    if other_uid == uid:
                        continue
                    expected = 1.0 / (1.0 + 10 ** ((elos[other_uid] - elos[uid]) / 400.0))
                    if scores[uid] > scores[other_uid]:
                        actual = 1.0
                    elif scores[uid] < scores[other_uid]:
                        actual = 0.0
                    else:
                        actual = 0.5
                    delta += actual - expected
                elo_changes[uid] = round(K_FACTOR * delta / (n - 1))

        # --- Apply ELO + XP per player ---
        result = {}
        for player in players:
            uid = player.user_id.id
            profile = profile_by_user[uid]
            elo_before = profile.elo
            elo_change = elo_changes.get(uid, 0)
            elo_after = elo_before + elo_change

            my_results = game.round_result_ids.filtered(lambda r: r.user_id.id == uid)
            xp_gain = (
                sum(my_results.mapped('points')) * XP_PER_POINT
                + len(my_results.filtered(lambda r: r.rank > 0)) * XP_ROUND_FINISHED
                + (XP_GAME_WON if game.winner_id.id == uid else 0)
            )

            profile.write({
                'elo': elo_after,
                'peak_elo': max(profile.peak_elo, elo_after),
                'xp': profile.xp + xp_gain,
            })
            if len(players) >= 2:
                self.env['speedrun.elo.history'].create({
                    'profile_id': profile.id,
                    'game_id': game.id,
                    'elo_before': elo_before,
                    'elo_after': elo_after,
                    'elo_change': elo_change,
                })
            result[uid] = {
                'elo_before': elo_before,
                'elo_after': elo_after,
                'elo_change': elo_change,
                'xp_gain': xp_gain,
            }

        # --- Stats, badges, level-up notifications ---
        profiles._recompute_stats()
        profiles._check_badges(game=game)
        for profile in profiles:
            uid = profile.user_id.id
            if profile.level > old_levels[uid]:
                profile.user_id._bus_send('speedrun/level_up', {
                    'level': profile.level,
                    'level_title': profile.level_title,
                    'xp': profile.xp,
                })

        # --- Award gacha chests ---
        from odoo.addons.odoo_speedrun.models.speedrun_gacha import CHEST_BY_RANK, DEFAULT_CHEST
        if game.game_mode == 'best_of':
            ranked_players = sorted(players, key=lambda p: (-p.round_wins, -p.score))
        else:
            ranked_players = sorted(players, key=lambda p: -p.score)
        for i, player in enumerate(ranked_players):
            uid = player.user_id.id
            profile = profile_by_user[uid]
            chest_rarity = CHEST_BY_RANK.get(i, DEFAULT_CHEST)
            profile._award_chest(chest_rarity, game_id=game.id, source='game_win')

        return result

    def _award_chest(self, rarity, game_id=None, source='game_win'):
        self.ensure_one()
        chest = self.env['speedrun.player.chest'].create({
            'profile_id': self.id,
            'rarity': rarity,
            'game_id': game_id,
            'source': source,
        })
        self.user_id._bus_send('speedrun/chest_earned', {
            'chest_id': chest.id,
            'rarity': rarity,
            'source': source,
        })
        return chest

    def _open_chest(self, chest_id):
        """Open a chest, add item to collection, return equipment dict or None."""
        chest = self.env['speedrun.player.chest'].browse(int(chest_id))
        if not chest.exists() or chest.profile_id.id != self.id or chest.state != 'pending':
            return None
        equipment = self._roll_equipment(chest.rarity)
        chest.write({'state': 'opened', 'equipment_id': equipment.id if equipment else False})
        if equipment:
            existing = self.env['speedrun.player.equipment'].search([
                ('profile_id', '=', self.id),
                ('equipment_id', '=', equipment.id),
            ], limit=1)
            if existing:
                existing.count += 1
            else:
                self.env['speedrun.player.equipment'].create({
                    'profile_id': self.id,
                    'equipment_id': equipment.id,
                })
            return {
                'id': equipment.id,
                'name': equipment.name,
                'rarity': equipment.rarity,
                'icon': equipment.icon or '',
                'description': equipment.description or '',
                'category': equipment.category or '',
            }
        return None

    def _roll_equipment(self, chest_rarity):
        import random
        from odoo.addons.odoo_speedrun.models.speedrun_gacha import CHEST_DROP_TABLES
        weights = CHEST_DROP_TABLES.get(chest_rarity, CHEST_DROP_TABLES['common'])
        roll = random.randint(1, 100)
        cumulative = 0
        rolled_rarity = 'common'
        for rarity, w in weights.items():
            cumulative += w
            if roll <= cumulative:
                rolled_rarity = rarity
                break
        items = self.env['speedrun.equipment'].search([('rarity', '=', rolled_rarity)])
        if not items:
            items = self.env['speedrun.equipment'].search([])
        if not items:
            return None
        return self.env['speedrun.equipment'].browse(random.choice(items.ids))

    def _check_badges(self, game=None):
        """Award any newly-earned badges (+ their XP rewards)."""
        badges = self.env['speedrun.badge'].search([])
        Award = self.env['speedrun.badge.award']
        for profile in self:
            earned = profile.badge_award_ids.badge_id
            for badge in badges - earned:
                if badge._matches_profile(profile):
                    Award.create({
                        'profile_id': profile.id,
                        'badge_id': badge.id,
                        'game_id': game.id if game else False,
                    })
                    if badge.xp_reward:
                        profile.xp += badge.xp_reward
                    profile.user_id._bus_send('speedrun/badge_earned', {
                        'badge_name': badge.name,
                        'badge_icon': badge.icon or '',
                        'badge_description': badge.description or '',
                        'xp_reward': badge.xp_reward,
                    })

    def _slot_payload(self, player_equip):
        if not player_equip:
            return None
        return {
            'id': player_equip.id,
            'equipment_id': player_equip.equipment_id.id,
            'name': player_equip.equipment_id.name,
            'icon': player_equip.equipment_id.icon or '',
            'rarity': player_equip.rarity,
            'fusion_level': player_equip.fusion_level,
            'item_score': player_equip.item_score,
        }

    def _equip_item(self, player_equip_id):
        """Equip an item to its category slot. Returns dict with result."""
        self.ensure_one()
        item = self.env['speedrun.player.equipment'].browse(int(player_equip_id))
        if not item.exists() or item.profile_id.id != self.id:
            return {'error': 'Item not found.'}
        slot_field = {
            'peripheral': 'equipped_peripheral_id',
            'badge': 'equipped_badge_id',
            'module': 'equipped_module_id',
            'cosmetic': 'equipped_cosmetic_id',
        }.get(item.equipment_id.category)
        if not slot_field:
            return {'error': 'Unknown item category.'}
        self.write({slot_field: item.id})
        return {'success': True, 'slot': item.equipment_id.category}

    def _unequip_slot(self, slot):
        """Unequip the item from a slot."""
        self.ensure_one()
        slot_field = {
            'peripheral': 'equipped_peripheral_id',
            'badge': 'equipped_badge_id',
            'module': 'equipped_module_id',
            'cosmetic': 'equipped_cosmetic_id',
        }.get(slot)
        if not slot_field:
            return {'error': 'Unknown slot.'}
        self.write({slot_field: False})
        return {'success': True}

    def _fuse_equipment(self, player_equip_id):
        """Fuse 3 copies of an item to increase fusion level by 1 (max 3)."""
        self.ensure_one()
        item = self.env['speedrun.player.equipment'].browse(int(player_equip_id))
        if not item.exists() or item.profile_id.id != self.id:
            return {'error': 'Item not found.'}
        if item.count < 3:
            return {'error': 'Need at least 3 copies to fuse.'}
        if item.fusion_level >= 3:
            return {'error': 'This item is already at maximum fusion level (★★★).'}
        item.write({
            'count': item.count - 2,
            'fusion_level': item.fusion_level + 1,
        })
        return {
            'success': True,
            'fusion_level': item.fusion_level,
            'count': item.count,
            'item_score': item.item_score,
        }

    def _get_stats_payload(self):
        """Return a dict with all personal stats for the frontend."""
        self.ensure_one()
        bests = self.env['speedrun.personal.best'].search(
            [('user_id', '=', self.user_id.id)], order='best_time_ms asc', limit=10)
        history = self.env['speedrun.elo.history'].search(
            [('profile_id', '=', self.id)], order='create_date desc', limit=10)
        next_level_xp = (self.level ** 2) * 100
        return {
            'user_id': self.user_id.id,
            'user_name': self.user_id.name,
            'elo': self.elo,
            'peak_elo': self.peak_elo,
            'xp': self.xp,
            'level': self.level,
            'level_title': self.level_title,
            'next_level_xp': next_level_xp,
            'games_played': self.games_played,
            'games_won': self.games_won,
            'rounds_won': self.rounds_won,
            'win_rate': round(self.win_rate, 1),
            'best_time_ms': self.best_time_ms,
            'badges': [{
                'name': a.badge_id.name,
                'icon': a.badge_id.icon or '',
                'description': a.badge_id.description or '',
                'date': fields.Datetime.to_string(a.create_date),
            } for a in self.badge_award_ids],
            'best_times': [{
                'task_name': b.task_id.name,
                'best_time_ms': b.best_time_ms,
                'attempts': b.attempts,
                'wins': b.wins,
            } for b in bests],
            'elo_history': [{
                'date': fields.Datetime.to_string(h.create_date),
                'elo_before': h.elo_before,
                'elo_after': h.elo_after,
                'elo_change': h.elo_change,
            } for h in history],
            'pending_chest_count': self.pending_chest_count,
            'last_daily_chest': fields.Date.to_string(self.last_daily_chest) if self.last_daily_chest else None,
            'equipment_count': len(self.equipment_collection_ids),
            # Gear score and sets
            'gear_score': self.gear_score,
            'active_title': self.active_title or '',
            'unlocked_sets': [{'id': s.id, 'name': s.name, 'icon': s.icon or '', 'title': s.title} for s in self.unlocked_set_ids],
            # Equipped slots
            'equipped': {
                'peripheral': self._slot_payload(self.equipped_peripheral_id),
                'badge': self._slot_payload(self.equipped_badge_id),
                'module': self._slot_payload(self.equipped_module_id),
                'cosmetic': self._slot_payload(self.equipped_cosmetic_id),
            },
        }


class SpeedrunEloHistory(models.Model):
    _name = 'speedrun.elo.history'
    _description = 'Speedrun ELO History'
    _order = 'create_date desc, id desc'

    profile_id = fields.Many2one('speedrun.profile', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one(related='profile_id.user_id', store=True)
    game_id = fields.Many2one('speedrun.game', ondelete='set null')
    elo_before = fields.Integer()
    elo_after = fields.Integer()
    elo_change = fields.Integer()
