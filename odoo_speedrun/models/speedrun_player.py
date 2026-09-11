from odoo import api, fields, models


class SpeedrunPlayer(models.Model):
    _name = 'speedrun.player'
    _description = 'Speedrun Player'
    _order = 'score desc, finish_time asc nulls last'

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
    score = fields.Integer(string='Score', default=0)
    round_wins = fields.Integer(string='Round Wins', default=0,
                                help="Number of rounds finished in 1st place.")
    dismissed = fields.Boolean(
        string='Dismissed', default=False,
        help="Set when the player leaves the final results screen (Play again). "
             "Dismissed games are no longer restored on refresh.")
    lives_remaining = fields.Integer(
        string='Lives Remaining', default=0,
        help="Battle Royale mode: number of lives left. 0 = eliminated.")

    # Time Attack fields
    ta_task_index = fields.Integer(
        string='TA Task Index', default=0,
        help="Time Attack: 0-based index of the player's current task in the shared sequence.")
    ta_completed_count = fields.Integer(
        string='TA Tasks Completed', default=0,
        help="Time Attack: number of tasks completed so far.")
    ta_last_task_time = fields.Datetime(
        string='TA Last Task Time',
        help="Time Attack: server time when the player last completed a task. "
             "Used as the start_time reference for verifying the next task.")

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
