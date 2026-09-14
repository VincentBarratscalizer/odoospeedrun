from odoo import api, fields, models

# ELO K-factor for the per-task ranking (a bit gentler than the global one).
TASK_K_FACTOR = 24


class SpeedrunTaskScore(models.Model):
    """Per-player, per-task ELO rating.

    Every time a task is played in a round, the participants' ratings for
    *that* task are adjusted against each other (multiplayer ELO on the round
    standings). This yields a separate leaderboard for each task, updated day
    after day as people keep racing.
    """
    _name = 'speedrun.task.score'
    _description = 'Speedrun Per-Task ELO Score'
    _order = 'elo desc'
    _rec_name = 'task_id'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    task_id = fields.Many2one('speedrun.task', required=True, index=True, ondelete='cascade')
    elo = fields.Integer(string='Task ELO', default=1000)
    peak_elo = fields.Integer(string='Peak Task ELO', default=1000)
    rounds_played = fields.Integer(default=0)
    rounds_won = fields.Integer(default=0)
    best_time_ms = fields.Integer(string='Best Time (ms)', default=0)
    last_played = fields.Date()

    _unique_user_task = models.Constraint(
        'UNIQUE(user_id, task_id)',
        'A player can only have one score entry per task.',
    )

    @api.model
    def _get_map(self, user_ids, task_id):
        """Return {user_id: record}, creating missing entries."""
        existing = self.search([
            ('user_id', 'in', list(user_ids)),
            ('task_id', '=', task_id),
        ])
        by_user = {r.user_id.id: r for r in existing}
        missing = [uid for uid in user_ids if uid not in by_user]
        if missing:
            created = self.create([
                {'user_id': uid, 'task_id': task_id} for uid in missing
            ])
            for r in created:
                by_user[r.user_id.id] = r
        return by_user

    @api.model
    def _update_from_game(self, game):
        """Update per-task ELO from every round played in a finished game."""
        today = fields.Date.today()
        results = game.round_result_ids.filtered(lambda r: r.task_id)
        RoundResult = self.env['speedrun.round.result']
        # Group round results by (round number, task).
        rounds = {}
        for r in results:
            key = (r.round_number, r.task_id.id)
            rounds.setdefault(key, RoundResult)
            rounds[key] |= r

        for (_rnum, task_id), rrs in rounds.items():
            # Comparable standing score: finished rounds beat DNF (rank 0).
            standing = {
                r.user_id.id: (1000 - r.rank) if r.rank > 0 else -1
                for r in rrs
            }
            recs = self._get_map(set(standing), task_id)
            elos = {uid: recs[uid].elo for uid in recs}
            n = len(recs)
            for r in rrs:
                uid = r.user_id.id
                change = 0
                if n >= 2:
                    delta = 0.0
                    for other in recs:
                        if other == uid:
                            continue
                        expected = 1.0 / (1.0 + 10 ** ((elos[other] - elos[uid]) / 400.0))
                        if standing[uid] > standing[other]:
                            actual = 1.0
                        elif standing[uid] < standing[other]:
                            actual = 0.0
                        else:
                            actual = 0.5
                        delta += actual - expected
                    change = round(TASK_K_FACTOR * delta / (n - 1))
                rec = recs[uid]
                new_elo = rec.elo + change
                vals = {
                    'elo': new_elo,
                    'peak_elo': max(rec.peak_elo, new_elo),
                    'rounds_played': rec.rounds_played + 1,
                    'last_played': today,
                }
                if r.rank == 1:
                    vals['rounds_won'] = rec.rounds_won + 1
                if r.duration_ms and (not rec.best_time_ms or r.duration_ms < rec.best_time_ms):
                    vals['best_time_ms'] = r.duration_ms
                rec.write(vals)
