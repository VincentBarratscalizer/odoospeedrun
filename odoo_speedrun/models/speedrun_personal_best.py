from odoo import fields, models, tools


class SpeedrunPersonalBest(models.Model):
    _name = 'speedrun.personal.best'
    _description = 'Speedrun Personal Best Times'
    _auto = False
    _order = 'best_time_ms asc'

    user_id = fields.Many2one('res.users', string='Player', readonly=True)
    task_id = fields.Many2one('speedrun.task', string='Task', readonly=True)
    best_time_ms = fields.Integer(string='Best Time (ms)', readonly=True)
    avg_time_ms = fields.Integer(string='Avg Time (ms)', readonly=True)
    attempts = fields.Integer(string='Attempts', readonly=True)
    wins = fields.Integer(string='Round Wins', readonly=True)
    last_played = fields.Datetime(string='Last Played', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    MIN(rr.id) AS id,
                    rr.user_id,
                    rr.task_id,
                    MIN(rr.duration_ms) AS best_time_ms,
                    CAST(AVG(rr.duration_ms) AS int) AS avg_time_ms,
                    COUNT(*) AS attempts,
                    COUNT(*) FILTER (WHERE rr.rank = 1) AS wins,
                    MAX(rr.create_date) AS last_played
                FROM speedrun_round_result rr
                WHERE rr.rank > 0
                  AND rr.duration_ms > 0
                  AND rr.task_id IS NOT NULL
                GROUP BY rr.user_id, rr.task_id
            )
        """ % self._table)
