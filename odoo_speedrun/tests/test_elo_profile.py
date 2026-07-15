from odoo.tests import tagged

from .common import SpeedrunCommon


@tagged('post_install', '-at_install', 'speedrun')
class TestEloProfile(SpeedrunCommon):

    def test_elo_two_players(self):
        """Winner gains ELO, loser loses the same amount (equal ratings)."""
        game = self._play_game([self.user_a, self.user_b], total_rounds=1)
        self.assertEqual(game.winner_id, self.user_a)

        profile_a = self._get_profile(self.user_a)
        profile_b = self._get_profile(self.user_b)
        self.assertTrue(profile_a and profile_b, "Profiles must be auto-created")

        # Equal 1000 ratings: expected score 0.5, K=32 => +/-16
        self.assertEqual(profile_a.elo, 1016)
        self.assertEqual(profile_b.elo, 984)
        self.assertEqual(profile_a.peak_elo, 1016)
        self.assertEqual(profile_b.peak_elo, 1000, "Peak ELO never decreases")

    def test_elo_history_created(self):
        """Each ranked multiplayer game creates one ELO history entry per player."""
        self._play_game([self.user_a, self.user_b], total_rounds=1)
        profile_a = self._get_profile(self.user_a)
        profile_b = self._get_profile(self.user_b)
        self.assertEqual(len(profile_a.elo_history_ids), 1)
        self.assertEqual(len(profile_b.elo_history_ids), 1)
        hist_a = profile_a.elo_history_ids
        self.assertEqual(hist_a.elo_before, 1000)
        self.assertEqual(hist_a.elo_change, 16)
        self.assertEqual(hist_a.elo_after, 1016)
        self.assertEqual(profile_b.elo_history_ids.elo_change, -16)

    def test_elo_progression_over_games(self):
        """ELO keeps moving over several games and history accumulates."""
        for _ in range(3):
            self._play_game([self.user_a, self.user_b], total_rounds=1)
        profile_a = self._get_profile(self.user_a)
        profile_b = self._get_profile(self.user_b)
        self.assertEqual(len(profile_a.elo_history_ids), 3)
        self.assertGreater(profile_a.elo, 1030)  # winner keeps climbing
        self.assertLess(profile_b.elo, 970)
        # History chain is consistent
        ordered = profile_a.elo_history_ids.sorted('id')
        self.assertEqual(ordered[0].elo_before, 1000)
        self.assertEqual(ordered[-1].elo_after, profile_a.elo)

    def test_solo_game_no_elo(self):
        """Single-player games grant XP but do not affect ELO."""
        self._play_game([self.user_a], total_rounds=1)
        profile_a = self._get_profile(self.user_a)
        self.assertEqual(profile_a.elo, 1000)
        self.assertFalse(profile_a.elo_history_ids)
        self.assertGreater(profile_a.xp, 0)

    def test_xp_and_stats(self):
        """XP is granted per round points, participation and victory; stats update."""
        game = self._play_game([self.user_a, self.user_b], total_rounds=2)
        profile_a = self._get_profile(self.user_a)
        profile_b = self._get_profile(self.user_b)
        # a: 2 rounds rank 1 => 6 pts * 15 + 2 * 10 + 50 (win) = 160 base XP
        # b: 2 rounds rank 2 => 4 pts * 15 + 2 * 10 = 80 base XP
        self.assertGreaterEqual(profile_a.xp, 160)
        self.assertGreaterEqual(profile_b.xp, 80)
        self.assertGreater(profile_a.xp, profile_b.xp)
        # Stats
        self.assertEqual(profile_a.games_played, 1)
        self.assertEqual(profile_a.games_won, 1)
        self.assertEqual(profile_a.rounds_played, 2)
        self.assertEqual(profile_a.rounds_won, 2)
        self.assertEqual(profile_b.games_won, 0)
        self.assertGreater(profile_a.best_time_ms, 0)
        self.assertEqual(profile_a.win_rate, 100.0)
        self.assertEqual(game.round_result_ids.filtered(
            lambda r: r.user_id == self.user_a and r.rank == 1
        ).mapped('round_number'), [1, 2])

    def test_level_computation(self):
        """Level derives from XP: level = isqrt(xp/100) + 1."""
        profile = self.env['speedrun.profile'].create({'user_id': self.user_c.id})
        self.assertEqual(profile.level, 1)
        self.assertEqual(profile.level_title, 'Rookie')
        profile.xp = 100
        self.assertEqual(profile.level, 2)
        self.assertEqual(profile.level_title, 'Apprentice')
        profile.xp = 400
        self.assertEqual(profile.level, 3)
        self.assertEqual(profile.level_title, 'Runner')
        profile.xp = 2500  # isqrt(25) + 1 = 6
        self.assertEqual(profile.level, 6)
        self.assertEqual(profile.level_title, 'Expert')

    def test_stats_payload(self):
        """The frontend stats payload contains all sections."""
        self._play_game([self.user_a, self.user_b], total_rounds=1)
        profile_a = self._get_profile(self.user_a)
        payload = profile_a._get_stats_payload()
        self.assertEqual(payload['user_id'], self.user_a.id)
        self.assertEqual(payload['elo'], 1016)
        self.assertEqual(payload['games_played'], 1)
        self.assertTrue(payload['best_times'], "Personal bests must be listed")
        self.assertEqual(payload['best_times'][0]['task_name'], self.task.name)
        self.assertEqual(len(payload['elo_history']), 1)
        self.assertGreater(payload['next_level_xp'], 0)
