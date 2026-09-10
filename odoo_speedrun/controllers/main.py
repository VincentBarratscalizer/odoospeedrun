import io

from odoo import http
from odoo.http import request, content_disposition


class SpeedrunController(http.Controller):

    @http.route('/odoo_speedrun/task_import_template', type='http', auth='user')
    def task_import_template(self, **kw):
        """Return a downloadable .xlsx template with two sheets: Tasks and Groups."""
        import xlsxwriter

        output = io.BytesIO()
        wb = xlsxwriter.Workbook(output, {'in_memory': True})
        bold = wb.add_format({'bold': True, 'bg_color': '#D9E1F2', 'border': 1})
        wrap = wb.add_format({'text_wrap': True, 'valign': 'top'})

        # --- Tasks sheet ---
        task_headers = [
            'name', 'description', 'target_model', 'verification_method',
            'verification_domain', 'verification_code', 'verification_count',
            'difficulty', 'required_modules', 'groups',
        ]
        ws = wb.add_worksheet('Tasks')
        ws.set_column(0, len(task_headers) - 1, 26, wrap)
        for col, header in enumerate(task_headers):
            ws.write(0, col, header, bold)
        # Example 1: domain verification
        ws.write_row(1, 0, [
            'Create a helpdesk ticket',
            'Create a new helpdesk ticket with a subject.',
            'helpdesk.ticket',
            'domain',
            '[["create_uid","=","__uid__"],["create_date",">=","__game_start__"]]',
            '',
            1,
            'easy',
            'helpdesk',
            'Support',
        ])
        # Example 2: python verification (multi-line code)
        ws.write_row(2, 0, [
            'Confirm a sale and create its invoice',
            'Create a quotation, confirm it, then create an invoice from it.',
            'sale.order',
            'python',
            '[]',
            "orders = env['sale.order'].with_user(uid).search([\n"
            "    ('create_uid', '=', uid),\n"
            "    ('create_date', '>=', start_time),\n"
            "    ('state', '=', 'sale'),\n"
            "])\n"
            "result = any(o.invoice_ids for o in orders)",
            1,
            'hard',
            'sale,account',
            'Sales',
        ])

        # --- Groups sheet ---
        group_headers = ['name', 'icon', 'sequence']
        gs = wb.add_worksheet('Groups')
        gs.set_column(0, 0, 26)
        gs.set_column(1, 2, 14)
        for col, header in enumerate(group_headers):
            gs.write(0, col, header, bold)
        gs.write_row(1, 0, ['Support', '\U0001F3AB', 140])
        gs.write_row(2, 0, ['Sales', '\U0001F4B0', 20])

        wb.close()
        output.seek(0)
        return request.make_response(
            output.read(),
            headers=[
                ('Content-Type',
                 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'),
                ('Content-Disposition',
                 content_disposition('speedrun_tasks_template.xlsx')),
            ],
        )

    @http.route('/odoo_speedrun/create_game', type='jsonrpc', auth='user')
    def create_game(self, name=None, max_players=8, total_rounds=3, group_ids=None):
        vals = {'max_players': max_players, 'total_rounds': int(total_rounds)}
        if name:
            vals['name'] = name
        if group_ids:
            valid = request.env['speedrun.task.group'].browse(
                [int(g) for g in group_ids]
            ).exists()
            if valid:
                vals['task_group_ids'] = [(6, 0, valid.ids)]
        game = request.env['speedrun.game'].create(vals)
        return game._get_game_info()

    @http.route('/odoo_speedrun/task_groups', type='jsonrpc', auth='user')
    def task_groups(self):
        """Return the selectable task groups (those with playable tasks)."""
        groups = request.env['speedrun.task.group']._get_selectable_groups()
        return [{
            'id': g.id,
            'name': g.name,
            'icon': g.icon or '',
            'image_url': g._image_url(),
            'available_task_count': g.available_task_count,
        } for g in groups]

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

    @http.route('/odoo_speedrun/surrender', type='jsonrpc', auth='user')
    def surrender(self, game_id):
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        return game.action_surrender()

    @http.route('/odoo_speedrun/game_info', type='jsonrpc', auth='user')
    def game_info(self, game_id):
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        return game._get_game_info()

    @http.route('/odoo_speedrun/dismiss_game', type='jsonrpc', auth='user')
    def dismiss_game(self, game_id):
        """Mark a finished game as dismissed so it isn't restored on refresh."""
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        game.action_dismiss()
        return {'success': True}

    @http.route('/odoo_speedrun/my_active_game', type='jsonrpc', auth='user')
    def my_active_game(self):
        """Return the user's current game info, if any.

        Only the user's single most recent game is considered — we never fall
        back to older games. That game is restored when it is either in
        progress, or finished but not yet dismissed (so results survive a
        refresh until the player clicks "Play again"). Once dismissed, nothing
        is restored and the user lands back in the arena."""
        uid = request.env.uid
        game = request.env['speedrun.game'].search([
            ('player_ids.user_id', '=', uid),
        ], limit=1, order='create_date desc')
        if not game:
            return {}
        in_progress = game.state in ('waiting', 'countdown', 'running', 'round_finished')
        if not in_progress:
            player = game.player_ids.filtered(lambda p: p.user_id.id == uid)
            if game.state != 'finished' or player.dismissed:
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

    # ------------------------------------------------------------------
    # Tournaments
    # ------------------------------------------------------------------
    @http.route('/odoo_speedrun/tournament/list', type='jsonrpc', auth='user')
    def tournament_list(self):
        return request.env['speedrun.tournament']._get_list()

    @http.route('/odoo_speedrun/tournament/get', type='jsonrpc', auth='user')
    def tournament_get(self, tournament_id):
        tournament = request.env['speedrun.tournament'].browse(int(tournament_id))
        if not tournament.exists():
            return {'error': 'Tournament not found.'}
        return tournament._get_data()

    @http.route('/odoo_speedrun/tournament/create', type='jsonrpc', auth='user')
    def tournament_create(self, name=None, match_best_of='3', seeding_method='elo',
                          max_participants=0):
        vals = {
            'match_best_of': str(match_best_of),
            'seeding_method': seeding_method,
            'max_participants': int(max_participants or 0),
        }
        if name:
            vals['name'] = name
        tournament = request.env['speedrun.tournament'].create(vals)
        # Organizer auto-registers.
        tournament.action_register()
        return tournament._get_data()

    @http.route('/odoo_speedrun/tournament/register', type='jsonrpc', auth='user')
    def tournament_register(self, tournament_id):
        tournament = request.env['speedrun.tournament'].browse(int(tournament_id))
        if not tournament.exists():
            return {'error': 'Tournament not found.'}
        try:
            tournament.action_register()
        except Exception as e:
            return {'error': str(e)}
        return tournament._get_data()

    @http.route('/odoo_speedrun/tournament/unregister', type='jsonrpc', auth='user')
    def tournament_unregister(self, tournament_id):
        tournament = request.env['speedrun.tournament'].browse(int(tournament_id))
        if not tournament.exists():
            return {'error': 'Tournament not found.'}
        try:
            tournament.action_unregister()
        except Exception as e:
            return {'error': str(e)}
        return tournament._get_data()

    @http.route('/odoo_speedrun/tournament/close_registration', type='jsonrpc', auth='user')
    def tournament_close_registration(self, tournament_id):
        tournament = request.env['speedrun.tournament'].browse(int(tournament_id))
        if not tournament.exists():
            return {'error': 'Tournament not found.'}
        try:
            tournament.action_close_registration()
        except Exception as e:
            return {'error': str(e)}
        return tournament._get_data()

    @http.route('/odoo_speedrun/tournament/reopen_registration', type='jsonrpc', auth='user')
    def tournament_reopen_registration(self, tournament_id):
        tournament = request.env['speedrun.tournament'].browse(int(tournament_id))
        if not tournament.exists():
            return {'error': 'Tournament not found.'}
        try:
            tournament.action_reopen_registration()
        except Exception as e:
            return {'error': str(e)}
        return tournament._get_data()

    @http.route('/odoo_speedrun/tournament/auto_seed', type='jsonrpc', auth='user')
    def tournament_auto_seed(self, tournament_id, method='elo'):
        tournament = request.env['speedrun.tournament'].browse(int(tournament_id))
        if not tournament.exists():
            return {'error': 'Tournament not found.'}
        try:
            tournament.action_auto_seed(method)
        except Exception as e:
            return {'error': str(e)}
        return tournament._get_data()

    @http.route('/odoo_speedrun/tournament/move_seed', type='jsonrpc', auth='user')
    def tournament_move_seed(self, tournament_id, user_id, direction):
        tournament = request.env['speedrun.tournament'].browse(int(tournament_id))
        if not tournament.exists():
            return {'error': 'Tournament not found.'}
        try:
            tournament.action_move_seed(int(user_id), direction)
        except Exception as e:
            return {'error': str(e)}
        return tournament._get_data()

    @http.route('/odoo_speedrun/tournament/start', type='jsonrpc', auth='user')
    def tournament_start(self, tournament_id):
        tournament = request.env['speedrun.tournament'].browse(int(tournament_id))
        if not tournament.exists():
            return {'error': 'Tournament not found.'}
        try:
            tournament.action_generate_bracket()
        except Exception as e:
            return {'error': str(e)}
        return tournament._get_data()

    @http.route('/odoo_speedrun/tournament/play_match', type='jsonrpc', auth='user')
    def tournament_play_match(self, match_id):
        match = request.env['speedrun.tournament.match'].browse(int(match_id))
        if not match.exists():
            return {'error': 'Match not found.'}
        try:
            return {'game_info': match.action_play()}
        except Exception as e:
            return {'error': str(e)}

    @http.route('/odoo_speedrun/tournament/cancel', type='jsonrpc', auth='user')
    def tournament_cancel(self, tournament_id):
        tournament = request.env['speedrun.tournament'].browse(int(tournament_id))
        if not tournament.exists():
            return {'error': 'Tournament not found.'}
        try:
            tournament.action_cancel()
        except Exception as e:
            return {'error': str(e)}
        return {'success': True}

    # ------------------------------------------------------------------
    # Gacha / Chests
    # ------------------------------------------------------------------
    @http.route('/odoo_speedrun/my_chests', type='jsonrpc', auth='user')
    def my_chests(self):
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        pending = request.env['speedrun.player.chest'].sudo().search([
            ('user_id', '=', request.env.uid),
            ('state', '=', 'pending'),
        ], order='create_date desc')
        from odoo import fields as F
        today = F.Date.today()
        return {
            'chests': [{'id': c.id, 'rarity': c.rarity, 'source': c.source} for c in pending],
            'daily_available': profile.last_daily_chest != today,
        }

    @http.route('/odoo_speedrun/open_chest', type='jsonrpc', auth='user')
    def open_chest(self, chest_id):
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        equipment = profile.sudo()._open_chest(chest_id)
        if equipment is None:
            return {'error': 'Chest not found or already opened.'}
        return {'equipment': equipment}

    @http.route('/odoo_speedrun/daily_chest', type='jsonrpc', auth='user')
    def daily_chest(self):
        from odoo import fields as F
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        today = F.Date.today()
        if profile.last_daily_chest == today:
            return {'error': 'Daily chest already claimed today.'}
        profile.sudo().write({'last_daily_chest': today})
        chest = profile.sudo()._award_chest('common', source='daily')
        return {'chest_id': chest.id, 'rarity': chest.rarity}

    @http.route('/odoo_speedrun/my_equipment', type='jsonrpc', auth='user')
    def my_equipment(self):
        collection = request.env['speedrun.player.equipment'].sudo().search([
            ('user_id', '=', request.env.uid),
        ], order='rarity desc, create_date desc')
        return [{
            'id': e.equipment_id.id,
            'name': e.equipment_id.name,
            'rarity': e.rarity,
            'icon': e.equipment_id.icon or '',
            'description': e.equipment_id.description or '',
            'count': e.count,
        } for e in collection]
