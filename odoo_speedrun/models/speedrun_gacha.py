import random

from odoo import fields, models

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
        ('peripheral', 'Peripheral'), ('badge', 'Badge'),
        ('module', 'Odoo Module'), ('cosmetic', 'Cosmetic'),
    ], default='cosmetic')


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

    _unique_per_player = models.Constraint(
        'UNIQUE(profile_id, equipment_id)',
        'A player can only have one entry per equipment.',
    )
