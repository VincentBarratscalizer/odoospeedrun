from odoo import http
from odoo.http import request


class SpeedrunController(http.Controller):

    @http.route('/odoo_speedrun/create_game', type='jsonrpc', auth='user')
    def create_game(self, name=None, max_players=8, total_rounds=3):
        vals = {'max_players': max_players, 'total_rounds': int(total_rounds)}
        if name:
            vals['name'] = name
        game = request.env['speedrun.game'].create(vals)
        return game._get_game_info()

    @http.route('/odoo_speedrun/join_game', type='jsonrpc', auth='user')
    def join_game(self, code):
        game = request.env['speedrun.game'].search([
            ('code', '=', code.upper().strip()),
            ('state', '=', 'waiting'),
        ], limit=1)
        if not game:
            return {'error': 'Game not found or already started.'}
        try:
            game.action_join()
        except Exception as e:
            return {'error': str(e)}
        return game._get_game_info()

    @http.route('/odoo_speedrun/leave_game', type='jsonrpc', auth='user')
    def leave_game(self, game_id):
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        game.action_leave()
        return {'success': True}

    @http.route('/odoo_speedrun/start_game', type='jsonrpc', auth='user')
    def start_game(self, game_id):
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        try:
            game.action_start()
        except Exception as e:
            return {'error': str(e)}
        return {
            'success': True,
            'countdown_seconds': 5,
            'task_name': game.task_id.name,
            'task_description': game.task_id.description or '',
            'current_round': game.current_round,
            'total_rounds': game.total_rounds,
        }

    @http.route('/odoo_speedrun/begin_game', type='jsonrpc', auth='user')
    def begin_game(self, game_id):
        """Called after countdown finishes to officially start the timer."""
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        try:
            game.action_begin()
        except Exception as e:
            return {'error': str(e)}
        return game._get_game_info()

    @http.route('/odoo_speedrun/next_round', type='jsonrpc', auth='user')
    def next_round(self, game_id):
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        try:
            game.action_next_round()
        except Exception as e:
            return {'error': str(e)}
        return {
            'success': True,
            'countdown_seconds': 5,
            'task_name': game.task_id.name,
            'task_description': game.task_id.description or '',
            'current_round': game.current_round,
            'total_rounds': game.total_rounds,
        }

    @http.route('/odoo_speedrun/check_completion', type='jsonrpc', auth='user')
    def check_completion(self, game_id):
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        return game.action_check_completion()

    @http.route('/odoo_speedrun/game_info', type='jsonrpc', auth='user')
    def game_info(self, game_id):
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        return game._get_game_info()

    @http.route('/odoo_speedrun/my_active_game', type='jsonrpc', auth='user')
    def my_active_game(self):
        """Return the user's active game info, if any."""
        game = request.env['speedrun.game'].search([
            ('player_ids.user_id', '=', request.env.uid),
            ('state', 'in', ['waiting', 'running', 'countdown', 'round_finished', 'finished']),
        ], limit=1, order='create_date desc')
        if not game:
            return {}
        info = game._get_game_info()
        # Include countdown remaining seconds if in countdown state
        if game.state == 'countdown':
            from odoo import fields
            elapsed = (fields.Datetime.now() - game.write_date).total_seconds()
            info['countdown_remaining'] = max(1, int(5 - elapsed))
        # Include round results for the current round if available
        if game.state == 'round_finished' and game.current_round:
            rr = game.round_result_ids.filtered(
                lambda r: r.round_number == game.current_round
            ).sorted('rank')
            info['round_results'] = [{
                'user_id': r.user_id.id,
                'user_name': r.user_id.name,
                'rank': r.rank,
                'duration_ms': r.duration_ms,
                'points': r.points,
            } for r in rr]
        return info

    # ------------------------------------------------------------------
    # Matchmaking
    # ------------------------------------------------------------------
    @http.route('/odoo_speedrun/matchmaking/join', type='jsonrpc', auth='user')
    def matchmaking_join(self):
        try:
            request.env['speedrun.matchmaking.queue'].action_join_queue()
        except Exception as e:
            return {'error': str(e)}
        return request.env['speedrun.matchmaking.queue'].get_queue_status()

    @http.route('/odoo_speedrun/matchmaking/leave', type='jsonrpc', auth='user')
    def matchmaking_leave(self):
        request.env['speedrun.matchmaking.queue'].action_leave_queue()
        return {'success': True}

    @http.route('/odoo_speedrun/matchmaking/status', type='jsonrpc', auth='user')
    def matchmaking_status(self):
        return request.env['speedrun.matchmaking.queue'].get_queue_status()

    # ------------------------------------------------------------------
    # Personal stats
    # ------------------------------------------------------------------
    @http.route('/odoo_speedrun/my_stats', type='jsonrpc', auth='user')
    def my_stats(self):
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        return profile._get_stats_payload()

    @http.route('/odoo_speedrun/leaderboard', type='jsonrpc', auth='user')
    def leaderboard(self, limit=20):
        records = request.env['speedrun.leaderboard'].search([], limit=int(limit))
        return [{
            'user_id': r.user_id.id,
            'user_name': r.user_id.name,
            'total_games': r.total_games,
            'total_wins': r.total_wins,
            'best_time_ms': r.best_time_ms,
            'avg_time_ms': r.avg_time_ms,
            'win_rate': round(r.win_rate, 1),
        } for r in records]
