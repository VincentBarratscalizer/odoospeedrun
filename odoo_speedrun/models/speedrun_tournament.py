import random

from odoo import api, fields, models
from odoo.exceptions import AccessError, UserError


def _next_pow2(n):
    p = 1
    while p < n:
        p *= 2
    return p


def _seed_order(size):
    """Return the standard single-elimination seeding order for a power-of-2
    bracket ``size``. Seed 1 and seed 2 can only meet in the final.

    e.g. size 4 -> [1, 4, 2, 3] ; size 8 -> [1, 8, 4, 5, 2, 7, 3, 6]
    """
    order = [1, 2]
    while len(order) < size:
        length = len(order) * 2
        new = []
        for s in order:
            new.append(s)
            new.append(length + 1 - s)
        order = new
    return order


class SpeedrunTournament(models.Model):
    _name = 'speedrun.tournament'
    _description = 'Speedrun Tournament'
    _order = 'create_date desc'

    name = fields.Char(required=True, default=lambda self: 'Tournament #%s' % random.randint(100, 999))
    state = fields.Selection([
        ('registration', 'Registration Open'),
        ('seeding', 'Seeding'),
        ('running', 'Running'),
        ('finished', 'Finished'),
    ], default='registration', required=True, readonly=True)
    organizer_id = fields.Many2one('res.users', string='Organizer', required=True,
                                   default=lambda self: self.env.uid, readonly=True)
    match_best_of = fields.Selection([
        ('3', 'Best of 3'),
        ('5', 'Best of 5'),
    ], default='3', required=True, string='Match Format',
        help="Each tournament match is a 1v1 best-of series.")
    seeding_method = fields.Selection([
        ('elo', 'By ELO'),
        ('random', 'Random'),
        ('manual', 'Manual'),
    ], default='elo', required=True)
    max_participants = fields.Integer(default=0, help="0 = unlimited.")

    registration_ids = fields.One2many('speedrun.tournament.registration', 'tournament_id',
                                        string='Registrations')
    match_ids = fields.One2many('speedrun.tournament.match', 'tournament_id', string='Matches')
    participant_count = fields.Integer(compute='_compute_participant_count', store=True)
    bracket_size = fields.Integer(readonly=True)

    winner_id = fields.Many2one('res.users', string='Champion', readonly=True)
    runner_up_id = fields.Many2one('res.users', string='Runner-up', readonly=True)

    @api.depends('registration_ids')
    def _compute_participant_count(self):
        for tournament in self:
            tournament.participant_count = len(tournament.registration_ids)

    # ------------------------------------------------------------------
    # Registration & seeding
    # ------------------------------------------------------------------
    def action_register(self, user_id=None):
        self.ensure_one()
        user_id = user_id or self.env.uid
        if self.state != 'registration':
            raise UserError("Registrations for this tournament are closed.")
        if user_id in self.registration_ids.user_id.ids:
            raise UserError("You are already registered.")
        if self.max_participants and len(self.registration_ids) >= self.max_participants:
            raise UserError("This tournament is full.")
        profile = self.env['speedrun.profile'].sudo()._get_or_create(
            self.env['res.users'].browse(user_id))
        reg = self.env['speedrun.tournament.registration'].create({
            'tournament_id': self.id,
            'user_id': user_id,
            'elo': profile.elo,
            'seed': len(self.registration_ids) + 1,
        })
        self._notify_update()
        return reg

    def action_unregister(self, user_id=None):
        self.ensure_one()
        user_id = user_id or self.env.uid
        if self.state not in ('registration', 'seeding'):
            raise UserError("You cannot leave a running tournament.")
        reg = self.registration_ids.filtered(lambda r: r.user_id.id == user_id)
        reg.unlink()
        self._resequence_seeds()
        self._notify_update()
        return True

    def _resequence_seeds(self):
        for idx, reg in enumerate(self.registration_ids.sorted('seed'), start=1):
            reg.seed = idx

    def action_close_registration(self):
        self.ensure_one()
        self._check_organizer()
        if self.state != 'registration':
            raise UserError("Registration is not open.")
        if len(self.registration_ids) < 2:
            raise UserError("At least 2 participants are required.")
        self.action_auto_seed(self.seeding_method)
        self.state = 'seeding'
        self._notify_update()
        return True

    def action_reopen_registration(self):
        self.ensure_one()
        self._check_organizer()
        if self.state != 'seeding':
            raise UserError("Cannot reopen registration now.")
        self.state = 'registration'
        self._notify_update()
        return True

    def action_auto_seed(self, method=None):
        self.ensure_one()
        self._check_organizer()
        method = method or self.seeding_method
        regs = self.registration_ids
        if method == 'elo':
            ordered = regs.sorted(lambda r: (-r.elo, r.id))
        elif method == 'random':
            ordered = regs.sorted(lambda r: r.id)
            ordered = self.env['speedrun.tournament.registration'].browse(
                random.sample(ordered.ids, len(ordered.ids)))
        else:
            ordered = regs.sorted(lambda r: (r.seed or 9999, r.id))
        for idx, reg in enumerate(ordered, start=1):
            reg.seed = idx
        self.seeding_method = method
        self._notify_update()
        return True

    def action_set_seeds(self, ordered_user_ids):
        """Manually set the seeding from an ordered list of user ids."""
        self.ensure_one()
        self._check_organizer()
        if self.state not in ('registration', 'seeding'):
            raise UserError("Seeding can no longer be changed.")
        reg_by_user = {r.user_id.id: r for r in self.registration_ids}
        seed = 1
        for uid in ordered_user_ids:
            reg = reg_by_user.get(uid)
            if reg:
                reg.seed = seed
                seed += 1
        # Any registration not in the list keeps ordering at the end
        for reg in self.registration_ids.sorted('seed'):
            if reg.user_id.id not in ordered_user_ids:
                reg.seed = seed
                seed += 1
        self.seeding_method = 'manual'
        self._notify_update()
        return True

    def action_move_seed(self, user_id, direction):
        """Move a participant up/down by one seed position."""
        self.ensure_one()
        self._check_organizer()
        regs = list(self.registration_ids.sorted('seed'))
        idx = next((i for i, r in enumerate(regs) if r.user_id.id == user_id), None)
        if idx is None:
            return False
        swap = idx - 1 if direction == 'up' else idx + 1
        if swap < 0 or swap >= len(regs):
            return False
        regs[idx].seed, regs[swap].seed = regs[swap].seed, regs[idx].seed
        self.seeding_method = 'manual'
        self._notify_update()
        return True

    # ------------------------------------------------------------------
    # Bracket generation (double elimination)
    # ------------------------------------------------------------------
    def action_generate_bracket(self):
        self.ensure_one()
        self._check_organizer()
        if self.state not in ('registration', 'seeding'):
            raise UserError("Bracket already generated.")
        participants = self.registration_ids.sorted('seed')
        if len(participants) < 2:
            raise UserError("At least 2 participants are required.")

        # Clean seeds 1..P
        for idx, reg in enumerate(participants, start=1):
            reg.seed = idx
        part_by_seed = {reg.seed: reg for reg in participants}

        size = max(4, _next_pow2(len(participants)))
        self.match_ids.unlink()
        recmap = self._build_matches(size)
        self.write({'bracket_size': size, 'state': 'running'})
        participants.write({'state': 'active'})

        # Feed round-1 winners bracket according to the seed order.
        order = _seed_order(size)
        for i in range(size // 2):
            match = recmap[('W', 1, i)]
            s1, s2 = order[2 * i], order[2 * i + 1]
            reg1 = part_by_seed.get(s1)
            reg2 = part_by_seed.get(s2)
            match._fill_slot(1, reg1, is_bye=not reg1)
            match._fill_slot(2, reg2, is_bye=not reg2)

        self._notify_update()
        return True

    def _build_matches(self, size):
        """Create every match of the double-elimination bracket and wire up
        the winner/loser routing. Returns a dict keyed by (bracket, round, idx).
        """
        Match = self.env['speedrun.tournament.match']
        w = size.bit_length() - 1          # number of winners-bracket rounds
        lb_rounds = 2 * (w - 1)            # number of losers-bracket rounds

        # --- pass 1: create bare records ---
        keys = []
        vals_list = []
        for r in range(1, w + 1):
            for i in range(size >> r):
                keys.append(('W', r, i))
                vals_list.append({
                    'tournament_id': self.id, 'bracket': 'winner',
                    'round_number': r, 'match_number': i,
                    'label': self._wb_label(r, w, i),
                })
        for rnd in range(1, lb_rounds + 1):
            k = (rnd + 1) // 2
            for i in range(size >> (k + 1)):
                keys.append(('L', rnd, i))
                vals_list.append({
                    'tournament_id': self.id, 'bracket': 'loser',
                    'round_number': rnd, 'match_number': i,
                    'label': 'Losers Round %s' % rnd + (' Match %s' % (i + 1) if (size >> (k + 1)) > 1 else ''),
                })
        keys.append(('G', 1, 0))
        vals_list.append({'tournament_id': self.id, 'bracket': 'grand',
                          'round_number': 1, 'match_number': 0, 'label': 'Grand Final'})
        keys.append(('G', 2, 0))
        vals_list.append({'tournament_id': self.id, 'bracket': 'grand',
                          'round_number': 2, 'match_number': 0, 'is_reset': True,
                          'label': 'Grand Final (Reset)'})

        records = Match.create(vals_list)
        recmap = dict(zip(keys, records))

        # --- pass 2: routing ---
        for r in range(1, w + 1):
            for i in range(size >> r):
                rec = recmap[('W', r, i)]
                vals = {}
                if r < w:
                    vals['next_win_match_id'] = recmap[('W', r + 1, i // 2)].id
                    vals['next_win_slot'] = 1 if i % 2 == 0 else 2
                else:
                    vals['next_win_match_id'] = recmap[('G', 1, 0)].id
                    vals['next_win_slot'] = 1
                if r == 1:
                    vals['next_lose_match_id'] = recmap[('L', 1, i // 2)].id
                    vals['next_lose_slot'] = 1 if i % 2 == 0 else 2
                else:
                    lb_round = 2 * (r - 1)
                    cnt_lb = size >> r
                    target = cnt_lb - 1 - i        # reversed to reduce rematches
                    vals['next_lose_match_id'] = recmap[('L', lb_round, target)].id
                    vals['next_lose_slot'] = 2     # WB drop-down occupies slot 2
                rec.write(vals)

        for rnd in range(1, lb_rounds + 1):
            k = (rnd + 1) // 2
            for i in range(size >> (k + 1)):
                rec = recmap[('L', rnd, i)]
                if rnd == lb_rounds:
                    rec.write({'next_win_match_id': recmap[('G', 1, 0)].id, 'next_win_slot': 2})
                elif rnd % 2 == 1:
                    # minor round -> next major round, same count, LB slot 1
                    rec.write({'next_win_match_id': recmap[('L', rnd + 1, i)].id, 'next_win_slot': 1})
                else:
                    # major round -> next minor round, count halves
                    rec.write({'next_win_match_id': recmap[('L', rnd + 1, i // 2)].id,
                               'next_win_slot': 1 if i % 2 == 0 else 2})
        return recmap

    @staticmethod
    def _wb_label(r, w, i):
        if r == w:
            return 'Winners Final'
        if r == w - 1:
            return 'Winners Semifinal %s' % (i + 1)
        return 'Winners Round %s Match %s' % (r, i + 1)

    def _set_champion(self, winner_reg, loser_reg):
        self.ensure_one()
        vals = {'state': 'finished'}
        if winner_reg:
            vals['winner_id'] = winner_reg.user_id.id
            winner_reg.state = 'champion'
        if loser_reg:
            vals['runner_up_id'] = loser_reg.user_id.id
            loser_reg.state = 'eliminated'
        self.write(vals)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _check_organizer(self):
        if self.env.uid != self.organizer_id.id and not self.env.user.has_group('base.group_system'):
            raise AccessError("Only the organizer can manage this tournament.")

    def action_cancel(self):
        self.ensure_one()
        self._check_organizer()
        # Only allow deletion pre-start or by admin
        self.match_ids.unlink()
        self.registration_ids.unlink()
        self.unlink()
        return True

    def _notify_update(self):
        """Push a lightweight refresh signal to everyone involved."""
        for record in self:
            users = record.registration_ids.user_id | record.organizer_id
            payload = {'tournament_id': record.id}
            for user in users:
                user._bus_send('speedrun/tournament_update', payload)

    # ------------------------------------------------------------------
    # Frontend payloads
    # ------------------------------------------------------------------
    @api.model
    def _get_list(self):
        tournaments = self.search([('state', '!=', 'finished')]) \
            | self.search([('state', '=', 'finished')], limit=10)
        uid = self.env.uid
        result = []
        for t in tournaments:
            result.append({
                'id': t.id,
                'name': t.name,
                'state': t.state,
                'match_best_of': t.match_best_of,
                'participant_count': t.participant_count,
                'max_participants': t.max_participants,
                'is_registered': uid in t.registration_ids.user_id.ids,
                'is_organizer': uid == t.organizer_id.id,
                'organizer_name': t.organizer_id.name,
                'winner_name': t.winner_id.name if t.winner_id else None,
            })
        return result

    def _get_data(self, user_id=None):
        self.ensure_one()
        uid = user_id or self.env.uid
        regs = self.registration_ids.sorted('seed')
        return {
            'id': self.id,
            'name': self.name,
            'state': self.state,
            'match_best_of': self.match_best_of,
            'seeding_method': self.seeding_method,
            'organizer_id': self.organizer_id.id,
            'organizer_name': self.organizer_id.name,
            'is_organizer': uid == self.organizer_id.id,
            'participant_count': self.participant_count,
            'max_participants': self.max_participants,
            'bracket_size': self.bracket_size,
            'is_registered': uid in regs.user_id.ids,
            'winner_id': self.winner_id.id if self.winner_id else None,
            'winner_name': self.winner_id.name if self.winner_id else None,
            'runner_up_name': self.runner_up_id.name if self.runner_up_id else None,
            'registrations': [{
                'user_id': r.user_id.id,
                'user_name': r.user_id.name,
                'seed': r.seed,
                'elo': r.elo,
                'state': r.state,
                'is_me': r.user_id.id == uid,
            } for r in regs],
            'bracket': self._bracket_payload(uid) if self.state in ('running', 'finished') else None,
        }

    def _bracket_payload(self, uid):
        self.ensure_one()

        def slot(match, n):
            reg = match.player1_id if n == 1 else match.player2_id
            filled = match.p1_filled if n == 1 else match.p2_filled
            bye = match.p1_bye if n == 1 else match.p2_bye
            score = 0
            if match.game_id and reg:
                player = match.game_id.player_ids.filtered(lambda p: p.user_id.id == reg.user_id.id)
                score = player.round_wins if player else 0
            return {
                'user_id': reg.user_id.id if reg else None,
                'name': reg.user_id.name if reg else ('BYE' if bye else None),
                'bye': bye,
                'filled': filled,
                'score': score,
                'is_me': bool(reg) and reg.user_id.id == uid,
                'is_winner': bool(match.winner_id) and reg and match.winner_id.id == reg.id,
            }

        def match_dict(m):
            can_play = (m.state == 'ready'
                        and uid in (m.player1_id.user_id.id, m.player2_id.user_id.id))
            return {
                'id': m.id,
                'label': m.label,
                'state': m.state,
                'bracket': m.bracket,
                'round_number': m.round_number,
                'match_number': m.match_number,
                'is_reset': m.is_reset,
                'game_id': m.game_id.id if m.game_id else None,
                'can_play': can_play,
                'my_match': uid in (m.player1_id.user_id.id, m.player2_id.user_id.id),
                'p1': slot(m, 1),
                'p2': slot(m, 2),
            }

        def group(matches):
            rounds = {}
            for m in matches:
                rounds.setdefault(m.round_number, []).append(m)
            out = []
            for rnd in sorted(rounds):
                ms = sorted(rounds[rnd], key=lambda m: m.match_number)
                out.append({
                    'round_number': rnd,
                    'label': ms[0].label.split(' Match')[0] if ms else '',
                    'matches': [match_dict(m) for m in ms],
                })
            return out

        winners = self.match_ids.filtered(lambda m: m.bracket == 'winner')
        losers = self.match_ids.filtered(lambda m: m.bracket == 'loser')
        # Grand final: hide the reset match unless it is actually in play
        grand = self.match_ids.filtered(lambda m: m.bracket == 'grand').sorted('round_number')
        grand = grand.filtered(lambda m: not m.is_reset or m.p1_filled)
        return {
            'winners': group(winners),
            'losers': group(losers),
            'grand': [match_dict(m) for m in grand],
        }


class SpeedrunTournamentRegistration(models.Model):
    _name = 'speedrun.tournament.registration'
    _description = 'Speedrun Tournament Registration'
    _order = 'tournament_id, seed'
    _rec_name = 'user_id'

    tournament_id = fields.Many2one('speedrun.tournament', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', required=True, index=True)
    seed = fields.Integer(default=0)
    elo = fields.Integer(help="ELO snapshot at registration time.")
    state = fields.Selection([
        ('registered', 'Registered'),
        ('active', 'Active'),
        ('eliminated', 'Eliminated'),
        ('champion', 'Champion'),
    ], default='registered', required=True)

    _unique_reg = models.Constraint(
        'UNIQUE(tournament_id, user_id)',
        'A user can only register once per tournament.',
    )


class SpeedrunTournamentMatch(models.Model):
    _name = 'speedrun.tournament.match'
    _description = 'Speedrun Tournament Match'
    _order = 'tournament_id, bracket desc, round_number, match_number'

    tournament_id = fields.Many2one('speedrun.tournament', required=True, ondelete='cascade', index=True)
    bracket = fields.Selection([
        ('winner', 'Winners Bracket'),
        ('loser', 'Losers Bracket'),
        ('grand', 'Grand Final'),
    ], required=True)
    round_number = fields.Integer(required=True)
    match_number = fields.Integer(default=0)
    label = fields.Char()
    is_reset = fields.Boolean(default=False)

    player1_id = fields.Many2one('speedrun.tournament.registration', ondelete='set null')
    player2_id = fields.Many2one('speedrun.tournament.registration', ondelete='set null')
    p1_filled = fields.Boolean(default=False)
    p2_filled = fields.Boolean(default=False)
    p1_bye = fields.Boolean(default=False)
    p2_bye = fields.Boolean(default=False)

    winner_id = fields.Many2one('speedrun.tournament.registration', ondelete='set null')
    loser_id = fields.Many2one('speedrun.tournament.registration', ondelete='set null')
    game_id = fields.Many2one('speedrun.game', ondelete='set null')

    state = fields.Selection([
        ('waiting', 'Waiting for players'),
        ('ready', 'Ready to play'),
        ('running', 'In progress'),
        ('done', 'Finished'),
        ('bye', 'Bye'),
    ], default='waiting', required=True)

    next_win_match_id = fields.Many2one('speedrun.tournament.match', ondelete='set null')
    next_win_slot = fields.Integer()
    next_lose_match_id = fields.Many2one('speedrun.tournament.match', ondelete='set null')
    next_lose_slot = fields.Integer()

    # ------------------------------------------------------------------
    # Slot feeding & progression
    # ------------------------------------------------------------------
    def _fill_slot(self, slot, reg, is_bye=False):
        self.ensure_one()
        if slot == 1:
            self.write({'player1_id': reg.id if reg else False,
                        'p1_filled': True, 'p1_bye': is_bye})
        else:
            self.write({'player2_id': reg.id if reg else False,
                        'p2_filled': True, 'p2_bye': is_bye})
        self._check_ready()

    def _check_ready(self):
        self.ensure_one()
        if not (self.p1_filled and self.p2_filled):
            return
        p1_real = bool(self.player1_id) and not self.p1_bye
        p2_real = bool(self.player2_id) and not self.p2_bye
        if p1_real and p2_real:
            if self.state == 'waiting':
                self.state = 'ready'
        elif p1_real and not p2_real:
            self.state = 'bye'
            self._record_result(self.player1_id, None)
        elif p2_real and not p1_real:
            self.state = 'bye'
            self._record_result(self.player2_id, None)
        else:
            # both byes: propagate an empty slot downstream
            self.state = 'bye'
            self._record_result(None, None)

    def _record_result(self, winner_reg, loser_reg):
        self.ensure_one()
        self.write({
            'winner_id': winner_reg.id if winner_reg else False,
            'loser_id': loser_reg.id if loser_reg else False,
            'state': self.state if self.state == 'bye' else 'done',
        })

        if self.bracket == 'grand':
            reset = self.tournament_id.match_ids.filtered(
                lambda m: m.bracket == 'grand' and m.is_reset)
            if not self.is_reset and winner_reg and winner_reg == self.player2_id and reset:
                # Losers-bracket champion forced a bracket reset.
                reset._fill_slot(1, self.player1_id)
                reset._fill_slot(2, self.player2_id)
            else:
                self.tournament_id._set_champion(winner_reg, loser_reg)
            return

        if self.next_win_match_id:
            self.next_win_match_id._fill_slot(
                self.next_win_slot, winner_reg, is_bye=not winner_reg)
        if self.next_lose_match_id:
            self.next_lose_match_id._fill_slot(
                self.next_lose_slot, loser_reg, is_bye=not loser_reg)
        elif loser_reg:
            loser_reg.state = 'eliminated'

    # ------------------------------------------------------------------
    # Playing a match
    # ------------------------------------------------------------------
    def action_play(self, user_id=None):
        """Create and auto-start the 1v1 best-of game for this match."""
        self.ensure_one()
        user_id = user_id or self.env.uid
        tournament = self.tournament_id
        if self.state == 'running' and self.game_id:
            return self.game_id.sudo()._get_game_info()
        if self.state != 'ready':
            raise UserError("This match is not ready to be played.")
        players = (self.player1_id.user_id.id, self.player2_id.user_id.id)
        if user_id not in players and user_id != tournament.organizer_id.id:
            raise AccessError("Only the two players can start this match.")

        game = self.env['speedrun.game'].sudo().with_context(
            default_host_id=self.player1_id.user_id.id).create({
                'name': '%s — %s' % (tournament.name, self.label),
                'host_id': self.player1_id.user_id.id,
                'game_mode': 'best_of',
                'total_rounds': int(tournament.match_best_of),
                'max_players': 2,
                'is_ranked': True,
                'tournament_match_id': self.id,
            })
        game.action_join(user_id=self.player2_id.user_id.id)
        self.write({'game_id': game.id, 'state': 'running'})

        game_info = game._get_game_info()
        for uid in players:
            self.env['res.users'].browse(uid)._bus_send('speedrun/match_found', {
                'game_info': game_info,
            })
        game._start_round()
        tournament._notify_update()
        return game_info

    def _on_game_over(self):
        """Called by speedrun.game when the underlying best-of game ends."""
        self.ensure_one()
        game = self.game_id
        if not game or not game.winner_id:
            return
        winner_user = game.winner_id.id
        if self.player1_id.user_id.id == winner_user:
            self._record_result(self.player1_id, self.player2_id)
        else:
            self._record_result(self.player2_id, self.player1_id)
        self.tournament_id._notify_update()
