from odoo import api, fields, models


class SpeedrunPlayer(models.Model):
    _name = 'speedrun.player'
    _description = 'Speedrun Player'
    _order = 'finish_time asc nulls last'

    game_id = fields.Many2one('speedrun.game', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', required=True, index=True)
    state = fields.Selection([
        ('waiting', 'Waiting'),
        ('playing', 'Playing'),
        ('finished', 'Finished'),
        ('dnf', 'Did Not Finish'),
    ], default='waiting', required=True)
    finish_time = fields.Datetime()
    duration_ms = fields.Integer(string='Duration (ms)', compute='_compute_duration_ms', store=True)

    _unique_player_per_game = models.Constraint(
        'UNIQUE(game_id, user_id)',
        'A user can only join a game once.',
    )

    @api.depends('finish_time', 'game_id.start_time')
    def _compute_duration_ms(self):
        for player in self:
            if player.finish_time and player.game_id.start_time:
                delta = player.finish_time - player.game_id.start_time
                player.duration_ms = int(delta.total_seconds() * 1000)
            else:
                player.duration_ms = 0
