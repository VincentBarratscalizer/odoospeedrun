from datetime import timedelta

from odoo import fields
from odoo.tests.common import tagged

from .common import SpeedrunCommon


@tagged('post_install', '-at_install')
class TestBoss(SpeedrunCommon):

    def setUp(self):
        super().setUp()
        self.Boss = self.env['speedrun.boss']
        self.boss = self.Boss.search([('active', '=', True)], order='sequence', limit=1)
        self.assertTrue(self.boss, "The boss ladder data should be installed.")
        self.profile = self.env['speedrun.profile']._get_or_create(self.user_a)

    def test_ladder_status(self):
        payload = self.Boss._ladder_payload(self.user_a)
        self.assertTrue(payload['total'] >= 1)
        self.assertEqual(payload['current']['id'], self.boss.id)
        # bosses after the current one are locked
        others = [b for b in payload['bosses'] if b['id'] != self.boss.id]
        if others:
            self.assertTrue(all(b['status'] in ('locked', 'defeated') for b in others))

    def test_fight_returns_replay(self):
        result = self.boss._fight(self.profile)
        self.assertIn('winner', result)
        self.assertIn('boss_result', result)

    def test_epreuve_success(self):
        self.boss.write({'challenge_type': 'time', 'time_limit_ms': 240000})
        self.boss._epreuve_start(self.user_a)
        result = self.boss._epreuve_check(self.user_a)
        self.assertTrue(result.get('success'))
        self.assertTrue(result['epreuve_done'])

    def test_epreuve_timeout_consumes_attempt(self):
        self.boss.write({'time_limit_ms': 1000, 'epreuve_attempts': 2})
        self.boss._epreuve_start(self.user_a)
        prog = self.boss._progress(self.user_a)
        prog.epreuve_start_time = fields.Datetime.now() - timedelta(seconds=5)
        result = self.boss._epreuve_timeout(self.user_a)
        self.assertTrue(result.get('attempt_failed'))
        self.assertEqual(result['attempts'], 1)

    def test_boss_wins_triggers_cooldown(self):
        self.boss.write({'time_limit_ms': 1000, 'epreuve_attempts': 1, 'epreuve_cooldown_min': 30})
        self.boss._epreuve_start(self.user_a)
        prog = self.boss._progress(self.user_a)
        prog.epreuve_start_time = fields.Datetime.now() - timedelta(seconds=5)
        result = self.boss._epreuve_timeout(self.user_a)
        self.assertTrue(result.get('boss_won'))
        self.assertGreater(result['cooldown_remaining'], 0)
        # combat is blocked during cooldown
        fight = self.boss._fight(self.profile)
        self.assertTrue(fight.get('error'))

    def test_cooldown_recovers_and_resets_attempts(self):
        self.boss.write({'epreuve_attempts': 3})
        prog = self.boss._progress(self.user_a, create=True)
        prog.write({
            'cooldown_until': fields.Datetime.now() - timedelta(seconds=1),
            'attempts_left': 0,
        })
        self.boss._recover_cooldown(prog)
        self.assertFalse(prog.cooldown_until)
        self.assertEqual(prog.attempts_left, 3)

    def test_defeat_grants_reward_and_advances(self):
        self.boss.write({'challenge_type': 'time', 'time_limit_ms': 240000,
                         'reward_coins': 300})
        prog = self.boss._progress(self.user_a, create=True)
        prog.combat_done = True
        coins_before = self.profile.coins
        self.boss._epreuve_start(self.user_a)
        result = self.boss._epreuve_check(self.user_a)
        self.assertTrue(result.get('defeated'))
        self.assertEqual(self.profile.coins, coins_before + 300)
        # the ladder now points to a different (next) boss, or is cleared
        payload = self.Boss._ladder_payload(self.user_a)
        current = payload['current']
        self.assertTrue(current is None or current['id'] != self.boss.id)
        self.assertEqual(payload['defeated_count'], 1)
