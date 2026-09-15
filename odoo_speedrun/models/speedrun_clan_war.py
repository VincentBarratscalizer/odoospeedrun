import json
import random

from odoo import api, fields, models
from odoo.exceptions import UserError

# War tuning
WAR_DURATION_HOURS = 24
ACCEPT_DEADLINE_HOURS = 12
CLAN_K_FACTOR = 24

# Blitz: a fixed daily hour window (server/UTC time) during which every normal
# game task completion by a clan's members counts toward the blitz épreuve.
DEFAULT_BLITZ_HOUR = 18
DEFAULT_BLITZ_DURATION_MIN = 60
# The Blitz épreuve is only surfaced in the last hour of the war.
BLITZ_VISIBLE_BEFORE_END_HOURS = 1

# Rewards
TREASURY_WIN = 1000
TREASURY_LOSS = 150
CLAN_XP_WIN = 300
CLAN_XP_LOSS = 100
TROPHY_WIN = 30
TROPHY_STREAK_BONUS = 5      # extra trophies per consecutive win
TROPHY_LOSS = 10
MEMBER_COINS_WIN = 150
MEMBER_COINS_LOSS = 40
MEMBER_CHEST_WIN = 'rare'

# The three "épreuves" (best-of-3). The blitz only decides when raid & arena split.
EPREUVE_LABELS = {
    'raid': '🛠️ Raid',
    'arena': '🥊 Arène',
    'blitz': '⚡ Blitz',
}


