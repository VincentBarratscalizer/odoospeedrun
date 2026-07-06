from datetime import timedelta

from odoo import fields
from odoo.tests.common import TransactionCase


class SpeedrunCommon(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        group_user = cls.env.ref('base.group_user')
        player_group = cls.env.ref('odoo_speedrun.group_speedrun_player')
        cls.user_a = cls.env['res.users'].create({
            'name': 'Speedrunner Alpha',
            'login': 'speedrun_alpha',
            'email': 'alpha@example.com',
            'group_ids': [(6, 0, [group_user.id, player_group.id])],
        })
        cls.user_b = cls.env['res.users'].create({
            'name': 'Speedrunner Bravo',
            'login': 'speedrun_bravo',
            'email': 'bravo@example.com',
            'group_ids': [(6, 0, [group_user.id, player_group.id])],
        })
        cls.user_c = cls.env['res.users'].create({
            'name': 'Speedrunner Charlie',
            'login': 'speedrun_charlie',
            'email': 'charlie@example.com',
            'group_ids': [(6, 0, [group_user.id, player_group.id])],
        })
        # A trivially-verifiable task (there is always at least 1 user)
        cls.task = cls.env['speedrun.task'].create({
            'name': 'Trivial Test Task',
            'target_model': 'res.users',
            'verification_method': 'domain',
            'verification_domain': '[]',
            'verification_count': 1,
            'difficulty': 'easy',
        })
        # Make task picking deterministic and always verifiable
        cls.env['speedrun.task'].search([('id', '!=', cls.task.id)]).write({'active': False})

    def _play_game(self, users_in_finish_order, total_rounds=1):
        """Create and fully play a game. Players finish rounds in the given order."""
        host = users_in_finish_order[0]
        game = self.env['speedrun.game'].with_user(host).create({
            'total_rounds': total_rounds,
        })
        for user in users_in_finish_order[1:]:
            game.action_join(user_id=user.id)
        for rnd in range(total_rounds):
            if rnd == 0:
                game.with_user(host).action_start()
            else:
                game.with_user(host).action_next_round()
            game.with_user(host).action_begin()
            # Odoo datetimes are second-precision: backdate the start so
            # instantly-completed test rounds still get a duration > 0
            # (45s: above the speed-badge thresholds to keep XP deterministic).
            game.sudo().write({
                'start_time': fields.Datetime.now() - timedelta(seconds=45),
            })
            for user in users_in_finish_order:
                result = game.with_user(user).action_check_completion()
                self.assertTrue(result.get('success'), result)
        self.assertEqual(game.state, 'finished')
        return game

    def _get_profile(self, user):
        return self.env['speedrun.profile'].search([('user_id', '=', user.id)])
