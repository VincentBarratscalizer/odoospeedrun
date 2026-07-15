from odoo.tests import tagged

from .common import SpeedrunCommon


@tagged('post_install', '-at_install', 'speedrun')
class TestPersonalBest(SpeedrunCommon):

    def _make_result(self, game, user, task, round_number, rank, duration_ms):
        return self.env['speedrun.round.result'].create({
            'game_id': game.id,
            'round_number': round_number,
            'task_id': task.id,
            'user_id': user.id,
            'rank': rank,
            'duration_ms': duration_ms,
            'points': {1: 3, 2: 2, 3: 1}.get(rank, 0),
        })

    def test_best_time_per_task(self):
        """The personal best view aggregates per user and per task."""
        game = self.env['speedrun.game'].with_user(self.user_a).create({})
        task2 = self.env['speedrun.task'].create({
            'name': 'Second Task',
            'target_model': 'res.users',
            'verification_domain': '[]',
        })
        # user_a: two attempts on task 1 (best 20s), one on task 2
        self._make_result(game, self.user_a, self.task, 1, 1, 30000)
        self._make_result(game, self.user_a, self.task, 2, 2, 20000)
        self._make_result(game, self.user_a, task2, 3, 1, 45000)
        # DNF results are excluded
        self._make_result(game, self.user_a, self.task, 3, 0, 0)
        # user_b results don't leak into user_a's bests
        self._make_result(game, self.user_b, self.task, 1, 2, 15000)

        bests_a = self.env['speedrun.personal.best'].search([('user_id', '=', self.user_a.id)])
        self.assertEqual(len(bests_a), 2, "One row per task")
        best_task1 = bests_a.filtered(lambda b: b.task_id == self.task)
        self.assertEqual(best_task1.best_time_ms, 20000)
        self.assertEqual(best_task1.avg_time_ms, 25000)
        self.assertEqual(best_task1.attempts, 2, "DNF attempts are excluded")
        self.assertEqual(best_task1.wins, 1)
        best_task2 = bests_a.filtered(lambda b: b.task_id == task2)
        self.assertEqual(best_task2.best_time_ms, 45000)

        bests_b = self.env['speedrun.personal.best'].search([('user_id', '=', self.user_b.id)])
        self.assertEqual(len(bests_b), 1)
        self.assertEqual(bests_b.best_time_ms, 15000)

    def test_populated_by_real_game(self):
        """Playing a real game feeds the personal best view."""
        self._play_game([self.user_a, self.user_b], total_rounds=1)
        bests = self.env['speedrun.personal.best'].search([('user_id', '=', self.user_a.id)])
        self.assertEqual(len(bests), 1)
        self.assertEqual(bests.task_id, self.task)
        self.assertGreater(bests.best_time_ms, 0)
        self.assertEqual(bests.wins, 1)
