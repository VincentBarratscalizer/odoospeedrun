from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import SpeedrunCommon


@tagged('post_install', '-at_install')
class TestClanWar(SpeedrunCommon):

    def setUp(self):
        super().setUp()
        Clan = self.env['speedrun.clan']
        self.clan_a = Clan.with_user(self.user_a)._create_clan('Alpha', 'ALP')
        self.clan_b = Clan.with_user(self.user_b)._create_clan('Bravo', 'BRV')
        self.War = self.env['speedrun.clan.war']

    def _running_war(self):
        war = self.War.with_user(self.user_a)._declare(self.clan_b.id)
        war.with_user(self.user_b)._accept()
        return war

    def test_declare_requires_leader(self):
        # user_c is in no clan -> cannot declare
        with self.assertRaises(UserError):
            self.War.with_user(self.user_c)._declare(self.clan_b.id)

    def test_declare_and_accept(self):
        war = self.War.with_user(self.user_a)._declare(self.clan_b.id)
        self.assertEqual(war.state, 'declared')
        self.assertTrue(war.accept_deadline)
        war.with_user(self.user_b)._accept()
        self.assertEqual(war.state, 'running')
        self.assertTrue(war.raid_task_id)
        self.assertTrue(war.blitz_at)

    def test_decline(self):
        war = self.War.with_user(self.user_a)._declare(self.clan_b.id)
        war.with_user(self.user_b)._decline()
        self.assertEqual(war.state, 'declined')

    def test_no_double_war(self):
        self.War.with_user(self.user_a)._declare(self.clan_b.id)
        with self.assertRaises(UserError):
            self.War.with_user(self.user_a)._declare(self.clan_b.id)

    def test_raid_task_flow(self):
        war = self._running_war()
        res = war.with_user(self.user_a)._task_start('raid')
        self.assertEqual(res['my_raid']['status'], 'in_progress')
        # The raid task is the trivial always-verifiable test task.
        res = war.with_user(self.user_a)._task_check('raid')
        self.assertTrue(res.get('success'))

    def test_arena_fight(self):
        war = self._running_war()
        replay = war.with_user(self.user_a)._arena_fight()
        self.assertIn('winner', replay)
        # a second attack is blocked
        second = war.with_user(self.user_a)._arena_fight()
        self.assertTrue(second.get('error'))

    def test_close_decides_winner_and_rewards(self):
        war = self._running_war()
        # Clan A completes the raid; nobody in B -> A wins raid.
        war.with_user(self.user_a)._task_start('raid')
        war.result_ids.sudo().write({
            'completed': True, 'duration_ms': 5000,
            'finish_time': fields.Datetime.now(),
        })
        # A attacks in the arena and (vs an equal fresh clan) at least fights.
        war.with_user(self.user_a)._arena_fight()
        elo_before = self.clan_a.clan_elo
        war._close()
        self.assertEqual(war.state, 'finished')
        self.assertTrue(war.winner_clan_id)
        self.assertIn(war.winner_clan_id, (self.clan_a, self.clan_b))
        # ELO moved for both clans
        self.assertNotEqual(self.clan_a.clan_elo, elo_before)

    def test_cron_expires_stale_declaration(self):
        war = self.War.with_user(self.user_a)._declare(self.clan_b.id)
        war.sudo().accept_deadline = fields.Datetime.subtract(fields.Datetime.now(), hours=1)
        self.War._cron_process_wars()
        self.assertEqual(war.state, 'cancelled')