class SpeedrunClanWar(models.Model):
    _name = 'speedrun.clan.war'
    _description = 'Speedrun Clan War'
    _order = 'create_date desc, id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name', store=True)
    challenger_clan_id = fields.Many2one(
        'speedrun.clan', required=True, ondelete='cascade', index=True, string='Challenger Clan')
    defender_clan_id = fields.Many2one(
        'speedrun.clan', required=True, ondelete='cascade', index=True, string='Defender Clan')
    declared_by = fields.Many2one('res.users', string='Declared By')

    state = fields.Selection([
        ('declared', 'Declared'),
        ('running', 'Running'),
        ('finished', 'Finished'),
        ('declined', 'Declined'),
        ('cancelled', 'Cancelled'),
    ], default='declared', required=True, index=True)

    declared_at = fields.Datetime(default=fields.Datetime.now)
    accept_deadline = fields.Datetime()
    start_at = fields.Datetime()
    end_at = fields.Datetime(index=True)
    blitz_at = fields.Datetime(string='Blitz Start')
    blitz_end = fields.Datetime(string='Blitz End')

    raid_task_id = fields.Many2one('speedrun.task', ondelete='set null')
    blitz_task_id = fields.Many2one('speedrun.task', ondelete='set null')

    duel_ids = fields.One2many('speedrun.clan.war.duel', 'war_id')
    result_ids = fields.One2many('speedrun.clan.war.result', 'war_id')

    # Outcome
    raid_winner_id = fields.Many2one('speedrun.clan', ondelete='set null')
    arena_winner_id = fields.Many2one('speedrun.clan', ondelete='set null')
    blitz_winner_id = fields.Many2one('speedrun.clan', ondelete='set null')
    blitz_decisive = fields.Boolean(default=False)
    winner_clan_id = fields.Many2one('speedrun.clan', ondelete='set null', index=True)
    score_challenger = fields.Integer(default=0)
    score_defender = fields.Integer(default=0)
    challenger_arena_wins = fields.Integer(default=0)
    defender_arena_wins = fields.Integer(default=0)
    rating_change_challenger = fields.Integer(default=0)
    rating_change_defender = fields.Integer(default=0)

    @api.depends('challenger_clan_id.tag', 'defender_clan_id.tag')
    def _compute_display_name(self):
        for war in self:
            war.display_name = "[%s] ⚔ [%s]" % (
                war.challenger_clan_id.tag or '?', war.defender_clan_id.tag or '?')

    # ------------------------------------------------------------------
    # Declaration / acceptance
    # ------------------------------------------------------------------
    @api.model
    def _declare(self, defender_clan_id):
        """Current user's clan (as leader) declares war on another clan."""
        user = self.env.user
        my_clan = self.env['speedrun.clan'].sudo()._my_clan(user)
        if not my_clan:
            raise UserError("Vous n'appartenez à aucun clan.")
        if not my_clan._is_leader(user):
            raise UserError("Seul le chef de clan peut déclarer une guerre.")
        defender = self.env['speedrun.clan'].sudo().browse(int(defender_clan_id)).exists()
        if not defender:
            raise UserError("Clan cible introuvable.")
        if defender.id == my_clan.id:
            raise UserError("Vous ne pouvez pas déclarer la guerre à votre propre clan.")
        if my_clan._has_active_war():
            raise UserError("Votre clan est déjà engagé dans une guerre.")
        if defender._has_active_war():
            raise UserError("Le clan adverse est déjà engagé dans une guerre.")
        if not my_clan.member_count or not defender.member_count:
            raise UserError("Les deux clans doivent avoir au moins un membre.")
        war = self.sudo().create({
            'challenger_clan_id': my_clan.id,
            'defender_clan_id': defender.id,
            'declared_by': user.id,
            'accept_deadline': fields.Datetime.add(
                fields.Datetime.now(), hours=ACCEPT_DEADLINE_HOURS),
        })
        defender.leader_id._bus_send('speedrun/clan_update', {
            'event': 'war_declared',
            'war_id': war.id,
            'challenger_name': my_clan.name,
            'challenger_tag': my_clan.tag,
        })
        return war

    def _accept(self):
        """Defender leader accepts: the war starts for WAR_DURATION_HOURS."""
        self.ensure_one()
        user = self.env.user
        if self.state != 'declared':
            raise UserError("Cette guerre ne peut plus être acceptée.")
        if not self.defender_clan_id._is_leader(user):
            raise UserError("Seul le chef du clan défenseur peut accepter la guerre.")
        raid = self._pick_raid_task()
        now = fields.Datetime.now()
        end = fields.Datetime.add(now, hours=WAR_DURATION_HOURS)
        blitz_at, blitz_end = self._compute_blitz_window(now, end)
        self.sudo().write({
            'state': 'running',
            'start_at': now,
            'end_at': end,
            'blitz_at': blitz_at,
            'blitz_end': blitz_end,
            'raid_task_id': raid.id if raid else False,
        })
        self._notify_all('war_started', {'war_id': self.id})
        return self

    def _decline(self):
        """Defender leader declines the war."""
        self.ensure_one()
        user = self.env.user
        if self.state != 'declared':
            raise UserError("Cette guerre ne peut plus être refusée.")
        if not self.defender_clan_id._is_leader(user):
            raise UserError("Seul le chef du clan défenseur peut refuser la guerre.")
        self.sudo().state = 'declined'
        self.challenger_clan_id.leader_id._bus_send('speedrun/clan_update', {
            'event': 'war_declined', 'war_id': self.id,
            'defender_name': self.defender_clan_id.name,
        })
        return self

    def _cancel(self):
        """Challenger leader cancels a not-yet-accepted declaration."""
        self.ensure_one()
        user = self.env.user
        if self.state != 'declared':
            raise UserError("Cette guerre ne peut plus être annulée.")
        if not self.challenger_clan_id._is_leader(user):
            raise UserError("Seul le chef du clan attaquant peut annuler la déclaration.")
        self.sudo().state = 'cancelled'
        return self

    def _pick_raid_task(self):
        """Pick a raid (medium/hard) task among the available ones."""
        available = self.env['speedrun.task'].sudo()._get_available_tasks()
        if not available:
            return self.env['speedrun.task']
        hard = available.filtered(lambda t: t.difficulty in ('medium', 'hard'))
        return self.env['speedrun.task'].browse(random.choice((hard or available).ids))

    @api.model
    def _blitz_config(self):
        ICP = self.env['ir.config_parameter'].sudo()

        def _int(key, default):
            try:
                return int(ICP.get_param(key, default))
            except (TypeError, ValueError):
                return default
        hour = min(23, max(0, _int('odoo_speedrun.blitz_hour', DEFAULT_BLITZ_HOUR)))
        duration = max(5, _int('odoo_speedrun.blitz_duration_minutes', DEFAULT_BLITZ_DURATION_MIN))
        return hour, duration

    def _compute_blitz_window(self, start, end):
        """The first HH:00 blitz hour that falls within [start, end]."""
        hour, duration = self._blitz_config()
        cand = start.replace(hour=hour, minute=0, second=0, microsecond=0)
        if cand < start:
            cand = fields.Datetime.add(cand, days=1)
        if cand > end:
            cand = start
        return cand, fields.Datetime.add(cand, minutes=duration)

    # ------------------------------------------------------------------
    # Raid / Blitz participation (task épreuves)
    # ------------------------------------------------------------------
    def _side_of(self, user):
        """Return 'challenger' / 'defender' / None for a user in this war."""
        self.ensure_one()
        clan = self.env['speedrun.clan'].sudo()._my_clan(user)
        if clan.id == self.challenger_clan_id.id:
            return 'challenger'
        if clan.id == self.defender_clan_id.id:
            return 'defender'
        return None

    def _task_for(self, kind):
        return self.raid_task_id if kind == 'raid' else self.blitz_task_id

    def _my_result(self, user, kind):
        self.ensure_one()
        return self.sudo().result_ids.filtered(
            lambda r: r.user_id.id == user.id and r.kind == kind)

    def _task_start(self, kind):
        """Record the start of a raid/blitz task for the current user."""
        self.ensure_one()
        user = self.env.user
        if self.state != 'running':
            return {'error': "La guerre n'est pas en cours."}
        side = self._side_of(user)
        if not side:
            return {'error': "Vous ne participez pas à cette guerre."}
        if not self._task_for(kind):
            return {'error': "Aucune tâche disponible pour cette épreuve."}
        my = self._my_result(user, kind)
        if my and my.completed:
            return self._info(user)
        if not my:
            clan = self.challenger_clan_id if side == 'challenger' else self.defender_clan_id
            self.sudo().env['speedrun.clan.war.result'].create({
                'war_id': self.id,
                'user_id': user.id,
                'clan_id': clan.id,
                'kind': kind,
                'start_time': fields.Datetime.now(),
            })
        return self._info(user)

    def _raid_systray_payload(self, user):
        """Compact payload for the systray to resume an in-progress raid."""
        self.ensure_one()
        my = self._my_result(user, 'raid')
        if not my or not my.start_time or my.completed or not self.raid_task_id:
            return {}
        return {
            'war_id': self.id,
            'task_name': self.raid_task_id.name,
            'task_description': self.raid_task_id.description or '',
            'start_time': fields.Datetime.to_string(my.start_time),
        }

    def _task_check(self, kind):
        """Verify the current user's raid/blitz task completion."""
        self.ensure_one()
        user = self.env.user
        if self.state != 'running':
            return {'error': "La guerre n'est pas en cours."}
        my = self._my_result(user, kind)
        if not my or not my.start_time:
            return {'error': "Démarrez d'abord l'épreuve !"}
        if my.completed:
            return {'success': True, 'already_completed': True, **self._info(user)}
        task = self._task_for(kind)
        if not task:
            return {'error': "Aucune tâche disponible."}
        if not task._verify_completion(user.id, my.start_time):
            return {'success': False, 'error': "Tâche non terminée. Continuez !"}
        now = fields.Datetime.now()
        my.sudo().write({
            'finish_time': now,
            'duration_ms': int((now - my.start_time).total_seconds() * 1000),
            'completed': True,
        })
        info = self._info(user)
        info['success'] = True
        return info

    # ------------------------------------------------------------------
    # Closing: score the three épreuves & apply rewards
    # ------------------------------------------------------------------
    def _task_metrics(self, kind):
        """Return (a_count, b_count, a_dur, b_dur) for a task épreuve."""
        self.ensure_one()
        done = self.result_ids.filtered(lambda r: r.kind == kind and r.completed)
        a = done.filtered(lambda r: r.clan_id.id == self.challenger_clan_id.id)
        b = done.filtered(lambda r: r.clan_id.id == self.defender_clan_id.id)
        return (len(a), len(b), sum(a.mapped('duration_ms')), sum(b.mapped('duration_ms')))

    def _decide_task(self, kind):
        """Winner clan of a task épreuve: more completions, then faster total."""
        self.ensure_one()
        a_count, b_count, a_dur, b_dur = self._task_metrics(kind)
        if a_count != b_count:
            return self.challenger_clan_id if a_count > b_count else self.defender_clan_id
        if a_count and a_dur != b_dur:
            return self.challenger_clan_id if a_dur < b_dur else self.defender_clan_id
        return self._tiebreak()

    # ------------------------------------------------------------------
    # Arena — player-triggered duels (with the battle visual)
    # ------------------------------------------------------------------
    def _arena_opponent(self, my_profile, side):
        """Return the gear-score-seeded rival for a member in the enemy clan."""
        self.ensure_one()
        my_clan = self.challenger_clan_id if side == 'challenger' else self.defender_clan_id
        enemy = self.defender_clan_id if side == 'challenger' else self.challenger_clan_id
        mine = my_clan.member_profile_ids.sorted(lambda p: (p.gear_score, p.power), reverse=True)
        foes = enemy.member_profile_ids.sorted(lambda p: (p.gear_score, p.power), reverse=True)
        if not foes:
            return self.env['speedrun.profile']
        try:
            rank = list(mine.ids).index(my_profile.id)
        except ValueError:
            rank = 0
        return foes[min(rank, len(foes) - 1)]

    def _my_duel(self, user):
        self.ensure_one()
        profile = self.env['speedrun.clan'].sudo()._profile_for(user)
        return self.duel_ids.filtered(lambda d: d.challenger_profile_id.id == profile.id)

    def _arena_tally(self):
        """(challenger_wins, defender_wins) from triggered member attacks."""
        self.ensure_one()
        a = len(self.duel_ids.filtered(
            lambda d: d.attacker_clan_id.id == self.challenger_clan_id.id and d.attacker_won))
        b = len(self.duel_ids.filtered(
            lambda d: d.attacker_clan_id.id == self.defender_clan_id.id and d.attacker_won))
        return a, b

    def _arena_stats(self):
        """Per-clan arena {wins, losses} from members' triggered attacks."""
        self.ensure_one()

        def stat(clan):
            played = self.duel_ids.filtered(lambda d: d.attacker_clan_id.id == clan.id)
            wins = len(played.filtered('attacker_won'))
            return {'w': wins, 'l': len(played) - wins}
        return stat(self.challenger_clan_id), stat(self.defender_clan_id)

    def _standings(self, raid_a, raid_b, arena_a, arena_b, blitz_a, blitz_b, blitz_decisive_visible):
        """Provisional 'who is winning' summary during a running war."""
        self.ensure_one()

        def lead(a, b):
            return 'challenger' if a > b else ('defender' if b > a else 'tie')
        raid_lead = lead(raid_a, raid_b)
        arena_lead = lead(arena_a, arena_b)
        pc = pd = 0
        for ld in (raid_lead, arena_lead):
            if ld == 'challenger':
                pc += 1
            elif ld == 'defender':
                pd += 1
        # The blitz only breaks a 1-1 split between raid and arena.
        split = (raid_lead in ('challenger', 'defender')
                 and arena_lead in ('challenger', 'defender')
                 and raid_lead != arena_lead)
        blitz_lead = lead(blitz_a, blitz_b)
        if split and blitz_decisive_visible and blitz_lead != 'tie':
            if blitz_lead == 'challenger':
                pc += 1
            else:
                pd += 1
        overall = lead(pc, pd)
        return {
            'raid_lead': raid_lead,
            'arena_lead': arena_lead,
            'blitz_lead': blitz_lead,
            'challenger_points': pc,
            'defender_points': pd,
            'leader': overall,
            'blitz_is_decider': split,
        }

    def _arena_fight(self):
        """Current user triggers their single arena attack; returns a replay."""
        self.ensure_one()
        user = self.env.user
        if self.state != 'running':
            return {'error': "La guerre n'est pas en cours."}
        side = self._side_of(user)
        if not side:
            return {'error': "Vous ne participez pas à cette guerre."}
        if self._my_duel(user):
            return {'error': "Vous avez déjà mené votre attaque d'arène."}
        my_profile = self.env['speedrun.clan'].sudo()._profile_for(user)
        my_clan = self.challenger_clan_id if side == 'challenger' else self.defender_clan_id
        opponent = self._arena_opponent(my_profile, side)
        if not opponent:
            return {'error': "Aucun adversaire disponible dans le clan ennemi."}
        replay = self.env['speedrun.battle'].sudo()._simulate(my_profile, opponent)
        attacker_won = replay['winner'] == 'challenger'
        self.sudo().env['speedrun.clan.war.duel'].create({
            'war_id': self.id,
            'challenger_profile_id': my_profile.id,
            'opponent_profile_id': opponent.id,
            'attacker_clan_id': my_clan.id,
            'attacker_won': attacker_won,
            'winner_side': 'challenger' if attacker_won else 'defender',
            'winner_profile_id': (my_profile if attacker_won else opponent).id,
            'log': json.dumps(replay),
        })
        replay['clan_war'] = {'attacker_won': attacker_won}
        return replay

    def _decide_arena(self):
        """Winner clan = most member-attack wins (players who showed up)."""
        self.ensure_one()
        a_wins, b_wins = self._arena_tally()
        self.challenger_arena_wins = a_wins
        self.defender_arena_wins = b_wins
        if a_wins != b_wins:
            return self.challenger_clan_id if a_wins > b_wins else self.defender_clan_id
        return self._tiebreak()

    # ------------------------------------------------------------------
    # Blitz — fixed daily hour, sum of normal-game completions
    # ------------------------------------------------------------------
    def _blitz_metrics(self, now=None):
        """(challenger_total, defender_total) task completions in the blitz window."""
        self.ensure_one()
        if not self.blitz_at:
            return 0, 0
        now = now or fields.Datetime.now()
        hi = min(self.blitz_end, now) if self.blitz_end else now
        if hi <= self.blitz_at:
            return 0, 0
        RR = self.env['speedrun.round.result'].sudo()

        def count(clan):
            uids = clan.member_profile_ids.user_id.ids
            if not uids:
                return 0
            return RR.search_count([
                ('user_id', 'in', uids),
                ('rank', '>', 0),
                ('create_date', '>=', self.blitz_at),
                ('create_date', '<=', hi),
            ])
        return count(self.challenger_clan_id), count(self.defender_clan_id)

    def _decide_blitz(self):
        """Winner clan = highest total normal-game completions during the blitz."""
        self.ensure_one()
        a, b = self._blitz_metrics()
        if a != b:
            return self.challenger_clan_id if a > b else self.defender_clan_id
        return self._tiebreak()

    def _tiebreak(self):
        """Deterministic fallback winner: higher clan ELO, else the challenger."""
        self.ensure_one()
        if self.challenger_clan_id.clan_elo >= self.defender_clan_id.clan_elo:
            return self.challenger_clan_id
        return self.defender_clan_id

    def _close(self):
        """Close a running war: score the épreuves, decide, reward, notify."""
        for war in self:
            if war.state != 'running':
                continue
            raid_w = war._decide_task('raid')
            arena_w = war._decide_arena()
            blitz_w = war._decide_blitz()
            war.raid_winner_id = raid_w.id
            war.arena_winner_id = arena_w.id
            war.blitz_winner_id = blitz_w.id

            if raid_w.id == arena_w.id:
                winner = raid_w
                war.blitz_decisive = False
            else:
                winner = blitz_w
                war.blitz_decisive = True
            loser = war.defender_clan_id if winner.id == war.challenger_clan_id.id else war.challenger_clan_id
            war.winner_clan_id = winner.id

            challenger_won = winner.id == war.challenger_clan_id.id
            # Score in "épreuves won"
            if war.blitz_decisive:
                win_score, lose_score = 2, 1
            else:
                win_score, lose_score = 2, 0
            war.score_challenger = win_score if challenger_won else lose_score
            war.score_defender = lose_score if challenger_won else win_score

            war._apply_rewards(winner, loser, challenger_won)
            war.state = 'finished'
            war._notify_all('war_finished', {
                'war_id': war.id,
                'winner_clan_id': winner.id,
                'winner_name': winner.name,
            })

    def _apply_rewards(self, winner, loser, challenger_won):
        self.ensure_one()
        # --- Clan ELO (symmetric ELO update) ---
        ca, cd = self.challenger_clan_id, self.defender_clan_id
        ec = 1.0 / (1.0 + 10 ** ((cd.clan_elo - ca.clan_elo) / 400.0))
        sc = 1.0 if challenger_won else 0.0
        change_c = round(CLAN_K_FACTOR * (sc - ec))
        change_d = round(CLAN_K_FACTOR * ((1.0 - sc) - (1.0 - ec)))
        self.rating_change_challenger = change_c
        self.rating_change_defender = change_d
        ca.sudo().write({
            'clan_elo': ca.clan_elo + change_c,
            'clan_peak_elo': max(ca.clan_peak_elo, ca.clan_elo + change_c),
        })
        cd.sudo().write({
            'clan_elo': cd.clan_elo + change_d,
            'clan_peak_elo': max(cd.clan_peak_elo, cd.clan_elo + change_d),
        })

        # --- Win/loss counters, streak, trophies, treasury, xp ---
        streak = winner.war_streak + 1
        winner.sudo().write({
            'wars_played': winner.wars_played + 1,
            'wars_won': winner.wars_won + 1,
            'war_streak': streak,
            'trophies': winner.trophies + TROPHY_WIN + TROPHY_STREAK_BONUS * (streak - 1),
            'treasury': winner.treasury + TREASURY_WIN,
        })
        winner._add_clan_xp(CLAN_XP_WIN)
        loser.sudo().write({
            'wars_played': loser.wars_played + 1,
            'war_streak': 0,
            'trophies': max(0, loser.trophies - TROPHY_LOSS),
            'treasury': loser.treasury + TREASURY_LOSS,
        })
        loser._add_clan_xp(CLAN_XP_LOSS)

        # --- Per-member rewards (configurable victory loot) ---
        loot = self._loot_config()
        for p in winner.member_profile_ids:
            if loot['win_coins']:
                p.sudo()._add_coins(loot['win_coins'])
            for rarity in ('common', 'rare', 'epic', 'legendary'):
                for _ in range(loot['chests'][rarity]):
                    p.sudo()._award_chest(rarity, source='clan_war')
        for p in loser.member_profile_ids:
            if loot['loss_coins']:
                p.sudo()._add_coins(loot['loss_coins'])

    @api.model
    def _loot_config(self):
        """Read the (manager-configurable) clan-war victory loot from config."""
        ICP = self.env['ir.config_parameter'].sudo()

        def _int(key, default):
            try:
                return max(0, int(ICP.get_param(key, default)))
            except (TypeError, ValueError):
                return default
        return {
            'chests': {
                'common': _int('odoo_speedrun.clan_war_loot_common', 0),
                'rare': _int('odoo_speedrun.clan_war_loot_rare', 1),
                'epic': _int('odoo_speedrun.clan_war_loot_epic', 0),
                'legendary': _int('odoo_speedrun.clan_war_loot_legendary', 0),
            },
            'win_coins': _int('odoo_speedrun.clan_war_win_coins', MEMBER_COINS_WIN),
            'loss_coins': _int('odoo_speedrun.clan_war_loss_coins', MEMBER_COINS_LOSS),
        }

    # ------------------------------------------------------------------
    # Cron
    # ------------------------------------------------------------------
    @api.model
    def _cron_process_wars(self):
        """Close wars whose window elapsed; expire stale declarations."""
        now = fields.Datetime.now()
        due = self.sudo().search([('state', '=', 'running'), ('end_at', '<=', now)])
        for war in due:
            try:
                with self.env.cr.savepoint():
                    war._close()
            except Exception:  # noqa: BLE001
                import logging
                logging.getLogger(__name__).exception(
                    "Clan war close failed for war %s", war.id)
        stale = self.sudo().search([
            ('state', '=', 'declared'), ('accept_deadline', '<=', now)])
        stale.write({'state': 'cancelled'})

    # ------------------------------------------------------------------
    # Notifications & payloads
    # ------------------------------------------------------------------
    def _notify_all(self, event, payload):
        self.ensure_one()
        users = self.challenger_clan_id.member_profile_ids.user_id \
            | self.defender_clan_id.member_profile_ids.user_id
        for u in users:
            u._bus_send('speedrun/clan_update', {'event': event, **payload})

    def _task_status(self, user, kind):
        my = self._my_result(user, kind)
        if my and my.completed:
            status = 'completed'
        elif my and my.start_time:
            status = 'in_progress'
        else:
            status = 'not_started'
        return {
            'status': status,
            'start_time': fields.Datetime.to_string(my.start_time) if my and my.start_time else None,
            'duration_ms': my.duration_ms if my else 0,
        }

    def _info(self, user=None):
        """War payload for the frontend (scores hidden until finished)."""
        self.ensure_one()
        user = user or self.env.user
        side = self._side_of(user)
        a, b = self.challenger_clan_id, self.defender_clan_id

        def clan_brief(c):
            return {'id': c.id, 'name': c.name, 'tag': c.tag, 'emblem': c.emblem or '🛡️',
                    'member_count': c.member_count, 'clan_elo': c.clan_elo,
                    'total_power': c.total_power}

        # Live tallies (visible during the war)
        raid_a, raid_b, _da, _db = self._task_metrics('raid')
        arena_a, arena_b = self._arena_tally()
        arena_stat_a, arena_stat_b = self._arena_stats()
        blitz_a, blitz_b = self._blitz_metrics()
        now = fields.Datetime.now()
        blitz_state = 'pending'
        if self.blitz_at and self.blitz_end:
            if now < self.blitz_at:
                blitz_state = 'upcoming'
            elif now <= self.blitz_end:
                blitz_state = 'live'
            else:
                blitz_state = 'ended'
        # The Blitz épreuve is only revealed in the war's final hour.
        blitz_visible = bool(self.end_at) and now >= fields.Datetime.subtract(
            self.end_at, hours=BLITZ_VISIBLE_BEFORE_END_HOURS)

        standings = self._standings(
            raid_a, raid_b, arena_a, arena_b, blitz_a, blitz_b, blitz_visible)

        data = {
            'id': self.id,
            'state': self.state,
            'challenger': clan_brief(a),
            'defender': clan_brief(b),
            'my_side': side,
            'is_challenger_leader': a._is_leader(user),
            'is_defender_leader': b._is_leader(user),
            'declared_by': self.declared_by.name,
            'end_at': fields.Datetime.to_string(self.end_at) if self.end_at else None,
            'accept_deadline': fields.Datetime.to_string(self.accept_deadline) if self.accept_deadline else None,
            'raid_task': {'name': self.raid_task_id.name, 'description': self.raid_task_id.description or ''} if self.raid_task_id else None,
            'blitz_at': fields.Datetime.to_string(self.blitz_at) if self.blitz_at else None,
            'blitz_end': fields.Datetime.to_string(self.blitz_end) if self.blitz_end else None,
            'blitz_state': blitz_state,
            'blitz_visible': blitz_visible,
            'standings': standings,
            'tally': {
                'raid': {'challenger': raid_a, 'defender': raid_b},
                'arena': {
                    'challenger': {'w': arena_stat_a['w'], 'l': arena_stat_a['l']},
                    'defender': {'w': arena_stat_b['w'], 'l': arena_stat_b['l']},
                },
                'blitz': {'challenger': blitz_a, 'defender': blitz_b},
            },
        }
        if self.state == 'running' and side:
            data['my_raid'] = self._task_status(user, 'raid')
            my_duel = self._my_duel(user)
            data['my_arena'] = {
                'done': bool(my_duel),
                'won': bool(my_duel and my_duel.attacker_won),
                'opponent_name': my_duel.opponent_profile_id.user_id.name if my_duel else (
                    self._arena_opponent(
                        self.env['speedrun.clan'].sudo()._profile_for(user), side
                    ).user_id.name or ''),
            }
        if self.state == 'finished':
            data.update({
                'winner_clan_id': self.winner_clan_id.id,
                'winner_name': self.winner_clan_id.name,
                'score_challenger': self.score_challenger,
                'score_defender': self.score_defender,
                'blitz_decisive': self.blitz_decisive,
                'raid_winner_id': self.raid_winner_id.id,
                'arena_winner_id': self.arena_winner_id.id,
                'blitz_winner_id': self.blitz_winner_id.id,
                'challenger_arena_wins': self.challenger_arena_wins,
                'defender_arena_wins': self.defender_arena_wins,
                'rating_change_challenger': self.rating_change_challenger,
                'rating_change_defender': self.rating_change_defender,
                'duels': [{
                    'attacker_name': d.challenger_profile_id.user_id.name,
                    'defender_name': d.opponent_profile_id.user_id.name,
                    'attacker_won': d.attacker_won,
                    'attacker_clan_id': d.attacker_clan_id.id,
                } for d in self.duel_ids],
            })
        return data


