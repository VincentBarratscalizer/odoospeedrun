from odoo import fields, models


class SpeedrunRoundResult(models.Model):
    _name = 'speedrun.round.result'
    _description = 'Speedrun Round Result'
    _order = 'game_id, round_number, rank'

    game_id = fields.Many2one('speedrun.game', required=True, ondelete='cascade', index=True)
    round_number = fields.Integer(required=True)
    task_id = fields.Many2one('speedrun.task', string='Task')
    user_id = fields.Many2one('res.users', required=True)
    rank = fields.Integer(help="Finishing position (1=first, 0=DNF)")
    duration_ms = fields.Integer(string='Duration (ms)')
    points = fields.Integer(string='Points Earned')
