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
        return {'success': True}

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
        return {'success': True}

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