class SpeedrunClanWarDuel(models.Model):
    _name = 'speedrun.clan.war.duel'
    _description = 'Speedrun Clan War Duel (arena)'
    _order = 'war_id, seed'

    war_id = fields.Many2one('speedrun.clan.war', required=True, ondelete='cascade', index=True)
    seed = fields.Integer(string='Seed')
    # The attacker is the player who triggered the fight; the defender is their
    # gear-score-seeded rival in the enemy clan.
    challenger_profile_id = fields.Many2one(
        'speedrun.profile', ondelete='cascade', string='Attacker Profile', index=True)
    opponent_profile_id = fields.Many2one(
        'speedrun.profile', ondelete='cascade', string='Defender Profile')
    attacker_clan_id = fields.Many2one('speedrun.clan', ondelete='cascade', index=True)
    attacker_won = fields.Boolean()
    winner_side = fields.Selection([('challenger', 'Challenger'), ('defender', 'Defender')])
    winner_profile_id = fields.Many2one('speedrun.profile', ondelete='set null')
    log = fields.Text(help='JSON-encoded replay of the duel.')


class SpeedrunClanWarResult(models.Model):
    _name = 'speedrun.clan.war.result'
    _description = 'Speedrun Clan War Task Result (raid/blitz)'
    _order = 'war_id, kind, duration_ms'

    war_id = fields.Many2one('speedrun.clan.war', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', required=True, index=True)
    clan_id = fields.Many2one('speedrun.clan', required=True, ondelete='cascade', index=True)
    kind = fields.Selection([('raid', 'Raid'), ('blitz', 'Blitz')], required=True)
    start_time = fields.Datetime()
    finish_time = fields.Datetime()
    duration_ms = fields.Integer(default=0)
    completed = fields.Boolean(default=False)

    _unique_result = models.Constraint(
        'UNIQUE(war_id, user_id, kind)',
        'One result per user, war and épreuve.',
    )
