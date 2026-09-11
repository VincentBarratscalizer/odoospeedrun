import random

from odoo import api, fields, models

RARITY_LABELS = {'common': 'Common', 'rare': 'Rare', 'epic': 'Epic', 'legendary': 'Legendary'}

# Chest drop tables: chest_rarity → {item_rarity: weight}
CHEST_DROP_TABLES = {
    'common':    {'common': 70, 'rare': 25, 'epic': 4,  'legendary': 1},
    'rare':      {'common': 30, 'rare': 50, 'epic': 17, 'legendary': 3},
    'epic':      {'common': 10, 'rare': 35, 'epic': 42, 'legendary': 13},
    'legendary': {'common': 5,  'rare': 20, 'epic': 40, 'legendary': 35},
}

# Chest rarity awarded by finishing position (0-indexed in sorted standings)
CHEST_BY_RANK = {0: 'legendary', 1: 'epic', 2: 'rare'}
DEFAULT_CHEST = 'common'

RARITY_SEL = [('common', 'Common'), ('rare', 'Rare'), ('epic', 'Epic'), ('legendary', 'Legendary')]


class SpeedrunEquipment(models.Model):
    _name = 'speedrun.equipment'
    _description = 'Speedrun Equipment Item'
    _order = 'rarity desc, name'

    name = fields.Char(required=True)
    rarity = fields.Selection(RARITY_SEL, required=True, default='common')
    icon = fields.Char(string='Icon (emoji)')
    description = fields.Char()
    category = fields.Selection([
        ('peripheral', 'Périphérique'),  # keyboard, mouse, headphones, controller, mousepad
        ('display', 'Écran'),            # monitors, webcam, phone stand
        ('tech', 'Hardware'),            # SSD, cooling, USB, power, WiFi, laptop, printer, lamp, stand
        ('badge', 'Badge'),              # medals, trophies, crowns, achievement badges
        ('module', 'Module Odoo'),       # CRM ball, DevMode, dashboard, module key
        ('desk', 'Bureau'),              # office supplies + cosmetics: notepad, pen, coffee, hoodie, etc.
    ], default='desk')
    set_ids = fields.Many2many(
        'speedrun.equipment.set',
        'speedrun_equipment_set_item_rel', 'equipment_id', 'set_id',
        string='Panoplies',
    )


class SpeedrunEquipmentSet(models.Model):
    _name = 'speedrun.equipment.set'
    _description = 'Equipment Panoplie'
    _order = 'sequence, name'

    name = fields.Char(required=True)
    icon = fields.Char()
    title = fields.Char(required=True, string='Reward Title')
    description = fields.Char()
    sequence = fields.Integer(default=10)
    item_ids = fields.Many2many(
        'speedrun.equipment',
        'speedrun_equipment_set_item_rel', 'set_id', 'equipment_id',
        string='Items',
    )
    score_bonus = fields.Integer(default=0, string='GS Bonus')
    item_count = fields.Integer(compute='_compute_item_count')

    @api.depends('item_ids')
    def _compute_item_count(self):
        for s in self:
            s.item_count = len(s.item_ids)


class SpeedrunPlayerChest(models.Model):
    _name = 'speedrun.player.chest'
    _description = 'Player Chest'
    _order = 'create_date desc'

    profile_id = fields.Many2one('speedrun.profile', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one(related='profile_id.user_id', store=True, index=True)
    rarity = fields.Selection(RARITY_SEL, required=True, default='common')
    state = fields.Selection([('pending', 'Pending'), ('opened', 'Opened')], default='pending', required=True)
    equipment_id = fields.Many2one('speedrun.equipment', readonly=True, ondelete='set null')
    game_id = fields.Many2one('speedrun.game', ondelete='set null')
    source = fields.Selection([('game_win', 'Game Win'), ('daily', 'Daily Reward')], default='game_win', required=True)


class SpeedrunPlayerEquipment(models.Model):
    _name = 'speedrun.player.equipment'
    _description = 'Player Equipment Collection'
    _order = 'rarity desc, create_date desc'
    _rec_name = 'equipment_id'

    profile_id = fields.Many2one('speedrun.profile', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one(related='profile_id.user_id', store=True, index=True)
    equipment_id = fields.Many2one('speedrun.equipment', required=True, ondelete='cascade')
    rarity = fields.Selection(RARITY_SEL, related='equipment_id.rarity', store=True)
    count = fields.Integer(default=1)
    fusion_level = fields.Integer(default=0, string='Fusion Level')  # 0-3
    item_score = fields.Integer(compute='_compute_item_score', store=True)

    _unique_per_player = models.Constraint(
        'UNIQUE(profile_id, equipment_id)',
        'A player can only have one entry per equipment.',
    )

    @api.depends('rarity', 'fusion_level')
    def _compute_item_score(self):
        RARITY_SCORE = {'common': 10, 'rare': 50, 'epic': 200, 'legendary': 1000}
        for item in self:
            base = RARITY_SCORE.get(item.rarity, 0)
            multiplier = 1.0 + item.fusion_level * 0.5
            item.item_score = int(base * multiplier)
