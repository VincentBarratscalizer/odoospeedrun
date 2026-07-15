from odoo import fields, models, tools


class SpeedrunLeaderboard(models.Model):
    _name = 'speedrun.leaderboard'
    _description = 'Speedrun Leaderboard'
    _auto = False
    _order = 'total_wins desc, win_rate desc'

    user_id = fields.Many2one('res.users', string='Player', readonly=True)
    total_games = fields.Integer(string='Games Played', readonly=True)
    total_wins = fields.Integer(string='Wins', readonly=True)
    best_time_ms = fields.Integer(string='Best Time (ms)', readonly=True)
    avg_time_ms = fields.Integer(string='Avg Time (ms)', readonly=True)
    win_rate = fields.Float(string='Win Rate (%)', readonly=True)

    def init(self):
        tools.drop_view_if_exists(self.env.cr, self._table)
        self.env.cr.execute("""
            CREATE OR REPLACE VIEW %s AS (
                SELECT
                    p.user_id AS id,
                    p.user_id,
                    COUNT(*) AS total_games,
                    COUNT(*) FILTER (WHERE g.winner_id = p.user_id) AS total_wins,
                    MIN(p.duration_ms) FILTER (WHERE p.state = 'finished' AND p.duration_ms > 0) AS best_time_ms,
                    CAST(AVG(p.duration_ms) FILTER (WHERE p.state = 'finished' AND p.duration_ms > 0) AS int) AS avg_time_ms,
                    COALESCE(
                        COUNT(*) FILTER (WHERE g.winner_id = p.user_id) * 100.0
                        / NULLIF(COUNT(*), 0), 0
                    ) AS win_rate
                FROM speedrun_player p
                JOIN speedrun_game g ON g.id = p.game_id
                WHERE g.state = 'finished'
                GROUP BY p.user_id
            )
        """ % self._table)
