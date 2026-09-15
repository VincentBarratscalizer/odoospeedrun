from odoo.tests.common import tagged

from .common import SpeedrunCommon


@tagged('post_install', '-at_install')
class TestClass(SpeedrunCommon):

    def setUp(self):
        super().setUp()
        self.profile = self.env['speedrun.profile']._get_or_create(self.user_a)

    def test_class_info_payload(self):
        info = self.profile._class_info_payload()
        self.assertEqual(len(info['classes']), 6)
        badge = next(c for c in info['classes'] if c['element'] == 'badge')
        self.assertIn('Sales', badge['categories'])

    def test_upgrade_with_coins(self):
        self.profile.coins = 100000
        base_pp = self.profile._passive_power('badge')
        result = self.profile._upgrade_class('badge')
        self.assertTrue(result.get('success'))
        self.assertEqual(result['level'], 1)
        self.assertGreater(self.profile._passive_power('badge'), base_pp)

    def test_upgrade_not_enough_coins(self):
        self.profile.coins = 0
        result = self.profile._upgrade_class('badge')
        self.assertTrue(result.get('error'))
        self.assertEqual(self.profile.class_level_badge, 0)

    def test_percentile_and_domain_rating(self):
        Score = self.env['speedrun.task.score']
        # A fast time for user_a, a slow one for user_b, on the same task.
        Score.create({'user_id': self.user_a.id, 'task_id': self.task.id, 'best_time_ms': 10000})
        Score.create({'user_id': self.user_b.id, 'task_id': self.task.id, 'best_time_ms': 30000})
        pa = self.profile._percentile_for_task(self.task.id, 10000)
        self.assertEqual(round(pa), 100)
        # The test task belongs to no category by default; force one for the test.
        group = self.env['speedrun.task.group'].create({'name': 'Sales-Test'})
        self.task.group_ids = [(4, group.id)]
        rating = self.profile._domain_rating(['Sales-Test'])
        self.assertGreater(rating, 0)
