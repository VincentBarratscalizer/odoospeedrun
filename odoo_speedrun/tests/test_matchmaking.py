from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import SpeedrunCommon


@tagged('post_install', '-at_install', 'speedrun')
class TestMatchmaking(SpeedrunCommon):

    def _queue(self, user):
        return self.env['speedrun.matchmaking.queue'].with_user(user)

    def test_match_two_players(self):
        """Two players with similar ELO get matched into an auto-started ranked game."""
        entry_a = self._queue(self.user_a).action_join_queue()
        self.assertEqual(entry_a.state, 'waiting')
        self.assertEqual(entry_a.elo, 1000)

        entry_b = self._queue(self.user_b).action_join_queue()
        # Match should have happened immediately
        self.assertEqual(entry_a.state, 'matched')
        self.assertEqual(entry_b.state, 'matched')
        game = entry_a.game_id
        self.assertTrue(game)
        self.assertEqual(game, entry_b.game_id)
        self.assertTrue(game.is_ranked)
        self.assertEqual(game.host_id, self.user_a, "Longest-waiting player hosts")
        self.assertEqual(set(game.player_ids.user_id.ids), {self.user_a.id, self.user_b.id})
        self.assertEqual(game.state, 'countdown', "Ranked matches auto-start")
        self.assertEqual(game.game_mode, 'best_of', "Ranked matches are best-of")
        self.assertEqual(game.total_rounds, 5, "Best of 5")
        self.assertEqual(game.rounds_to_win, 3, "First to 3 round wins")

    def test_queue_status(self):
        """Queue status reports waiting, then matched with game info."""
        status = self._queue(self.user_a).get_queue_status()
        self.assertFalse(status['in_queue'])

        self._queue(self.user_a).action_join_queue()
        status = self._queue(self.user_a).get_queue_status()
        self.assertTrue(status['in_queue'])
        self.assertEqual(status['queue_size'], 1)

        self._queue(self.user_b).action_join_queue()
        status = self._queue(self.user_a).get_queue_status()
        self.assertFalse(status['in_queue'])
        self.assertTrue(status['matched'])
        self.assertTrue(status['game_info']['is_ranked'])
        self.assertEqual(status['game_info']['player_count'], 2)

    def test_elo_gap_blocks_then_widens(self):
        """Players too far apart in ELO only match after waiting widens the range."""
        # Give Bravo a much higher rating
        self.env['speedrun.profile'].create({'user_id': self.user_b.id, 'elo': 2000})
        entry_a = self._queue(self.user_a).action_join_queue()
        entry_b = self._queue(self.user_b).action_join_queue()
        self.assertEqual(entry_a.state, 'waiting', "1000 ELO gap > base range: no match")
        self.assertEqual(entry_b.state, 'waiting')

        # Simulate 5 minutes of waiting: range = 200 + 100 * 10 = 1200 >= 1000
        future = fields.Datetime.now() + timedelta(minutes=5)
        self.env['speedrun.matchmaking.queue'].sudo()._try_match(now=future)
        self.assertEqual(entry_a.state, 'matched')
        self.assertEqual(entry_b.state, 'matched')
        self.assertEqual(entry_a.game_id, entry_b.game_id)

    def test_leave_queue(self):
        """A player can cancel their search."""
        entry = self._queue(self.user_a).action_join_queue()
        self._queue(self.user_a).action_leave_queue()
        self.assertEqual(entry.state, 'cancelled')
        status = self._queue(self.user_a).get_queue_status()
        self.assertFalse(status['in_queue'])
        # Cancelled players are not matched
        self._queue(self.user_b).action_join_queue()
        self.assertEqual(entry.state, 'cancelled')
        self.assertFalse(entry.game_id)

    def test_join_twice_is_idempotent(self):
        """Re-joining while already waiting keeps the same entry (no error)."""
        entry = self._queue(self.user_a).action_join_queue()
        entry_again = self._queue(self.user_a).action_join_queue()
        self.assertEqual(entry, entry_again)
        self.assertEqual(self.env['speedrun.matchmaking.queue'].search_count(
            [('user_id', '=', self.user_a.id), ('state', '=', 'waiting')]), 1)

    def test_queue_leaves_waiting_lobby(self):
        """Queuing while idling in a waiting lobby auto-leaves the lobby."""
        game = self.env['speedrun.game'].with_user(self.user_a).create({})
        self.assertEqual(game.state, 'waiting')
        entry = self._queue(self.user_a).action_join_queue()
        self.assertEqual(entry.state, 'waiting')
        self.assertNotIn(self.user_a, game.player_ids.user_id)

    def test_cannot_queue_while_playing(self):
        """Queuing during a started game is refused."""
        game = self.env['speedrun.game'].with_user(self.user_a).create({})
        game.with_user(self.user_a).action_start()
        self.assertEqual(game.state, 'countdown')
        with self.assertRaises(UserError):
            self._queue(self.user_a).action_join_queue()

    def test_match_three_players(self):
        """Up to MATCH_MAX_PLAYERS compatible players end up in the same game."""
        # Join everyone "simultaneously": disable auto-match by pre-checking states
        Queue = self.env['speedrun.matchmaking.queue'].sudo()
        entries = Queue.create([
            {'user_id': self.user_a.id, 'elo': 1000},
            {'user_id': self.user_b.id, 'elo': 1050},
            {'user_id': self.user_c.id, 'elo': 950},
        ])
        Queue._try_match()
        self.assertTrue(all(e.state == 'matched' for e in entries))
        games = entries.mapped('game_id')
        self.assertEqual(len(games), 1, "All three fit in one match")
        self.assertEqual(len(games.player_ids), 3)

    # ------------------------------------------------------------------
    # Best-of mode gameplay
    # ------------------------------------------------------------------
    def _play_best_of_round(self, game, finish_order, first_round=False):
        """Play one round of a game; players finish in the given order."""
        host = game.host_id
        if first_round:
            game.with_user(host).action_start()
        else:
            game.with_user(host).action_next_round()
        game.with_user(host).action_begin()
        game.sudo().write({
            'start_time': fields.Datetime.now() - timedelta(seconds=45),
        })
        for user in finish_order:
            result = game.with_user(user).action_check_completion()
            self.assertTrue(result.get('success'), result)

    def _create_best_of_game(self):
        game = self.env['speedrun.game'].with_user(self.user_a).create({
            'game_mode': 'best_of',
            'total_rounds': 5,
        })
        game.action_join(user_id=self.user_b.id)
        return game

    def test_best_of_ends_early(self):
        """A best-of-5 game ends as soon as a player has 3 round wins."""
        game = self._create_best_of_game()
        self.assertEqual(game.rounds_to_win, 3)
        for rnd in range(3):
            self._play_best_of_round(game, [self.user_a, self.user_b], first_round=(rnd == 0))
        self.assertEqual(game.state, 'finished', "3 straight wins end the game after 3 rounds")
        self.assertEqual(game.current_round, 3)
        self.assertEqual(game.winner_id, self.user_a)
        player_a = game.player_ids.filtered(lambda p: p.user_id == self.user_a)
        self.assertEqual(player_a.round_wins, 3)

    def test_best_of_goes_the_distance(self):
        """With alternating round winners, the game lasts the full 5 rounds."""
        game = self._create_best_of_game()
        orders = [
            [self.user_a, self.user_b],
            [self.user_b, self.user_a],
            [self.user_a, self.user_b],
            [self.user_b, self.user_a],
            [self.user_a, self.user_b],
        ]
        for rnd, order in enumerate(orders):
            self.assertNotEqual(game.state, 'finished', "Game must not end before someone has 3 wins")
            self._play_best_of_round(game, order, first_round=(rnd == 0))
        self.assertEqual(game.state, 'finished')
        self.assertEqual(game.current_round, 5)
        self.assertEqual(game.winner_id, self.user_a, "Alpha won rounds 1, 3 and 5")
        wins = {p.user_id: p.round_wins for p in game.player_ids}
        self.assertEqual(wins[self.user_a], 3)
        self.assertEqual(wins[self.user_b], 2)

    def test_cron_cleans_stale_entries(self):
        """The cron purges old matched/cancelled entries."""
        entry = self._queue(self.user_a).action_join_queue()
        self._queue(self.user_a).action_leave_queue()
        # Backdate the entry by 2 days
        self.env.cr.execute(
            "UPDATE speedrun_matchmaking_queue SET create_date = create_date - interval '2 days' WHERE id = %s",
            [entry.id],
        )
        entry.invalidate_recordset()
        self.env['speedrun.matchmaking.queue'].sudo()._cron_process_queue()
        self.assertFalse(entry.exists())
