from odoo import fields, models


class SpeedrunGameTaskSeq(models.Model):
    """Ordered task sequence for a Time Attack game.

    All players share the same pre-generated sequence; each player advances
    through it at their own pace tracked by ``speedrun.player.ta_task_index``.
    """
    _name = 'speedrun.game.task.seq'
    _description = 'Time Attack Task Sequence'
    _order = 'game_id, sequence'

    game_id = fields.Many2one(
        'speedrun.game', required=True, ondelete='cascade', index=True)
    task_id = fields.Many2one(
        'speedrun.task', required=True, ondelete='restrict',
        string='Task')
    sequence = fields.Integer(
        required=True, default=0,
        help="0-based position in the task sequence.")
