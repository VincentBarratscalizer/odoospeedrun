from odoo import fields
from odoo.tests.common import tagged

from .common import SpeedrunCommon


@tagged('post_install', '-at_install')
class TestWeeklyReward(SpeedrunCommon):

    def setUp(self):
        super().setUp()
        self.profile = self.env['speedrun.profile']._get_or_create(self.user_a)
        self.profile.write({'loot_sequence_id': False, 'loot_day': 0, 'loot_last_claim': False})
        self.today = fields.Date.today()
        self.yesterday = fields.Date.subtract(self.today, days=1)

    def test_first_claim_starts_cycle(self):
        reward = self.profile._advance_weekly_reward()
        self.assertTrue(reward)
        self.assertEqual(reward['day'], 1)
        self.assertTrue(reward['is_new_cycle'])
        self.assertEqual(self.profile.loot_day, 1)

    def test_continue_next_day(self):
        self.profile._advance_weekly_reward()
        self.profile.loot_last_claim = self.yesterday
        reward = self.profile._advance_weekly_reward()
        self.assertEqual(reward['day'], 2)
        self.assertFalse(reward['is_new_cycle'])

    def test_same_day_no_double(self):
        self.profile._advance_weekly_reward()
        self.assertIsNone(self.profile._advance_weekly_reward())

    def test_missed_day_resets(self):
        self.profile.write({
            'loot_day': 4,
            'loot_last_claim': fields.Date.subtract(self.today, days=3),
        })
        reward = self.profile._advance_weekly_reward()
        self.assertEqual(reward['day'], 1)
        self.assertTrue(reward['is_new_cycle'])

    def test_rewards_visible_in_advance(self):
        payload = self.profile._weekly_reward_payload()
        self.assertTrue(payload['known'])
        self.assertEqual(len(payload['days']), 7)
        # every slot shows a concrete reward, not a surprise
        self.assertTrue(all(d['label'] and d['label'] != 'Surprise' for d in payload['days']))

    def test_preview_is_honored_on_claim(self):
        payload = self.profile._weekly_reward_payload()
        preview_seq = payload['sequence_name']
        self.profile._advance_weekly_reward()
        self.assertEqual(self.profile.loot_sequence_id.name, preview_seq)
