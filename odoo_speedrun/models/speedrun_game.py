import random
import string

from odoo import api, fields, models
from odoo.exceptions import UserError, AccessError

POINTS_BY_RANK = {1: 3, 2: 2, 3: 1}  # Points awarded by finishing position


class SpeedrunGame(models.Model):
    _name = 'speedrun.game'
    _description = 'Speedrun Game Room'
    _inherit = ['bus.listener.mixin']
    _order = 'create_date desc'

    name = fields.Char(required=True, default=lambda self: 'Speedrun #%s' % random.randint(1000, 9999))
    code = fields.Char(string='Join Code', index=True, readonly=True, copy=False)
    state = fields.Selection([
        ('waiting', 'Waiting'),
        ('countdown', 'Countdown'),
        ('running', 'Running'),
        ('round_finished', 'Round Finished'),
        ('finished', 'Finished'),
    ], default='waiting', required=True, readonly=True)
    host_id = fields.Many2one('res.users', string='Host', required=True, default=lambda self: self.env.uid)
    player_ids = fields.One2many('speedrun.player', 'game_id', string='Players')
    player_count = fields.Integer(compute='_compute_player_count', store=True)
    round_result_ids = fields.One2many('speedrun.round.result', 'game_id', string='Round Results')

    # Current round fields
    task_id = fields.Many2one('speedrun.task', string='Current Task', readonly=True)
    start_time = fields.Datetime(readonly=True, help="Start time of the current round")
    end_time = fields.Datetime(readonly=True)
    winner_id = fields.Many2one('res.users', string='Overall Winner', readonly=True)

    # Multi-round fields
    game_mode = fields.Selection([
        ('points', 'Points (fixed rounds)'),
        ('best_of', 'Best Of (first to win a majority of rounds)'),
        ('battle_royale', 'Battle Royale (last player standing)'),
        ('time_attack', 'Time Attack (most tasks in fixed time)'),
    ], default='points', required=True, string='Game Mode')
    br_lives = fields.Integer(string='Lives per Player', default=3,
                              help="Battle Royale: number of lives each player starts with.")
    br_cutoff = fields.Integer(string='Losers per Round', default=1,
                               help="Battle Royale: number of last-place players who lose a life each round.")
    total_rounds = fields.Integer(default=3, string='Number of Rounds',
                                  help="In Best Of mode, this is the maximum number of rounds.")
    rounds_to_win = fields.Integer(compute='_compute_rounds_to_win', string='Rounds to Win')
    current_round = fields.Integer(default=0, string='Current Round', readonly=True)
    max_players = fields.Integer(default=8)
    is_ranked = fields.Boolean(string='Ranked Match', readonly=True,
                               help="Game created through matchmaking.")
    cleanup_done = fields.Boolean(
        string='Data Cleaned', default=False, readonly=True, copy=False,
        help="Set once the demo-reset job has deleted the records players "
             "created during this game.")
    task_group_ids = fields.Many2many(
        'speedrun.task.group',
        'speedrun_game_task_group_rel', 'game_id', 'group_id',
        string='Task Groups', readonly=True,
        help="If set, tasks are drawn only from these groups during the game.")
    tournament_match_id = fields.Many2one('speedrun.tournament.match', readonly=True,
                                          ondelete='set null',
                                          help="Set when this game backs a tournament match.")

    # Time Attack fields
    ta_duration = fields.Integer(
        string='Time Attack Duration (s)', default=120,
        help="Time Attack mode: total play time in seconds (default 2 minutes).")
    ta_task_seq_ids = fields.One2many(
        'speedrun.game.task.seq', 'game_id', string='Task Sequence',
        help="Ordered list of tasks for Time Attack mode (shared by all players).")

    @api.depends('player_ids')
    def _compute_player_count(self):
        for game in self:
            game.player_count = len(game.player_ids)

    @api.depends('total_rounds')
    def _compute_rounds_to_win(self):
        for game in self:
            game.rounds_to_win = game.total_rounds // 2 + 1

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = self._generate_code()
        games = super().create(vals_list)
        for game in games:
            self.env['speedrun.player'].create({
                'game_id': game.id,
                'user_id': game.host_id.id,
                'state': 'waiting',
            })
        return games

    @staticmethod
    def _generate_code():
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

    def action_join(self, user_id=None):
        self.ensure_one()
        user_id = user_id or self.env.uid
        if self.state != 'waiting':
            raise UserError("This game has already started.")
        if len(self.player_ids) >= self.max_players:
            raise UserError("This game is full (max %s players)." % self.max_players)
        if user_id in self.player_ids.user_id.ids:
            raise UserError("You have already joined this game.")
        player = self.env['speedrun.player'].create({
            'game_id': self.id,
            'user_id': user_id,
            'state': 'waiting',
        })
        user = self.env['res.users'].browse(user_id)
        self._bus_send('speedrun/player_joined', {
            'user_id': user_id,
            'user_name': user.name,
            'player_count': len(self.player_ids),
        })
        return player

    def action_leave(self, user_id=None):
        self.ensure_one()
        user_id = user_id or self.env.uid
        if self.state not in ('waiting', 'finished'):
            raise UserError("Cannot leave a game in progress.")
        player = self.player_ids.filtered(lambda p: p.user_id.id == user_id)
        if not player:
            return
        user_name = player.user_id.name
        player.unlink()
        self._bus_send('speedrun/player_left', {
            'user_id': user_id,
            'user_name': user_name,
            'player_count': len(self.player_ids),
        })

    def action_dismiss(self, user_id=None):
        """Mark the current user as having left the results screen ("Play
        again"). Dismissed games are no longer restored on refresh, but the
        player row (and thus game history / standings) is kept intact."""
        self.ensure_one()
        user_id = user_id or self.env.uid
        player = self.player_ids.filtered(lambda p: p.user_id.id == user_id)
        if player:
            player.dismissed = True
        # Drop any stale matchmaking entry so the queue doesn't resurrect it.
        self.env['speedrun.matchmaking.queue'].sudo().search([
            ('user_id', '=', user_id),
            ('game_id', '=', self.id),
        ]).unlink()
        return True

    def _pick_random_task(self, exclude_ids=None):
        """Pick a random task, strictly avoiding already-used ones.

        If the game has task groups selected, the pool is restricted to the
        tasks of those groups (that are still playable)."""
        available_tasks = self.env['speedrun.task']._get_available_tasks()
        if self.task_group_ids:
            group_task_ids = set(self.task_group_ids.task_ids.ids)
            scoped = available_tasks.filtered(lambda t: t.id in group_task_ids)
            if scoped:
                available_tasks = scoped
            # else: no playable task in the selected groups -> fall back to all
        if not available_tasks:
            raise UserError("No tasks available. Please contact an administrator.")
        if exclude_ids:
            fresh = available_tasks.filtered(lambda t: t.id not in exclude_ids)
            if fresh:
                available_tasks = fresh
            # If all tasks have been used, we must reuse — but log it
        return self.env['speedrun.task'].browse(random.choice(available_tasks.ids))

    def action_start(self):
        """Start the first round (host only)."""
        self.ensure_one()
        if self.env.uid != self.host_id.id:
            raise AccessError("Only the host can start the game.")
        if self.state != 'waiting':
            raise UserError("Game has already started.")
        if len(self.player_ids) < 1:
            raise UserError("Need at least 1 player to start.")
        # Initialise lives for Battle Royale mode
        if self.game_mode == 'battle_royale':
            self.player_ids.write({'lives_remaining': self.br_lives})
        # Time Attack: generate task sequence and use dedicated start logic
        if self.game_mode == 'time_attack':
            return self._start_ta_game()
        return self._start_round()

    def action_next_round(self):
        """Start the next round (host only)."""
        self.ensure_one()
        if self.env.uid != self.host_id.id:
            raise AccessError("Only the host can start the next round.")
        if self.state != 'round_finished':
            raise UserError("Current round is not finished yet.")
        if self.game_mode == 'time_attack':
            raise UserError("Time Attack has no rounds — use the time attack end action.")
        # Battle Royale has no fixed round limit — game ends by elimination
        if self.game_mode != 'battle_royale' and self.current_round >= self.total_rounds:
            raise UserError("All rounds are already completed.")
        return self._start_round()

    def _start_round(self):
        """Start a new round: pick task, increment round, countdown."""
        # Pick a task different from previous rounds
        used_task_ids = list(set(
            self.round_result_ids.mapped('task_id').ids
            + ([self.task_id.id] if self.task_id else [])
        ))
        task = self._pick_random_task(exclude_ids=used_task_ids)

        self.write({
            'task_id': task.id,
            'state': 'countdown',
            'current_round': self.current_round + 1,
            'start_time': False,
            'end_time': False,
        })
        # Reset player states for the new round.
        # In Battle Royale, only reset players who still have lives.
        if self.game_mode == 'battle_royale':
            active_players = self.player_ids.filtered(lambda p: p.lives_remaining > 0)
        else:
            active_players = self.player_ids
        active_players.write({
            'state': 'playing',
            'finish_time': False,
            'duration_ms': 0,
        })

        self._bus_send('speedrun/countdown_start', {
            'countdown_seconds': 5,
            'game_id': self.id,
            'current_round': self.current_round,
            'total_rounds': self.total_rounds,
            'task_name': task.name,
            'task_description': task.description or '',
        })
        return True

    def action_begin(self):
        """Called after countdown. Officially starts the round timer."""
        self.ensure_one()
        if self.state != 'countdown':
            raise UserError("Game is not in countdown state.")
        now = fields.Datetime.now()
        self.write({
            'state': 'running',
            'start_time': now,
        })
        if self.game_mode == 'time_attack':
            # Time Attack: broadcast a dedicated start event (no shared task — each
            # player progresses through the sequence independently).
            first_seq = self.ta_task_seq_ids.filtered(lambda s: s.sequence == 0)
            self._bus_send('speedrun/ta_game_started', {
                'game_id': self.id,
                'ta_duration': self.ta_duration,
                'start_time': fields.Datetime.to_string(now),
                'task_name': first_seq.task_id.name if first_seq else '',
                'task_description': first_seq.task_id.description or '' if first_seq else '',
            })
        else:
            self._bus_send('speedrun/game_started', {
                'game_id': self.id,
                'task_name': self.task_id.name,
                'task_description': self.task_id.description or '',
                'start_time': fields.Datetime.to_string(now),
                'current_round': self.current_round,
                'total_rounds': self.total_rounds,
            })
        return True

    def action_check_completion(self, user_id=None):
        """Check if a user has completed the current round's task."""
        self.ensure_one()
        user_id = user_id or self.env.uid
        if self.state != 'running':
            return {'success': False, 'error': 'Game is not running.'}

        player = self.player_ids.filtered(lambda p: p.user_id.id == user_id)
        if not player:
            return {'success': False, 'error': 'You are not in this game.'}
        if player.state != 'playing':
            return {'success': False, 'error': 'You are no longer playing this round.'}

        # Verify the task
        completed = self.sudo().task_id._verify_completion(user_id, self.start_time)
        if not completed:
            return {'success': False, 'error': 'Task not completed yet. Keep going!'}

        # Mark the player as finished
        now = fields.Datetime.now()
        player.write({
            'state': 'finished',
            'finish_time': now,
        })
        duration_ms = int((now - self.start_time).total_seconds() * 1000)

        # Determine rank for this player in this round
        finished_count = len(self.player_ids.filtered(lambda p: p.state == 'finished'))
        rank = finished_count  # 1st finisher = rank 1, etc.
        points = POINTS_BY_RANK.get(rank, 0)

        # Save round result
        self.env['speedrun.round.result'].create({
            'game_id': self.id,
            'round_number': self.current_round,
            'task_id': self.task_id.id,
            'user_id': user_id,
            'rank': rank,
            'duration_ms': duration_ms,
            'points': points,
        })

        # Update player total score / round wins
        player.score += points
        if rank == 1:
            player.round_wins += 1

        user = self.env['res.users'].browse(user_id)
        self._bus_send('speedrun/player_finished', {
            'user_id': user_id,
            'user_name': user.name,
            'duration_ms': duration_ms,
            'rank': rank,
            'points': points,
        })

        # Check if all players are done (finished or surrendered)
        all_done = all(p.state in ('finished', 'dnf') for p in self.player_ids)
        if all_done:
            self._end_round(now)

        response = {
            'success': True,
            'all_done': all_done,
            'duration_ms': duration_ms,
            'rank': rank,
            'points': points,
        }
        if all_done:
            response['game_info'] = self._get_game_info()
        return response

    def action_surrender(self, user_id=None):
        """Surrender the current round: the player scores no points and stops
        playing. Unlike a natural DNF (round timeout), this is a voluntary
        forfeit triggered by the player."""
        self.ensure_one()
        user_id = user_id or self.env.uid
        if self.state != 'running':
            return {'success': False, 'error': 'Game is not running.'}

        player = self.player_ids.filtered(lambda p: p.user_id.id == user_id)
        if not player:
            return {'success': False, 'error': 'You are not in this game.'}
        if player.state != 'playing':
            return {'success': False, 'error': 'You are no longer playing this round.'}

        # Mark the player as DNF with no points for this round
        player.write({'state': 'dnf'})
        self.env['speedrun.round.result'].create({
            'game_id': self.id,
            'round_number': self.current_round,
            'task_id': self.task_id.id,
            'user_id': user_id,
            'rank': 0,
            'duration_ms': 0,
            'points': 0,
        })

        user = self.env['res.users'].browse(user_id)
        self._bus_send('speedrun/player_finished', {
            'user_id': user_id,
            'user_name': user.name,
            'duration_ms': 0,
            'rank': 0,
            'points': 0,
            'surrendered': True,
        })

        now = fields.Datetime.now()
        all_done = all(p.state in ('finished', 'dnf') for p in self.player_ids)
        if all_done:
            self._end_round(now)

        response = {
            'success': True,
            'surrendered': True,
            'all_done': all_done,
            'duration_ms': 0,
            'rank': 0,
            'points': 0,
        }
        if all_done:
            response['game_info'] = self._get_game_info()
        return response

    def _end_round(self, now):
        """End the current round and determine if game is over."""
        # Battle Royale has its own end-of-round logic
        if self.game_mode == 'battle_royale':
            self._end_round_br(now)
            return

        # Mark remaining players as DNF with 0 points
        dnf_players = self.player_ids.filtered(lambda p: p.state == 'playing')
        for p in dnf_players:
            p.write({'state': 'dnf'})
            self.env['speedrun.round.result'].create({
                'game_id': self.id,
                'round_number': self.current_round,
                'task_id': self.task_id.id,
                'user_id': p.user_id.id,
                'rank': 0,
                'duration_ms': 0,
                'points': 0,
            })

        self.write({'end_time': now})

        is_last_round = self.current_round >= self.total_rounds
        if self.game_mode == 'best_of':
            # Best-of: game ends as soon as a player reaches the required
            # number of round wins (majority), or the max rounds are played.
            is_last_round = is_last_round or any(
                p.round_wins >= self.rounds_to_win for p in self.player_ids
            )
        if is_last_round:
            # Game over — determine overall winner
            if self.game_mode == 'best_of':
                # Most round wins; total points break ties
                best_player = max(self.player_ids, key=lambda p: (p.round_wins, p.score))
            else:
                best_player = max(self.player_ids, key=lambda p: p.score)
            self.write({
                'state': 'finished',
                'winner_id': best_player.user_id.id,
            })
            # Update profiles: ELO, XP, stats, badges, levels
            # sudo: triggered by whichever player finished last
            elo_changes = self.env['speedrun.profile'].sudo()._process_game_results(self.sudo())
            payload = self._build_game_over_payload()
            payload['elo_changes'] = elo_changes
            self._bus_send('speedrun/game_over', payload)
            # Advance the tournament bracket if this game backs a match.
            if self.tournament_match_id:
                self.tournament_match_id.sudo()._on_game_over()
        else:
            self.write({'state': 'round_finished'})
            self._bus_send('speedrun/round_over', self._build_round_over_payload())

    # ------------------------------------------------------------------
    # Battle Royale helpers
    # ------------------------------------------------------------------

    def _end_round_br(self, now):
        """End a Battle Royale round: deduct lives, check for survivors."""
        # Force-DNF players still playing (they ran out of time / everyone else finished)
        for p in self.player_ids.filtered(lambda p: p.state == 'playing'):
            p.write({'state': 'dnf'})
            self.env['speedrun.round.result'].create({
                'game_id': self.id,
                'round_number': self.current_round,
                'task_id': self.task_id.id,
                'user_id': p.user_id.id,
                'rank': 0,
                'duration_ms': 0,
                'points': 0,
            })

        self.write({'end_time': now})

        # Deduct lives from the last-place players
        life_changes = self._apply_br_life_deduction()

        # Count survivors (players still with lives > 0)
        active = self.player_ids.filtered(lambda p: p.lives_remaining > 0)

        if len(active) <= 1:
            # Game over: last survivor wins; if simultaneous elimination pick best last round
            winner = active[0] if active else self._br_last_round_best_player()
            self.write({'state': 'finished', 'winner_id': winner.user_id.id})
            elo_changes = self.env['speedrun.profile'].sudo()._process_game_results(self.sudo())
            payload = self._build_game_over_payload()
            payload['elo_changes'] = elo_changes
            payload['life_changes'] = life_changes
            self._bus_send('speedrun/game_over', payload)
            if self.tournament_match_id:
                self.tournament_match_id.sudo()._on_game_over()
        else:
            self.write({'state': 'round_finished'})
            payload = self._build_round_over_payload()
            payload['life_changes'] = life_changes
            self._bus_send('speedrun/round_over', payload)

    def _apply_br_life_deduction(self):
        """Deduct one life from the last `br_cutoff` players this round.

        Ordering: finishers by rank (fastest first), then DNF players.
        The tail of this list loses a life.  Returns a list of dicts
        describing each life change, to be sent on the bus.
        """
        round_results = self.round_result_ids.filtered(
            lambda r: r.round_number == self.current_round
        )
        finishers = round_results.filtered(lambda r: r.rank > 0).sorted('rank')
        dnfs = round_results.filtered(lambda r: r.rank == 0).sorted('id')

        ordered = list(finishers) + list(dnfs)   # best → worst
        cutoff = min(self.br_cutoff, len(ordered))
        loser_user_ids = {r.user_id.id for r in ordered[-cutoff:]} if cutoff else set()

        life_changes = []
        for player in self.player_ids:
            if player.user_id.id in loser_user_ids:
                player.lives_remaining = max(0, player.lives_remaining - 1)
                life_changes.append({
                    'user_id': player.user_id.id,
                    'user_name': player.user_id.name,
                    'lives_remaining': player.lives_remaining,
                    'eliminated': player.lives_remaining <= 0,
                })
        return life_changes

    def _br_last_round_best_player(self):
        """Fallback winner when all players are eliminated in the same round.

        Returns the player who performed best in the final round (lowest rank
        among finishers; arbitrary among DNFs).
        """
        round_results = self.round_result_ids.filtered(
            lambda r: r.round_number == self.current_round and r.rank > 0
        ).sorted('rank')
        if round_results:
            best_uid = round_results[0].user_id.id
            player = self.player_ids.filtered(lambda p: p.user_id.id == best_uid)
            if player:
                return player[0]
        return self.player_ids[0]

    # ------------------------------------------------------------------
    # Time Attack
    # ------------------------------------------------------------------

    def _generate_ta_sequence(self, count=20):
        """Pre-generate ``count`` distinct tasks for the Time Attack sequence."""
        used_ids = []
        for i in range(count):
            task = self._pick_random_task(exclude_ids=used_ids)
            self.env['speedrun.game.task.seq'].create({
                'game_id': self.id,
                'task_id': task.id,
                'sequence': i,
            })
            # Avoid picking the same task again (best-effort; falls back if pool exhausted)
            used_ids.append(task.id)

    def _start_ta_game(self):
        """Kick off a Time Attack game: generate the task sequence and send countdown."""
        self._generate_ta_sequence(count=20)
        self.write({
            'state': 'countdown',
            'current_round': 1,
            'start_time': False,
            'end_time': False,
        })
        self.player_ids.write({
            'state': 'playing',
            'finish_time': False,
            'duration_ms': 0,
            'ta_task_index': 0,
            'ta_completed_count': 0,
            'ta_last_task_time': False,
        })
        minutes = self.ta_duration // 60
        self._bus_send('speedrun/countdown_start', {
            'countdown_seconds': 5,
            'game_id': self.id,
            'current_round': 1,
            'total_rounds': 1,
            'task_name': '⏱ Time Attack',
            'task_description': (
                f'Complete as many tasks as you can in {minutes} minute'
                f'{"s" if minutes != 1 else ""}! '
                'Everyone gets the same task order — the most tasks wins.'
            ),
            'game_mode': 'time_attack',
            'ta_duration': self.ta_duration,
        })
        return True

    def action_ta_check_completion(self, user_id=None):
        """Verify that a Time Attack player completed their current task.

        On success: advances the player to the next task, broadcasts a score
        update on the bus, and returns the next task info so the client can
        immediately display it.
        """
        self.ensure_one()
        user_id = user_id or self.env.uid
        if self.state != 'running' or self.game_mode != 'time_attack':
            return {'success': False, 'error': 'Game is not in Time Attack mode.'}

        player = self.player_ids.filtered(lambda p: p.user_id.id == user_id)
        if not player:
            return {'success': False, 'error': 'You are not in this game.'}

        # Get the player's current task from the shared sequence
        current_seq = self.ta_task_seq_ids.filtered(lambda s: s.sequence == player.ta_task_index)
        if not current_seq:
            return {'success': False, 'error': 'No task available — please contact the host.'}

        # Reference time: when the previous task was finished (game start for task 0)
        start_ref = player.ta_last_task_time or self.start_time
        completed = current_seq.task_id.sudo()._verify_completion(user_id, start_ref)
        if not completed:
            return {'success': False, 'error': 'Task not completed yet. Keep going!'}

        now = fields.Datetime.now()
        next_index = player.ta_task_index + 1

        # Ensure the next task exists in the sequence (auto-extend if needed)
        next_seq = self.ta_task_seq_ids.filtered(lambda s: s.sequence == next_index)
        if not next_seq:
            used_ids = self.ta_task_seq_ids.mapped('task_id').ids
            next_task = self._pick_random_task(exclude_ids=used_ids)
            next_seq = self.sudo().env['speedrun.game.task.seq'].create({
                'game_id': self.id,
                'task_id': next_task.id,
                'sequence': next_index,
            })

        new_count = player.ta_completed_count + 1
        player.sudo().write({
            'ta_task_index': next_index,
            'ta_completed_count': new_count,
            'ta_last_task_time': now,
        })

        user = self.env['res.users'].browse(user_id)
        self._bus_send('speedrun/ta_score_update', {
            'user_id': user_id,
            'user_name': user.name,
            'ta_completed_count': new_count,
            'next_task_name': next_seq.task_id.name,
            'next_task_description': next_seq.task_id.description or '',
        })

        return {
            'success': True,
            'ta_completed_count': new_count,
            'next_task_name': next_seq.task_id.name,
            'next_task_description': next_seq.task_id.description or '',
        }

    def action_ta_end(self):
        """End a Time Attack game (host only, called when the client-side timer expires).

        Validates that at least ``ta_duration - 5`` seconds have elapsed (5 s
        grace period to absorb network latency), syncs ``score`` for ELO
        compatibility, then fires the standard ``game_over`` bus event.
        """
        self.ensure_one()
        if self.env.uid != self.host_id.id:
            raise AccessError("Only the host can end the Time Attack.")
        if self.state != 'running' or self.game_mode != 'time_attack':
            return {'success': False, 'error': 'Game is not running in Time Attack mode.'}

        now = fields.Datetime.now()
        elapsed = (now - self.start_time).total_seconds()
        if elapsed < self.ta_duration - 5:
            return {'success': False, 'error': 'Time has not expired yet.'}

        # Sync ta_completed_count → score for ELO / profile pipeline
        for p in self.player_ids:
            p.score = p.ta_completed_count

        # Mark all still-playing players as finished
        for p in self.player_ids.filtered(lambda p: p.state == 'playing'):
            p.write({'state': 'finished', 'finish_time': now})

        # Winner: most tasks; lower id breaks ties deterministically
        winner = max(self.player_ids, key=lambda p: (p.ta_completed_count, -p.id))
        self.write({
            'state': 'finished',
            'winner_id': winner.user_id.id,
            'end_time': now,
        })

        elo_changes = self.env['speedrun.profile'].sudo()._process_game_results(self.sudo())
        payload = self._build_game_over_payload()
        payload['elo_changes'] = elo_changes
        self._bus_send('speedrun/game_over', payload)

        if self.tournament_match_id:
            self.tournament_match_id.sudo()._on_game_over()

        return {'success': True}

    # ------------------------------------------------------------------
    # Payload builders
    # ------------------------------------------------------------------

    def _build_round_over_payload(self):
        """Build payload for round_over bus notification."""
        round_results = self.round_result_ids.filtered(
            lambda r: r.round_number == self.current_round
        ).sorted('rank')
        return {
            'current_round': self.current_round,
            'total_rounds': self.total_rounds,
            'game_mode': self.game_mode,
            'rounds_to_win': self.rounds_to_win,
            'round_results': [{
                'user_id': r.user_id.id,
                'user_name': r.user_id.name,
                'rank': r.rank,
                'duration_ms': r.duration_ms,
                'points': r.points,
            } for r in round_results],
            'standings': self._build_standings(),
        }

    def _build_game_over_payload(self):
        """Build payload for game_over bus notification."""
        return {
            'winner_id': self.winner_id.id,
            'winner_name': self.winner_id.name,
            'standings': self._build_standings(),
            'total_rounds': self.total_rounds,
            'game_mode': self.game_mode,
            'rounds_to_win': self.rounds_to_win,
        }

    def _build_standings(self):
        """Build current standings sorted by game mode priority."""
        if self.game_mode == 'battle_royale':
            # Most lives remaining wins; score breaks ties
            players = self.player_ids.sorted(lambda p: (-p.lives_remaining, -p.score))
        elif self.game_mode == 'best_of':
            players = self.player_ids.sorted(lambda p: (-p.round_wins, -p.score))
        elif self.game_mode == 'time_attack':
            players = self.player_ids.sorted(lambda p: -p.ta_completed_count)
        else:
            players = self.player_ids.sorted(lambda p: -p.score)
        return [{
            'user_id': p.user_id.id,
            'user_name': p.user_id.name,
            'score': p.score,
            'round_wins': p.round_wins,
            'lives_remaining': p.lives_remaining,
            'ta_completed_count': p.ta_completed_count,
        } for p in players]

    def _get_game_info(self):
        """Return game info dict for the frontend."""
        self.ensure_one()
        players = []
        if self.game_mode == 'battle_royale':
            sorted_players = self.player_ids.sorted(lambda p: (-p.lives_remaining, -p.score))
        elif self.game_mode == 'best_of':
            sorted_players = self.player_ids.sorted(lambda p: (-p.round_wins, -p.score))
        elif self.game_mode == 'time_attack':
            sorted_players = self.player_ids.sorted(lambda p: -p.ta_completed_count)
        else:
            sorted_players = self.player_ids.sorted(lambda p: -p.score)
        for p in sorted_players:
            players.append({
                'user_id': p.user_id.id,
                'user_name': p.user_id.name,
                'state': p.state,
                'score': p.score,
                'round_wins': p.round_wins,
                'lives_remaining': p.lives_remaining,
                'ta_completed_count': p.ta_completed_count,
                'ta_task_index': p.ta_task_index,
                'duration_ms': p.duration_ms if p.state == 'finished' else None,
            })

        # Round history
        rounds = []
        for rnd in range(1, self.current_round + 1):
            rnd_results = self.round_result_ids.filtered(lambda r: r.round_number == rnd).sorted('rank')
            rounds.append({
                'round_number': rnd,
                'task_name': rnd_results[0].task_id.name if rnd_results else '',
                'results': [{
                    'user_id': r.user_id.id,
                    'user_name': r.user_id.name,
                    'rank': r.rank,
                    'duration_ms': r.duration_ms,
                    'points': r.points,
                } for r in rnd_results],
            })

        # For Time Attack: task_name/description are mode-level labels, not round tasks
        if self.game_mode == 'time_attack':
            task_name = '⏱ Time Attack'
            minutes = self.ta_duration // 60
            task_description = (
                f'Complete as many tasks as you can in {minutes} minute'
                f'{"s" if minutes != 1 else ""}!'
            )
        else:
            task_name = self.task_id.name if self.task_id else None
            task_description = self.task_id.description if self.task_id else None

        info = {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'state': self.state,
            'host_id': self.host_id.id,
            'host_name': self.host_id.name,
            'is_ranked': self.is_ranked,
            'task_groups': [{
                'id': g.id,
                'name': g.name,
                'icon': g.icon or '',
                'image_url': g._image_url(),
            } for g in self.task_group_ids],
            'tournament_id': self.tournament_match_id.tournament_id.id if self.tournament_match_id else None,
            'tournament_match_label': self.tournament_match_id.label if self.tournament_match_id else None,
            'players': players,
            'player_count': len(self.player_ids),
            'max_players': self.max_players,
            'game_mode': self.game_mode,
            'total_rounds': self.total_rounds,
            'rounds_to_win': self.rounds_to_win,
            'br_lives': self.br_lives,
            'br_cutoff': self.br_cutoff,
            'ta_duration': self.ta_duration,
            'current_round': self.current_round,
            'task_name': task_name,
            'task_description': task_description,
            'start_time': fields.Datetime.to_string(self.start_time) if self.start_time else None,
            'end_time': fields.Datetime.to_string(self.end_time) if self.end_time else None,
            'winner_id': self.winner_id.id if self.winner_id else None,
            'winner_name': self.winner_id.name if self.winner_id else None,
            'standings': self._build_standings(),
            'rounds': rounds,
        }
        if self.state == 'countdown':
            elapsed = (fields.Datetime.now() - self.write_date).total_seconds()
            info['countdown_remaining'] = max(1, int(5 - elapsed))
        # For Time Attack: include the requesting user's current task
        if self.game_mode == 'time_attack' and self.state == 'running':
            uid = self.env.uid
            my_player = self.player_ids.filtered(lambda p: p.user_id.id == uid)
            if my_player:
                idx = my_player.ta_task_index
                seq = self.ta_task_seq_ids.filtered(lambda s: s.sequence == idx)
                info['ta_current_task_name'] = seq.task_id.name if seq else ''
                info['ta_current_task_description'] = seq.task_id.description or '' if seq else ''
        return info
