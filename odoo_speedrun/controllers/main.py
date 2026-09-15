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
    def create_game(self, name=None, max_players=8, total_rounds=3, group_ids=None,
                    game_mode='points', br_lives=3, br_cutoff=1, ta_duration=120):
        valid_modes = ('points', 'best_of', 'battle_royale', 'time_attack')
        vals = {
            'max_players': max_players,
            'total_rounds': int(total_rounds),
            'game_mode': game_mode if game_mode in valid_modes else 'points',
            'br_lives': max(1, int(br_lives or 3)),
            'br_cutoff': max(1, int(br_cutoff or 1)),
            'ta_duration': max(30, int(ta_duration or 120)),
        }
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
    # Time Attack
    # ------------------------------------------------------------------

    @http.route('/odoo_speedrun/time_attack/check', type='jsonrpc', auth='user')
    def time_attack_check(self, game_id):
        """Check whether the player completed their current Time Attack task."""
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        return game.action_ta_check_completion()

    @http.route('/odoo_speedrun/time_attack/end', type='jsonrpc', auth='user')
    def time_attack_end(self, game_id):
        """End a Time Attack game (host only — called when the client timer expires)."""
        game = request.env['speedrun.game'].browse(int(game_id))
        if not game.exists():
            return {'error': 'Game not found.'}
        try:
            return game.action_ta_end()
        except Exception as e:
            return {'error': str(e)}

    # ------------------------------------------------------------------
    # Daily Challenge
    # ------------------------------------------------------------------

    @http.route('/odoo_speedrun/daily/today', type='jsonrpc', auth='user')
    def daily_today(self):
        """Return today's daily task and the current user's status."""
        daily = request.env['speedrun.daily.task']._get_or_create_today()
        if not daily:
            return {'error': 'No tasks available for today.'}
        return daily._get_info(request.env.uid)

    @http.route('/odoo_speedrun/daily/start', type='jsonrpc', auth='user')
    def daily_start(self):
        """Record the start of the daily challenge for the current user."""
        daily = request.env['speedrun.daily.task']._get_or_create_today()
        if not daily:
            return {'error': 'No tasks available for today.'}
        return daily._start_for_user(request.env.uid)

    @http.route('/odoo_speedrun/daily/check', type='jsonrpc', auth='user')
    def daily_check(self):
        """Check whether the user completed the daily task."""
        daily = request.env['speedrun.daily.task']._get_or_create_today()
        if not daily:
            return {'error': 'No tasks available for today.'}
        return daily._check_completion(request.env.uid)

    @http.route('/odoo_speedrun/daily/leaderboard', type='jsonrpc', auth='user')
    def daily_leaderboard(self):
        """Return the full daily leaderboard."""
        daily = request.env['speedrun.daily.task']._get_or_create_today()
        if not daily:
            return []
        return daily._get_leaderboard_data(limit=100)

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
            'pity': profile._pity_payload(),
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
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        equipped_ids = {
            profile.equipped_peripheral_id.id,
            profile.equipped_display_id.id,
            profile.equipped_tech_id.id,
            profile.equipped_badge_id.id,
            profile.equipped_module_id.id,
            profile.equipped_desk_id.id,
        } - {False}
        collection = request.env['speedrun.player.equipment'].sudo().search([
            ('user_id', '=', request.env.uid),
        ], order='rarity desc, create_date desc')
        # Load all sets with completion info
        all_sets = request.env['speedrun.equipment.set'].sudo().search([], order='sequence')
        owned_equipment_ids = set(collection.mapped('equipment_id').ids)
        sets_data = []
        for s in all_sets:
            s_item_ids = s.item_ids.ids
            owned_count = sum(1 for iid in s_item_ids if iid in owned_equipment_ids)
            sets_data.append({
                'id': s.id,
                'name': s.name,
                'icon': s.icon or '',
                'title': s.title,
                'description': s.description or '',
                'score_bonus': s.score_bonus,
                'item_count': len(s_item_ids),
                'owned_count': owned_count,
                'complete': owned_count == len(s_item_ids) and len(s_item_ids) > 0,
                'item_ids': s_item_ids,
            })
        return {
            'items': [{
                'id': e.id,
                'equipment_id': e.equipment_id.id,
                'name': e.equipment_id.name,
                'rarity': e.rarity,
                'icon': e.equipment_id.icon or '',
                'description': e.equipment_id.description or '',
                'category': e.equipment_id.category or '',
                'count': e.count,
                'fusion_level': e.fusion_level,
                'item_score': e.item_score,
                'fusion_cost': profile._fusion_cost(e),
                'stats': e._stat_contribution(),
                'is_equipped': e.id in equipped_ids,
                'set_ids': e.equipment_id.set_ids.ids,
            } for e in collection],
            'sets': sets_data,
            'gear_score': profile.gear_score,
            'coins': profile.coins,
            'combat': profile._gear_stats_payload(),
            'classes': profile._class_info_payload()['classes'],
            'active_title': profile.active_title or '',
            'equipped': {
                'peripheral': profile._slot_payload(profile.equipped_peripheral_id),
                'display':    profile._slot_payload(profile.equipped_display_id),
                'tech':       profile._slot_payload(profile.equipped_tech_id),
                'badge':      profile._slot_payload(profile.equipped_badge_id),
                'module':     profile._slot_payload(profile.equipped_module_id),
                'desk':       profile._slot_payload(profile.equipped_desk_id),
            },
        }

    @http.route('/odoo_speedrun/equip_item', type='jsonrpc', auth='user')
    def equip_item(self, player_equip_id):
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        return profile.sudo()._equip_item(player_equip_id)

    @http.route('/odoo_speedrun/unequip_slot', type='jsonrpc', auth='user')
    def unequip_slot(self, slot):
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        return profile.sudo()._unequip_slot(slot)

    @http.route('/odoo_speedrun/fuse_equipment', type='jsonrpc', auth='user')
    def fuse_equipment(self, player_equip_id):
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        return profile.sudo()._fuse_equipment(player_equip_id)

    # ------------------------------------------------------------------
    # Arena (avatar PvP battles)
    # ------------------------------------------------------------------
    @http.route('/odoo_speedrun/my_combat_stats', type='jsonrpc', auth='user')
    def my_combat_stats(self):
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        return profile._self_combat_payload()

    @http.route('/odoo_speedrun/arena_opponents', type='jsonrpc', auth='user')
    def arena_opponents(self, limit=24):
        Profile = request.env['speedrun.profile'].sudo()
        me = Profile._get_or_create(request.env.user)
        # Ensure every real (internal) user has a profile so there's someone to fight.
        users = request.env['res.users'].sudo().search([
            ('share', '=', False),
            ('active', '=', True),
            ('id', 'not in', [request.env.uid, request.env.ref('base.user_root').id]),
        ])
        Profile._get_or_create(users)
        opponents = Profile.search([('id', '!=', me.id), ('user_id', 'in', users.ids)])
        # Closest arena rating first (more interesting matchups).
        opponents = opponents.sorted(key=lambda p: abs(p.arena_rating - me.arena_rating))[:int(limit)]
        return {
            'me': me._self_combat_payload(),
            'opponents': [p._combat_payload() for p in opponents],
        }

    @http.route('/odoo_speedrun/arena_fight', type='jsonrpc', auth='user')
    def arena_fight(self, opponent_profile_id):
        Profile = request.env['speedrun.profile'].sudo()
        me = Profile._get_or_create(request.env.user)
        opponent = Profile.browse(int(opponent_profile_id)).exists()
        if not opponent:
            return {'error': 'Opponent not found.'}
        if opponent.id == me.id:
            return {'error': 'You cannot challenge yourself.'}
        quota = me._arena_quota()
        if quota['remaining'] <= 0:
            return {
                'error': 'Quota de combats journalier atteint. Revenez demain !',
                'quota_reached': True,
                'arena_quota': quota,
            }
        try:
            result = request.env['speedrun.battle'].sudo()._fight(me, opponent)
        except Exception as e:
            return {'error': str(e)}
        me._consume_fight()
        result['arena_quota'] = me._arena_quota()
        return result

    # ------------------------------------------------------------------
    # Unified leaderboards (ELO / Equipment / Arena / Tasks)
    # ------------------------------------------------------------------
    @http.route('/odoo_speedrun/leaderboard_data', type='jsonrpc', auth='user')
    def leaderboard_data(self, kind='elo', task_id=None, category_id=None, limit=25):
        uid = request.env.uid
        Profile = request.env['speedrun.profile'].sudo()
        limit = int(limit)

        def base(p):
            return {
                'user_id': p.user_id.id,
                'name': p.user_id.name,
                'avatar_url': f'/web/image/res.users/{p.user_id.id}/avatar_128',
                'level': p.level,
                'is_me': p.user_id.id == uid,
            }

        if kind == 'gear':
            profiles = Profile.search([('gear_score', '>', 0)],
                                      order='gear_score desc', limit=limit)
            rows = [{**base(p), 'value': p.gear_score, 'title': p.active_title or '',
                     'power': p.power} for p in profiles]
            return {'kind': kind, 'rows': rows}

        if kind == 'arena':
            profiles = Profile.search([('arena_battles', '>', 0)],
                                      order='arena_rating desc, arena_wins desc', limit=limit)
            rows = [{**base(p), 'value': p.arena_rating, 'wins': p.arena_wins,
                     'losses': p.arena_losses, 'win_rate': round(p.arena_win_rate, 1),
                     'power': p.power} for p in profiles]
            return {'kind': kind, 'rows': rows}

        if kind == 'clans':
            rows = request.env['speedrun.clan'].sudo()._leaderboard_rows(limit=limit)
            return {'kind': kind, 'rows': rows}

        if kind == 'perf':
            # Per-task ranking by best-time percentile (100 = record). No confrontation.
            Score = request.env['speedrun.task.score'].sudo()
            tasks = [{'id': t.id, 'name': t.name}
                     for t in Score.search([]).task_id.sorted('name')]
            selected = int(task_id) if task_id else (tasks[0]['id'] if tasks else None)
            rows = []
            if selected:
                all_scores = Score.search(
                    [('task_id', '=', selected), ('best_time_ms', '>', 0)],
                    order='best_time_ms asc')
                total = len(all_scores)
                for i, s in enumerate(all_scores[:limit]):
                    rating = round(100.0 * (total - i) / total) if total else 0
                    rows.append({
                        'user_id': s.user_id.id,
                        'name': s.user_id.name,
                        'avatar_url': f'/web/image/res.users/{s.user_id.id}/avatar_128',
                        'value': rating,
                        'best_time_ms': s.best_time_ms,
                        'rounds': s.rounds_played,
                        'wins': s.rounds_won,
                        'is_me': s.user_id.id == uid,
                    })
            return {'kind': kind, 'rows': rows, 'tasks': tasks, 'selected_task_id': selected}

        if kind == 'domains':
            # Per-category ranking: average per-task percentile over the category.
            Group = request.env['speedrun.task.group'].sudo()
            groups = Group.search([]).filtered(lambda g: g.task_ids)
            cats = [{'id': g.id, 'name': g.name} for g in groups.sorted('name')]
            selected = int(category_id) if category_id else (cats[0]['id'] if cats else None)
            rows = []
            if selected:
                grp = Group.browse(selected)
                Score = request.env['speedrun.task.score'].sudo()
                scores = Score.search([
                    ('task_id', 'in', grp.task_ids.ids), ('best_time_ms', '>', 0)])
                by_task = {}
                for s in scores:
                    by_task.setdefault(s.task_id.id, []).append((s.user_id.id, s.best_time_ms))
                user_vals = {}
                for _tid, lst in by_task.items():
                    lst.sort(key=lambda x: x[1])  # fastest first
                    n = len(lst)
                    for idx, (u, _t) in enumerate(lst):
                        user_vals.setdefault(u, []).append(100.0 * (n - idx) / n)
                ranked = sorted(
                    ((u, sum(v) / len(v), len(v)) for u, v in user_vals.items()),
                    key=lambda r: -r[1])[:limit]
                users = request.env['res.users'].sudo().browse([u for u, _, _ in ranked])
                name_by_id = {u.id: u.name for u in users}
                for u, rating, cnt in ranked:
                    rows.append({
                        'user_id': u,
                        'name': name_by_id.get(u, ''),
                        'avatar_url': f'/web/image/res.users/{u}/avatar_128',
                        'value': round(rating),
                        'tasks': cnt,
                        'is_me': u == uid,
                    })
            return {'kind': kind, 'rows': rows, 'categories': cats, 'selected_category_id': selected}

        if kind == 'tasks':
            Score = request.env['speedrun.task.score'].sudo()
            tasks = [{'id': t.id, 'name': t.name}
                     for t in Score.search([]).task_id.sorted('name')]
            selected = int(task_id) if task_id else (tasks[0]['id'] if tasks else None)
            rows = []
            if selected:
                scores = Score.search([('task_id', '=', selected)],
                                      order='elo desc, best_time_ms asc', limit=limit)
                rows = [{
                    'user_id': s.user_id.id,
                    'name': s.user_id.name,
                    'avatar_url': f'/web/image/res.users/{s.user_id.id}/avatar_128',
                    'value': s.elo,
                    'peak': s.peak_elo,
                    'rounds': s.rounds_played,
                    'wins': s.rounds_won,
                    'best_time_ms': s.best_time_ms,
                    'is_me': s.user_id.id == uid,
                } for s in scores]
            return {'kind': kind, 'rows': rows, 'tasks': tasks, 'selected_task_id': selected}

        # default: global ELO
        profiles = Profile.search([('games_played', '>', 0)],
                                  order='elo desc, peak_elo desc', limit=limit)
        rows = [{**base(p), 'value': p.elo, 'peak': p.peak_elo,
                 'games': p.games_played, 'wins': p.games_won,
                 'win_rate': round(p.win_rate, 1)} for p in profiles]
        return {'kind': 'elo', 'rows': rows}

    # ------------------------------------------------------------------
    # Clans
    # ------------------------------------------------------------------
    @http.route('/odoo_speedrun/clan/my', type='jsonrpc', auth='user')
    def clan_my(self):
        """Return the current user's clan info + the list of clans to browse."""
        Clan = request.env['speedrun.clan'].sudo()
        my_clan = Clan._my_clan()
        return {
            'clan': my_clan._info() if my_clan else None,
            'clans': Clan._browse_list() if not my_clan else [],
        }

    @http.route('/odoo_speedrun/clan/list', type='jsonrpc', auth='user')
    def clan_list(self):
        return request.env['speedrun.clan'].sudo()._browse_list()

    @http.route('/odoo_speedrun/clan/create', type='jsonrpc', auth='user')
    def clan_create(self, name, tag, emblem=None, description=None, motto=None):
        try:
            clan = request.env['speedrun.clan'].sudo()._create_clan(
                name, tag, emblem=emblem, description=description, motto=motto)
        except Exception as e:
            return {'error': str(e)}
        return {'clan': clan._info()}

    @http.route('/odoo_speedrun/clan/join', type='jsonrpc', auth='user')
    def clan_join(self, clan_id):
        clan = request.env['speedrun.clan'].sudo().browse(int(clan_id)).exists()
        if not clan:
            return {'error': 'Clan introuvable.'}
        try:
            clan._join()
        except Exception as e:
            return {'error': str(e)}
        return {'clan': clan._info()}

    @http.route('/odoo_speedrun/clan/leave', type='jsonrpc', auth='user')
    def clan_leave(self):
        clan = request.env['speedrun.clan'].sudo()._my_clan()
        if not clan:
            return {'error': "Vous n'appartenez à aucun clan."}
        try:
            clan._leave()
        except Exception as e:
            return {'error': str(e)}
        return {'success': True}

    @http.route('/odoo_speedrun/clan/kick', type='jsonrpc', auth='user')
    def clan_kick(self, profile_id):
        clan = request.env['speedrun.clan'].sudo()._my_clan()
        if not clan:
            return {'error': "Vous n'appartenez à aucun clan."}
        try:
            clan._kick(profile_id)
        except Exception as e:
            return {'error': str(e)}
        return {'clan': clan._info()}

    @http.route('/odoo_speedrun/clan/transfer_lead', type='jsonrpc', auth='user')
    def clan_transfer_lead(self, profile_id):
        clan = request.env['speedrun.clan'].sudo()._my_clan()
        if not clan:
            return {'error': "Vous n'appartenez à aucun clan."}
        try:
            clan._transfer_lead(profile_id)
        except Exception as e:
            return {'error': str(e)}
        return {'clan': clan._info()}

    @http.route('/odoo_speedrun/clan/disband', type='jsonrpc', auth='user')
    def clan_disband(self):
        clan = request.env['speedrun.clan'].sudo()._my_clan()
        if not clan:
            return {'error': "Vous n'appartenez à aucun clan."}
        try:
            clan._disband()
        except Exception as e:
            return {'error': str(e)}
        return {'success': True}

    # --- Wars ---
    @http.route('/odoo_speedrun/clan/declare_war', type='jsonrpc', auth='user')
    def clan_declare_war(self, target_clan_id):
        try:
            request.env['speedrun.clan.war'].sudo()._declare(target_clan_id)
        except Exception as e:
            return {'error': str(e)}
        clan = request.env['speedrun.clan'].sudo()._my_clan()
        return {'clan': clan._info() if clan else None}

    def _my_war_action(self, war_id, method):
        war = request.env['speedrun.clan.war'].sudo().browse(int(war_id)).exists()
        if not war:
            return {'error': 'Guerre introuvable.'}
        try:
            getattr(war, method)()
        except Exception as e:
            return {'error': str(e)}
        clan = request.env['speedrun.clan'].sudo()._my_clan()
        return {'clan': clan._info() if clan else None}

    @http.route('/odoo_speedrun/clan/accept_war', type='jsonrpc', auth='user')
    def clan_accept_war(self, war_id):
        return self._my_war_action(war_id, '_accept')

    @http.route('/odoo_speedrun/clan/decline_war', type='jsonrpc', auth='user')
    def clan_decline_war(self, war_id):
        return self._my_war_action(war_id, '_decline')

    @http.route('/odoo_speedrun/clan/cancel_war', type='jsonrpc', auth='user')
    def clan_cancel_war(self, war_id):
        return self._my_war_action(war_id, '_cancel')

    @http.route('/odoo_speedrun/clan/war_task/start', type='jsonrpc', auth='user')
    def clan_war_task_start(self, war_id, kind='raid'):
        war = request.env['speedrun.clan.war'].sudo().browse(int(war_id)).exists()
        if not war:
            return {'error': 'Guerre introuvable.'}
        if kind != 'raid':
            return {'error': 'Épreuve invalide.'}
        return war._task_start('raid')

    @http.route('/odoo_speedrun/clan/war_task/check', type='jsonrpc', auth='user')
    def clan_war_task_check(self, war_id, kind='raid'):
        war = request.env['speedrun.clan.war'].sudo().browse(int(war_id)).exists()
        if not war:
            return {'error': 'Guerre introuvable.'}
        if kind != 'raid':
            return {'error': 'Épreuve invalide.'}
        return war._task_check('raid')

    @http.route('/odoo_speedrun/clan/active_raid', type='jsonrpc', auth='user')
    def clan_active_raid(self):
        """Return the current user's in-progress clan-war raid, for the systray."""
        clan = request.env['speedrun.clan'].sudo()._my_clan()
        if not clan:
            return {}
        war = clan._active_war()
        if not war or war.state != 'running':
            return {}
        return war._raid_systray_payload(request.env.user)

    @http.route('/odoo_speedrun/clan/war/fight', type='jsonrpc', auth='user')
    def clan_war_fight(self, war_id):
        """Trigger the current user's single arena attack; returns a battle replay."""
        war = request.env['speedrun.clan.war'].sudo().browse(int(war_id)).exists()
        if not war:
            return {'error': 'Guerre introuvable.'}
        return war._arena_fight()

    # ------------------------------------------------------------------
    # Classes (upgrade the element passive with coins)
    # ------------------------------------------------------------------
    @http.route('/odoo_speedrun/class/info', type='jsonrpc', auth='user')
    def class_info(self):
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        return profile._class_info_payload()

    @http.route('/odoo_speedrun/class/upgrade', type='jsonrpc', auth='user')
    def class_upgrade(self, element):
        profile = request.env['speedrun.profile'].sudo()._get_or_create(request.env.user)
        result = profile._upgrade_class(element)
        if result.get('success'):
            result['classes'] = profile._class_info_payload(recompute=False)['classes']
        return result

    # ------------------------------------------------------------------
    # Daily Shop
    # ------------------------------------------------------------------
    @http.route('/odoo_speedrun/shop/today', type='jsonrpc', auth='user')
    def shop_today(self):
        shop = request.env['speedrun.shop.day'].sudo()._get_or_create_today()
        return shop._get_info(request.env.user)

    @http.route('/odoo_speedrun/shop/buy', type='jsonrpc', auth='user')
    def shop_buy(self, equipment_id):
        shop = request.env['speedrun.shop.day'].sudo()._get_or_create_today()
        result = shop._buy(equipment_id)
        if result.get('success'):
            result['shop'] = shop._get_info(request.env.user)
        return result

    @http.route('/odoo_speedrun/arena_leaderboard', type='jsonrpc', auth='user')
    def arena_leaderboard(self, limit=20):
        profiles = request.env['speedrun.profile'].sudo().search(
            [('arena_battles', '>', 0)], order='arena_rating desc, arena_wins desc', limit=int(limit))
        return [{
            'user_id': p.user_id.id,
            'name': p.user_id.name,
            'avatar_url': f'/web/image/res.users/{p.user_id.id}/avatar_128',
            'arena_rating': p.arena_rating,
            'arena_wins': p.arena_wins,
            'arena_losses': p.arena_losses,
            'arena_win_rate': round(p.arena_win_rate, 1),
            'power': p.power,
            'level': p.level,
            'is_me': p.user_id.id == request.env.uid,
        } for p in profiles]
