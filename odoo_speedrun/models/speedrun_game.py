import random
import string

from odoo import api, fields, models
from odoo.exceptions import UserError, AccessError


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
        ('finished', 'Finished'),
    ], default='waiting', required=True, readonly=True)
    host_id = fields.Many2one('res.users', string='Host', required=True, default=lambda self: self.env.uid)
    player_ids = fields.One2many('speedrun.player', 'game_id', string='Players')
    player_count = fields.Integer(compute='_compute_player_count', store=True)
    task_id = fields.Many2one('speedrun.task', string='Task', readonly=True)
    start_time = fields.Datetime(readonly=True)
    end_time = fields.Datetime(readonly=True)
    winner_id = fields.Many2one('res.users', string='Winner', readonly=True)
    max_players = fields.Integer(default=8)

    @api.depends('player_ids')
    def _compute_player_count(self):
        for game in self:
            game.player_count = len(game.player_ids)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('code'):
                vals['code'] = self._generate_code()
        games = super().create(vals_list)
        # Auto-join the host as first player
        for game in games:
            self.env['speedrun.player'].create({
                'game_id': game.id,
                'user_id': game.host_id.id,
                'state': 'waiting',
            })
        return games

    @staticmethod
    def _generate_code():
        """Generate a random 6-character uppercase join code."""
        return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))

    def action_join(self, user_id=None):
        """Add a player to this game."""
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
        """Remove a player from this game."""
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

    def action_start(self):
        """Start the game (host only). Picks a random task and begins countdown."""
        self.ensure_one()
        if self.env.uid != self.host_id.id:
            raise AccessError("Only the host can start the game.")
        if self.state != 'waiting':
            raise UserError("Game has already started.")
        if len(self.player_ids) < 1:
            raise UserError("Need at least 1 player to start.")

        # Pick a random task
        available_tasks = self.env['speedrun.task']._get_available_tasks()
        if not available_tasks:
            raise UserError("No tasks available. Please contact an administrator.")
        task = random.choice(available_tasks.ids)
        task = self.env['speedrun.task'].browse(task)

        self.write({
            'task_id': task.id,
            'state': 'countdown',
        })
        self.player_ids.write({'state': 'playing'})

        self._bus_send('speedrun/countdown_start', {
            'countdown_seconds': 3,
            'game_id': self.id,
        })
        return True

    def action_begin(self):
        """Called after countdown. Officially starts the game timer."""
        self.ensure_one()
        if self.state != 'countdown':
            raise UserError("Game is not in countdown state.")
        now = fields.Datetime.now()
        self.write({
            'state': 'running',
            'start_time': now,
        })
        self._bus_send('speedrun/game_started', {
            'game_id': self.id,
            'task_name': self.task_id.name,
            'task_description': self.task_id.description or '',
            'start_time': fields.Datetime.to_string(now),
        })
        return True

    def action_check_completion(self, user_id=None):
        """Check if a user has completed the current task.

        :return: dict with 'success' (bool) and optionally 'is_winner' (bool)
        """
        self.ensure_one()
        user_id = user_id or self.env.uid
        if self.state != 'running':
            return {'success': False, 'error': 'Game is not running.'}

        player = self.player_ids.filtered(lambda p: p.user_id.id == user_id)
        if not player:
            return {'success': False, 'error': 'You are not in this game.'}
        if player.state == 'finished':
            return {'success': False, 'error': 'You have already finished.'}

        # Verify the task
        # sudo: speedrun.task - verification needs to read any model
        completed = self.sudo().task_id._verify_completion(user_id, self.start_time)
        if not completed:
            return {'success': False, 'error': 'Task not completed yet. Keep going!'}

        # Mark the player as finished
        now = fields.Datetime.now()
        player.write({
            'state': 'finished',
            'finish_time': now,
        })

        # Calculate duration
        duration_ms = int((now - self.start_time).total_seconds() * 1000)

        # Check if this is the first finisher (winner)
        is_winner = not self.winner_id
        if is_winner:
            self.write({
                'winner_id': user_id,
                'end_time': now,
                'state': 'finished',
            })
            # Mark remaining players as DNF
            self.player_ids.filtered(lambda p: p.state == 'playing').write({'state': 'dnf'})

        user = self.env['res.users'].browse(user_id)
        self._bus_send('speedrun/player_finished', {
            'user_id': user_id,
            'user_name': user.name,
            'duration_ms': duration_ms,
            'is_winner': is_winner,
        })

        if is_winner:
            # Build results
            results = []
            for p in self.player_ids.sorted(lambda p: (p.state != 'finished', p.finish_time or now)):
                results.append({
                    'user_id': p.user_id.id,
                    'user_name': p.user_id.name,
                    'state': p.state,
                    'duration_ms': p.duration_ms if p.state == 'finished' else None,
                })
            self._bus_send('speedrun/game_over', {
                'winner_id': user_id,
                'winner_name': user.name,
                'results': results,
            })

        return {'success': True, 'is_winner': is_winner, 'duration_ms': duration_ms}

    def _get_game_info(self):
        """Return game info dict for the frontend."""
        self.ensure_one()
        players = []
        for p in self.player_ids:
            players.append({
                'user_id': p.user_id.id,
                'user_name': p.user_id.name,
                'state': p.state,
                'duration_ms': p.duration_ms if p.state == 'finished' else None,
            })
        return {
            'id': self.id,
            'name': self.name,
            'code': self.code,
            'state': self.state,
            'host_id': self.host_id.id,
            'host_name': self.host_id.name,
            'players': players,
            'player_count': len(self.player_ids),
            'max_players': self.max_players,
            'task_name': self.task_id.name if self.task_id else None,
            'task_description': self.task_id.description if self.task_id else None,
            'start_time': fields.Datetime.to_string(self.start_time) if self.start_time else None,
            'end_time': fields.Datetime.to_string(self.end_time) if self.end_time else None,
            'winner_id': self.winner_id.id if self.winner_id else None,
            'winner_name': self.winner_id.name if self.winner_id else None,
        }
