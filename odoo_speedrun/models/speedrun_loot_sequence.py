import random

from odoo import api, fields, models

# Emoji shown for a chest reward, by rarity.
CHEST_EMOJI = {'common': '📦', 'rare': '🎁', 'epic': '💎', 'legendary': '👑'}
RARITY_SEL = [('common', 'Common'), ('rare', 'Rare'), ('epic', 'Epic'), ('legendary', 'Legendary')]


class SpeedrunLootSequence(models.Model):
    _name = 'speedrun.loot.sequence'
    _description = 'Weekly Login Reward Sequence (7 days)'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    day_ids = fields.One2many('speedrun.loot.sequence.day', 'sequence_id', string='Days')
    day_count = fields.Integer(compute='_compute_day_count', store=True)

    @api.depends('day_ids')
    def _compute_day_count(self):
        for seq in self:
            seq.day_count = len(seq.day_ids)

    @api.model
    def _pick_random(self):
        """Return a random usable 7-day sequence (or empty recordset)."""
        candidates = self.search([('active', '=', True)]).filtered(
            lambda s: s.day_count >= 7)
        if not candidates:
            # Fall back to any sequence that at least defines day 1.
            candidates = self.search([('active', '=', True)]).filtered(
                lambda s: s.day_ids)
        if not candidates:
            return self.browse()
        return self.browse(random.choice(candidates.ids))

    def _day(self, day):
        """Return the reward record for a given day number (1-7)."""
        self.ensure_one()
        return self.day_ids.filtered(lambda d: d.day == day)[:1]


class SpeedrunLootSequenceDay(models.Model):
    _name = 'speedrun.loot.sequence.day'
    _description = 'Weekly Login Reward — one day'
    _order = 'sequence_id, day'

    sequence_id = fields.Many2one(
        'speedrun.loot.sequence', required=True, ondelete='cascade', index=True)
    day = fields.Integer(required=True, help="Day number in the cycle (1-7).")
    reward_type = fields.Selection([
        ('chest', 'Chest'),
        ('equipment', 'Equipment'),
    ], required=True, default='chest')
    chest_rarity = fields.Selection(RARITY_SEL, default='common', string='Chest Rarity')
    equipment_id = fields.Many2one(
        'speedrun.equipment', string='Specific Equipment',
        help="Grant this exact item. Leave empty to draw a random item of the "
             "rarity below.")
    equipment_rarity = fields.Selection(
        RARITY_SEL, default='rare', string='Random Equipment Rarity')
    coins = fields.Integer(string='Bonus Coins', default=0)

    _unique_day = models.Constraint(
        'UNIQUE(sequence_id, day)',
        'Each day of a sequence must be unique.',
    )

    # ------------------------------------------------------------------
    def _display(self):
        """Small {icon, label} descriptor for the frontend track."""
        self.ensure_one()
        if self.reward_type == 'chest':
            r = self.chest_rarity or 'common'
            return {'icon': CHEST_EMOJI.get(r, '📦'), 'label': 'Coffre %s' % r}
        if self.equipment_id:
            return {'icon': self.equipment_id.icon or '⚔️', 'label': self.equipment_id.name}
        return {'icon': '⚔️', 'label': 'Équipement %s' % (self.equipment_rarity or 'rare')}

    def _grant(self, profile):
        """Grant this day's reward to a player's profile; return a result dict."""
        self.ensure_one()
        result = {}
        if self.reward_type == 'chest':
            chest = profile._award_chest(self.chest_rarity or 'common', source='daily_streak')
            result = {'type': 'chest', 'rarity': chest.rarity,
                      'icon': CHEST_EMOJI.get(chest.rarity, '📦')}
        else:
            equipment = self.equipment_id
            if not equipment:
                pool = self.env['speedrun.equipment'].sudo().search(
                    [('rarity', '=', self.equipment_rarity or 'rare')])
                if pool:
                    equipment = self.env['speedrun.equipment'].browse(random.choice(pool.ids))
            if equipment:
                profile._grant_equipment(equipment)
                result = {'type': 'equipment', 'name': equipment.name,
                          'rarity': equipment.rarity, 'icon': equipment.icon or '⚔️'}
                profile.user_id._bus_send('speedrun/streak_reward', {
                    'day': self.day, 'reward': result,
                })
            else:
                chest = profile._award_chest('rare', source='daily_streak')
                result = {'type': 'chest', 'rarity': chest.rarity,
                          'icon': CHEST_EMOJI.get(chest.rarity, '📦')}
        if self.coins:
            profile._add_coins(self.coins)
            result['coins'] = self.coins
        return result
