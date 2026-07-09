from odoo import api, fields, models
from odoo.exceptions import UserError

# Matchmaking tuning
MATCH_MIN_PLAYERS = 2
MATCH_MAX_PLAYERS = 4
BASE_ELO_RANGE = 200        # initial acceptable ELO gap
RANGE_WIDENING_STEP = 100   # extra range gained per widening interval
WIDENING_INTERVAL = 30      # seconds per widening step
MATCH_ROUNDS = 5            # max rounds of a ranked match (best of 5: first to 3 round wins)


class SpeedrunMatchmakingQueue(models.Model):
    _name = 'speedrun.matchmaking.queue'
    _description = 'Speedrun Matchmaking Queue'
    _order = 'create_date asc'
    _rec_name = 'user_id'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    elo = fields.Integer(help="ELO snapshot when joining the queue.")
    state = fields.Selection([
        ('waiting', 'Waiting'),
        ('matched', 'Matched'),
        ('cancelled', 'Cancelled'),
    ], default='waiting', required=True, index=True)
    game_id = fields.Many2one('speedrun.game', readonly=True, ondelete='set null')

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    @api.model
    def action_join_queue(self):
        """Enter the matchmaking queue for the current user.

        Idempotent: joining while already queued simply keeps waiting
        (and opportunistically retries matching) instead of raising.
        """
        uid = self.env.uid
        existing = self.search([('user_id', '=', uid), ('state', '=', 'waiting')], limit=1)
        if existing:
            self.sudo()._try_match()
            return existing
        active_game = self.env['speedrun.game'].search([
            ('player_ids.user_id', '=', uid),
            ('state', 'in', ['waiting', 'countdown', 'running', 'round_finished']),
        ], limit=1)
        if active_game:
            if active_game.state == 'waiting':
                # Just sitting in a lobby: leave it automatically and queue up.
                active_game.action_leave(user_id=uid)
            else:
                raise UserError("You are already in an active game. Leave it before queuing.")
        profile = self.env['speedrun.profile'].sudo()._get_or_create(self.env.user)
        entry = self.create({
            'user_id': uid,
            'elo': profile.elo,
        })
        self.sudo()._try_match()
        return entry

    @api.model
    def action_leave_queue(self):
        """Leave the matchmaking queue for the current user."""
        entries = self.search([('user_id', '=', self.env.uid), ('state', '=', 'waiting')])
        entries.write({'state': 'cancelled'})
        return True

    @api.model
    def get_queue_status(self):
        """Return the current user's queue status (also opportunistically matches)."""
        self.sudo()._try_match()
        entry = self.search(
            [('user_id', '=', self.env.uid), ('state', 'in', ['waiting', 'matched'])],
            order='create_date desc', limit=1)
        if not entry:
            return {'in_queue': False}
        if entry.state == 'matched' and entry.game_id:
            # Only resurrect a match that is still in progress. Once the game
            # is finished (or the player has left it), the entry is stale:
            # drop it so a refresh doesn't drag the player back into the
            # results screen of a game they already left.
            game = entry.game_id.sudo()
            still_playing = (
                game.state in ('waiting', 'countdown', 'running', 'round_finished')
                and self.env.uid in game.player_ids.user_id.ids
            )
            if still_playing:
                return {
                    'in_queue': False,
                    'matched': True,
                    'game_info': game._get_game_info(),
                }
            entry.sudo().unlink()
            return {'in_queue': False}
        wait_seconds = int((fields.Datetime.now() - entry.create_date).total_seconds())
        return {
            'in_queue': True,
            'matched': False,
            'wait_seconds': wait_seconds,
            'elo': entry.elo,
            'queue_size': self.search_count([('state', '=', 'waiting')]),
        }

    # ------------------------------------------------------------------
    # Matching engine
    # ------------------------------------------------------------------
    def _elo_range(self, entry, now):
        """Acceptable ELO gap for an entry: widens the longer they wait."""
        wait = max(0, (now - entry.create_date).total_seconds())
        return BASE_ELO_RANGE + RANGE_WIDENING_STEP * int(wait // WIDENING_INTERVAL)

    @api.model
    def _try_match(self, now=None):
        """Try to build matches from waiting queue entries (ELO-based)."""
        now = now or fields.Datetime.now()
        waiting = self.search([('state', '=', 'waiting')], order='create_date asc')
        matched_games = self.env['speedrun.game']
        while len(waiting) >= MATCH_MIN_PLAYERS:
            anchor = waiting[0]
            anchor_range = self._elo_range(anchor, now)
            group = anchor
            for candidate in waiting[1:]:
                if len(group) >= MATCH_MAX_PLAYERS:
                    break
                allowed = max(anchor_range, self._elo_range(candidate, now))
                if abs(candidate.elo - anchor.elo) <= allowed:
                    group |= candidate
            if len(group) >= MATCH_MIN_PLAYERS:
                matched_games |= self._create_match(group)
                waiting -= group
            else:
                # Anchor can't be matched yet; nobody older can either.
                break
        return matched_games

    def _create_match(self, entries):
        """Create a ranked game for matched entries and auto-start it."""
        entries = entries.sorted('create_date')
        host = entries[0].user_id
        game = self.env['speedrun.game'].sudo().with_context(default_host_id=host.id).create({
            'name': 'Ranked Match',
            'host_id': host.id,
            'game_mode': 'best_of',
            'total_rounds': MATCH_ROUNDS,
            'max_players': MATCH_MAX_PLAYERS,
            'is_ranked': True,
        })
        for entry in entries[1:]:
            game.action_join(user_id=entry.user_id.id)
        entries.write({'state': 'matched', 'game_id': game.id})
        game_info = game._get_game_info()
        for entry in entries:
            entry.user_id._bus_send('speedrun/match_found', {
                'game_info': game_info,
            })
        # Auto-start the match (countdown)
        game._start_round()
        return game

    @api.model
    def _cron_process_queue(self):
        """Cron fallback: match waiting players and purge stale entries."""
        self._try_match()
        # Purge cancelled/matched entries older than 1 day
        stale = self.search([
            ('state', 'in', ['cancelled', 'matched']),
            ('create_date', '<', fields.Datetime.subtract(fields.Datetime.now(), days=1)),
        ])
        stale.unlink()
