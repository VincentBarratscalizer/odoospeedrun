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
        self.assertEqual(game.total_rounds, 3)

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

    def test_cannot_join_twice(self):
        self._queue(self.user_a).action_join_queue()
        with self.assertRaises(UserError):
            self._queue(self.user_a).action_join_queue()

    def test_cannot_queue_while_in_game(self):
        game = self.env['speedrun.game'].with_user(self.user_a).create({})
        self.assertEqual(game.state, 'waiting')
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
