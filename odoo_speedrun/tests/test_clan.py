from odoo.exceptions import UserError
from odoo.tests.common import tagged

from .common import SpeedrunCommon


@tagged('post_install', '-at_install')
class TestClan(SpeedrunCommon):

    def _clan(self, user, name, tag):
        return self.env['speedrun.clan'].with_user(user)._create_clan(name, tag)

    def test_create_and_join(self):
        clan = self._clan(self.user_a, 'Alpha Squad', 'ALP')
        self.assertEqual(clan.leader_id, self.user_a)
        self.assertEqual(clan.member_count, 1)
        # user_b joins
        clan.with_user(self.user_b)._join()
        self.assertEqual(clan.member_count, 2)
        self.assertIn(self.user_b, clan.member_profile_ids.user_id)

    def test_cannot_create_twice(self):
        self._clan(self.user_a, 'Alpha', 'ALP')
        with self.assertRaises(UserError):
            self._clan(self.user_a, 'Beta', 'BET')

    def test_tag_validation(self):
        with self.assertRaises(UserError):
            self._clan(self.user_a, 'Alpha', 'A')  # tag too short

    def test_kick_member(self):
        clan = self._clan(self.user_a, 'Alpha', 'ALP')
        clan.with_user(self.user_b)._join()
        prof_b = self._get_profile(self.user_b)
        clan.with_user(self.user_a)._kick(prof_b.id)
        self.assertEqual(clan.member_count, 1)
        self.assertFalse(prof_b.clan_id)

    def test_member_cannot_kick(self):
        clan = self._clan(self.user_a, 'Alpha', 'ALP')
        clan.with_user(self.user_b)._join()
        prof_a = self._get_profile(self.user_a)
        with self.assertRaises(UserError):
            clan.with_user(self.user_b)._kick(prof_a.id)

    def test_transfer_lead(self):
        clan = self._clan(self.user_a, 'Alpha', 'ALP')
        clan.with_user(self.user_b)._join()
        prof_b = self._get_profile(self.user_b)
        clan.with_user(self.user_a)._transfer_lead(prof_b.id)
        self.assertEqual(clan.leader_id, self.user_b)
        self.assertEqual(prof_b.clan_role, 'leader')

    def test_leader_leaves_promotes_heir(self):
        clan = self._clan(self.user_a, 'Alpha', 'ALP')
        clan.with_user(self.user_b)._join()
        clan.with_user(self.user_a)._leave()
        self.assertEqual(clan.member_count, 1)
        self.assertEqual(clan.leader_id, self.user_b)

    def test_last_member_leaving_disbands(self):
        clan = self._clan(self.user_a, 'Solo', 'SOL')
        clan_id = clan.id
        clan.with_user(self.user_a)._leave()
        self.assertFalse(self.env['speedrun.clan'].browse(clan_id).exists())

    def test_leaderboard_rows(self):
        clan = self._clan(self.user_a, 'Alpha', 'ALP')
        clan.wars_played = 1
        rows = self.env['speedrun.clan']._leaderboard_rows()
        self.assertTrue(any(r['tag'] == 'ALP' for r in rows))
