from odoo.tests import tagged

from .common import SpeedrunCommon


@tagged('post_install', '-at_install', 'speedrun')
class TestBadges(SpeedrunCommon):

    def test_badges_awarded_after_game(self):
        """First game/first win badges are awarded automatically at game end."""
        self._play_game([self.user_a, self.user_b], total_rounds=1)
        profile_a = self._get_profile(self.user_a)
        profile_b = self._get_profile(self.user_b)

        badges_a = profile_a.badge_award_ids.badge_id
        badges_b = profile_b.badge_award_ids.badge_id
        first_game = self.env.ref('odoo_speedrun.badge_first_game')
        first_win = self.env.ref('odoo_speedrun.badge_first_win')

        self.assertIn(first_game, badges_a)
        self.assertIn(first_win, badges_a, "Winner earns First Victory")
        self.assertIn(first_game, badges_b)
        self.assertNotIn(first_win, badges_b, "Loser does not earn First Victory")

    def test_badge_xp_reward(self):
        """Earning a badge grants its XP reward on top of game XP."""
        self._play_game([self.user_a, self.user_b], total_rounds=1)
        profile_b = self._get_profile(self.user_b)
        # b base XP: 2 pts * 15 + 10 = 40; + First Steps badge (25) = 65
        first_game = self.env.ref('odoo_speedrun.badge_first_game')
        self.assertEqual(profile_b.xp, 40 + first_game.xp_reward)

    def test_badge_awarded_once(self):
        """A badge is never awarded twice to the same player."""
        self._play_game([self.user_a, self.user_b], total_rounds=1)
        self._play_game([self.user_a, self.user_b], total_rounds=1)
        profile_a = self._get_profile(self.user_a)
        first_win = self.env.ref('odoo_speedrun.badge_first_win')
        awards = profile_a.badge_award_ids.filtered(lambda a: a.badge_id == first_win)
        self.assertEqual(len(awards), 1)

    def test_criteria_matching(self):
        """Each criteria type matches against the right profile field."""
        Badge = self.env['speedrun.badge']
        profile = self.env['speedrun.profile'].create({
            'user_id': self.user_c.id,
            'elo': 1250,
            'xp': 400,  # level 3
            'games_played': 12,
            'games_won': 4,
            'rounds_won': 30,
            'best_time_ms': 25000,
        })
        cases = [
            ({'criteria_type': 'games_played', 'threshold': 10}, True),
            ({'criteria_type': 'games_played', 'threshold': 20}, False),
            ({'criteria_type': 'games_won', 'threshold': 4}, True),
            ({'criteria_type': 'games_won', 'threshold': 5}, False),
            ({'criteria_type': 'rounds_won', 'threshold': 25}, True),
            ({'criteria_type': 'best_time_under', 'threshold': 30000}, True),
            ({'criteria_type': 'best_time_under', 'threshold': 15000}, False),
            ({'criteria_type': 'elo_reached', 'threshold': 1100}, True),
            ({'criteria_type': 'elo_reached', 'threshold': 1300}, False),
            ({'criteria_type': 'level_reached', 'threshold': 3}, True),
            ({'criteria_type': 'level_reached', 'threshold': 5}, False),
        ]
        for vals, expected in cases:
            badge = Badge.create({'name': 'T %s %s' % (vals['criteria_type'], vals['threshold']), **vals})
            self.assertEqual(
                badge._matches_profile(profile), expected,
                "%s should be %s" % (vals, expected),
            )

    def test_level_reward_badges(self):
        """Level milestone badges act as level-up rewards."""
        profile = self.env['speedrun.profile'].create({
            'user_id': self.user_c.id,
            'xp': 1600,  # level 5
        })
        self.assertEqual(profile.level, 5)
        profile._check_badges()
        badge_level_5 = self.env.ref('odoo_speedrun.badge_level_5')
        self.assertIn(badge_level_5, profile.badge_award_ids.badge_id)
        # Reward XP was granted
        self.assertEqual(profile.xp, 1600 + badge_level_5.xp_reward)

    def test_best_time_badge_from_profile_stats(self):
        """Speed badges use the recomputed best time."""
        profile = self.env['speedrun.profile'].create({
            'user_id': self.user_c.id,
            'best_time_ms': 12000,
        })
        profile._check_badges()
        badges = profile.badge_award_ids.badge_id
        self.assertIn(self.env.ref('odoo_speedrun.badge_speed_demon'), badges)
        self.assertIn(self.env.ref('odoo_speedrun.badge_lightning'), badges)
