import json
from datetime import timedelta

from odoo import api, fields, models
from odoo.addons.odoo_speedrun.models.speedrun_profile import ELEMENT_META
from odoo.addons.odoo_speedrun.models.speedrun_battle import ELEMENT_PASSIVE, ELEMENT_ORDER

RARITY_SEL = [('common', 'Common'), ('rare', 'Rare'), ('epic', 'Epic'), ('legendary', 'Legendary')]


class SpeedrunBoss(models.Model):
    """A boss on the individual PvE ladder.

    Each boss must be beaten on TWO fronts to be defeated and unlock the next:
      * Combat — win an auto-battle against the boss (gear / class check).
      * Épreuve — a speedrun challenge on a real task (complete it, complete it
        under a time limit, or complete it a number of times).
    """
    _name = 'speedrun.boss'
    _description = 'Speedrun PvE Boss (ladder)'
    _order = 'sequence, id'

    name = fields.Char(required=True)
    icon = fields.Char(default='👾', string='Emblem')
    description = fields.Char()
    sequence = fields.Integer(default=10, index=True, help="Position on the ladder.")
    active = fields.Boolean(default=True)
    element = fields.Selection([(e, e) for e in ELEMENT_ORDER], string='Element')

    # Combat stats
    stat_atk = fields.Integer(string='ATK', default=30)
    stat_def = fields.Integer(string='DEF', default=18)
    stat_spd = fields.Integer(string='SPD', default=22)
    stat_crit = fields.Integer(string='CRIT %', default=10)
    encounter_hp = fields.Integer(string='HP', default=800)

    # Épreuve (speedrun challenge) — a countdown per attempt + limited attempts.
    task_id = fields.Many2one('speedrun.task', string='Épreuve Task',
                              help="Task to complete. Empty = a random available task.")
    challenge_type = fields.Selection([
        ('time', 'Complete under the countdown'),
        ('count', 'Complete several times (each under the countdown)'),
    ], default='time', required=True)
    time_limit_ms = fields.Integer(string='Countdown (ms)', default=120000,
                                   help="Time allowed to complete one attempt.")
    target_count = fields.Integer(string='Target Count', default=3)
    epreuve_attempts = fields.Integer(
        string='Attempts', default=3,
        help="Number of tries before the boss wins and a cooldown starts.")
    epreuve_cooldown_min = fields.Integer(
        string='Cooldown (min)', default=30,
        help="Minutes to wait before re-challenging the boss after it wins.")

    # Reward on defeat
    reward_chest_rarity = fields.Selection(RARITY_SEL, default='rare')
    reward_coins = fields.Integer(default=200)

    progress_ids = fields.One2many('speedrun.boss.progress', 'boss_id')

    def _power(self):
        self.ensure_one()
        return int(self.encounter_hp * 0.4 + self.stat_atk * 3 + self.stat_def * 2.5
                   + self.stat_spd * 2 + self.stat_crit * 3)

    # ------------------------------------------------------------------
    # Progress helpers
    # ------------------------------------------------------------------
    def _progress(self, user, create=False):
        self.ensure_one()
        Progress = self.env['speedrun.boss.progress'].sudo()
        rec = Progress.search([('boss_id', '=', self.id), ('user_id', '=', user.id)], limit=1)
        if not rec and create:
            rec = Progress.create({'boss_id': self.id, 'user_id': user.id})
        return rec

    def _epreuve_task(self):
        self.ensure_one()
        if self.task_id:
            return self.task_id
        available = self.env['speedrun.task'].sudo()._get_available_tasks()
        return available[:1]

    def _epreuve_desc(self):
        self.ensure_one()
        task = self._epreuve_task()
        tname = task.name if task else '—'
        secs = '%g' % (self.time_limit_ms / 1000.0)
        if self.challenge_type == 'count':
            return "Complétez « %s » %d fois, chacune en moins de %ss" % (
                tname, self.target_count, secs)
        return "Complétez « %s » en moins de %ss" % (tname, secs)

    # ------------------------------------------------------------------
    # Cooldown helpers
    # ------------------------------------------------------------------
    def _cooldown_remaining(self, progress):
        """Seconds left before the boss can be re-challenged (0 if none)."""
        if progress and progress.cooldown_until:
            delta = (progress.cooldown_until - fields.Datetime.now()).total_seconds()
            return max(0, int(delta))
        return 0

    def _recover_cooldown(self, progress):
        """Once the cooldown elapses, refresh the attempts and clear the lock."""
        self.ensure_one()
        if progress and progress.cooldown_until \
                and fields.Datetime.now() >= progress.cooldown_until:
            progress.write({
                'cooldown_until': False,
                'attempts_left': self.epreuve_attempts,
                'epreuve_count': 0,
                'epreuve_start_time': False,
            })

    def _fail_attempt(self, user, progress):
        """Consume one attempt; trigger the boss-win cooldown if none left."""
        self.ensure_one()
        progress.attempts_left = max(0, progress.attempts_left - 1)
        progress.epreuve_start_time = False
        if progress.attempts_left <= 0:
            progress.write({
                'cooldown_until': fields.Datetime.now() + timedelta(minutes=self.epreuve_cooldown_min),
                'epreuve_count': 0,
            })
            user._bus_send('speedrun/boss_failed', {
                'boss_name': self.name, 'cooldown_min': self.epreuve_cooldown_min})
            return {'success': False, 'boss_won': True, 'attempt_failed': True,
                    **self._status_for(user)}
        return {'success': False, 'attempt_failed': True, 'too_slow': True,
                'error': "Temps écoulé ! Tentative perdue.", **self._status_for(user)}

    # ------------------------------------------------------------------
    # Combat
    # ------------------------------------------------------------------
    def _boss_fighter(self, side='opponent'):
        self.ensure_one()
        return {
            'side': side, 'name': self.name,
            'hp': self.encounter_hp, 'max_hp': self.encounter_hp,
            'atk': self.stat_atk, 'def': self.stat_def, 'spd': max(1, self.stat_spd),
            'crit': self.stat_crit, 'element': self.element or None,
            'passive': ELEMENT_PASSIVE.get(self.element), 'passive_power': 1.0, 'gauge': 0.0,
        }

    def _card(self, side='opponent'):
        self.ensure_one()
        return {
            'side': side, 'name': self.name, 'level': self.sequence, 'level_title': 'Boss',
            'power': self._power(), 'gear_score': 0, 'element': self.element or '',
            'element_meta': ELEMENT_META.get(self.element) or None,
            'emoji': self.icon or '👾', 'avatar_url': False,
            'stats': {'hp': self.encounter_hp, 'atk': self.stat_atk, 'def': self.stat_def,
                      'spd': self.stat_spd, 'crit': self.stat_crit},
            'equipped': {},
        }

    def _fight(self, profile):
        """Run the combat objective. Winning marks it done."""
        self.ensure_one()
        user = profile.user_id
        if not self._is_current(user):
            return {'error': "Ce boss n'est pas votre adversaire actuel."}
        progress = self._progress(user, create=True)
        self._recover_cooldown(progress)
        if self._cooldown_remaining(progress) > 0:
            return {'error': "Le boss vous a repoussé — attendez la fin du cooldown pour le redéfier."}
        Battle = self.env['speedrun.battle']
        c = Battle._fighter_from_profile(profile, 'challenger')
        o = self._boss_fighter('opponent')
        turns, winner = Battle._run_fight(c, o)
        won = winner == 'challenger'
        if won and not progress.combat_done:
            progress.combat_done = True
        defeat = self._maybe_defeat(progress)
        return {
            'challenger': profile._combat_payload(),
            'opponent': self._card('opponent'),
            'turns': turns,
            'winner': winner,
            'boss_result': {
                'mode': 'combat',
                'won': won,
                'combat_done': progress.combat_done,
                'epreuve_done': progress.epreuve_done,
                'defeated': defeat['defeated'],
                'reward': defeat.get('reward'),
            },
        }

    # ------------------------------------------------------------------
    # Épreuve (speedrun challenge)
    # ------------------------------------------------------------------
    def _epreuve_start(self, user):
        self.ensure_one()
        if not self._is_current(user):
            return {'error': "Ce boss n'est pas votre adversaire actuel."}
        progress = self._progress(user, create=True)
        self._recover_cooldown(progress)
        if progress.epreuve_done:
            return self._status_for(user)
        if self._cooldown_remaining(progress) > 0:
            return {'error': "Le boss vous a repoussé — attendez la fin du cooldown.",
                    **self._status_for(user)}
        if progress.attempts_left <= 0:
            progress.attempts_left = self.epreuve_attempts
        progress.epreuve_start_time = fields.Datetime.now()
        return self._status_for(user)

    def _epreuve_check(self, user):
        self.ensure_one()
        progress = self._progress(user, create=True)
        self._recover_cooldown(progress)
        if self._cooldown_remaining(progress) > 0:
            return {'error': "En récupération.", **self._status_for(user)}
        if progress.epreuve_done:
            return {'success': True, **self._status_for(user)}
        if not progress.epreuve_start_time:
            return {'error': "Démarrez d'abord l'épreuve !"}
        task = self._epreuve_task()
        if not task:
            return {'error': "Aucune tâche disponible pour l'épreuve."}
        start = progress.epreuve_start_time
        duration = int((fields.Datetime.now() - start).total_seconds() * 1000)
        completed = task._verify_completion(user.id, start)
        if completed and duration <= self.time_limit_ms:
            if self.challenge_type == 'count':
                progress.epreuve_count += 1
                progress.epreuve_start_time = False
                if progress.epreuve_count >= self.target_count:
                    progress.epreuve_done = True
            else:
                progress.epreuve_done = True
                progress.epreuve_start_time = False
            defeat = self._maybe_defeat(progress)
            return {'success': True, 'defeated': defeat['defeated'],
                    'reward': defeat.get('reward'), **self._status_for(user)}
        if duration > self.time_limit_ms:
            # Countdown elapsed -> this attempt is lost.
            return self._fail_attempt(user, progress)
        return {'success': False, 'error': "Pas encore terminé, continuez !",
                **self._status_for(user)}

    def _epreuve_timeout(self, user):
        """Called when the client countdown reaches zero: burn the attempt."""
        self.ensure_one()
        progress = self._progress(user, create=True)
        if progress.epreuve_done or not progress.epreuve_start_time:
            return self._status_for(user)
        duration = int((fields.Datetime.now() - progress.epreuve_start_time).total_seconds() * 1000)
        if duration >= self.time_limit_ms:
            return self._fail_attempt(user, progress)
        return {'success': False, **self._status_for(user)}

    # ------------------------------------------------------------------
    # Defeat & rewards
    # ------------------------------------------------------------------
    def _maybe_defeat(self, progress):
        self.ensure_one()
        if progress.defeated or not (progress.combat_done and progress.epreuve_done):
            return {'defeated': progress.defeated}
        progress.write({'defeated': True, 'defeated_date': fields.Date.today()})
        profile = self.env['speedrun.profile'].sudo()._get_or_create(progress.user_id)
        reward = {'coins': self.reward_coins, 'chest_rarity': self.reward_chest_rarity}
        if self.reward_coins:
            profile._add_coins(self.reward_coins)
        if self.reward_chest_rarity:
            profile._award_chest(self.reward_chest_rarity, source='boss')
        progress.user_id._bus_send('speedrun/boss_defeated', {
            'boss_name': self.name, 'rarity': self.reward_chest_rarity,
            'coins': self.reward_coins,
        })
        return {'defeated': True, 'reward': reward}

    # ------------------------------------------------------------------
    # Ladder navigation
    # ------------------------------------------------------------------
    @api.model
    def _ladder_bosses(self):
        return self.sudo().search([('active', '=', True)], order='sequence, id')

    def _is_defeated(self, user):
        self.ensure_one()
        p = self._progress(user)
        return bool(p and p.defeated)

    def _is_current(self, user):
        """The current boss is the first non-defeated boss on the ladder."""
        bosses = self._ladder_bosses()
        for boss in bosses:
            if not boss._is_defeated(user):
                return boss.id == self.id
        return False  # all defeated

    def _status_for(self, user):
        self.ensure_one()
        p = self._progress(user)
        is_current = self._is_current(user)
        defeated = bool(p and p.defeated)
        # locked = neither defeated nor current
        status = 'defeated' if defeated else ('current' if is_current else 'locked')
        cooldown = self._cooldown_remaining(p)
        deadline = None
        if p and p.epreuve_start_time and not p.epreuve_done:
            deadline = fields.Datetime.to_string(
                p.epreuve_start_time + timedelta(milliseconds=self.time_limit_ms))
        task = self._epreuve_task()
        return {
            'id': self.id,
            'name': self.name,
            'icon': self.icon or '👾',
            'description': self.description or '',
            'sequence': self.sequence,
            'power': self._power(),
            'element': self.element or '',
            'element_meta': ELEMENT_META.get(self.element) or None,
            'stats': {'hp': self.encounter_hp, 'atk': self.stat_atk, 'def': self.stat_def,
                      'spd': self.stat_spd, 'crit': self.stat_crit},
            'status': status,
            'combat_done': bool(p and p.combat_done),
            'epreuve_done': bool(p and p.epreuve_done),
            'epreuve_count': p.epreuve_count if p else 0,
            'epreuve_start_time': fields.Datetime.to_string(p.epreuve_start_time) if p and p.epreuve_start_time else None,
            'epreuve_deadline': deadline,
            'in_progress': bool(p and p.epreuve_start_time and not p.epreuve_done),
            'attempts': p.attempts_left if (p and p.attempts_left) else self.epreuve_attempts,
            'max_attempts': self.epreuve_attempts,
            'cooldown_remaining': cooldown,
            'challenge_type': self.challenge_type,
            'target_count': self.target_count,
            'time_limit_ms': self.time_limit_ms,
            'epreuve_desc': self._epreuve_desc(),
            'task_name': task.name if task else '',
            'task_description': task.description or '' if task else '',
            'reward': {'coins': self.reward_coins, 'chest_rarity': self.reward_chest_rarity},
        }

    @api.model
    def _ladder_payload(self, user):
        bosses = self._ladder_bosses()
        rows = [b._status_for(user) for b in bosses]
        defeated = sum(1 for r in rows if r['status'] == 'defeated')
        current = next((r for r in rows if r['status'] == 'current'), None)
        return {
            'bosses': rows,
            'defeated_count': defeated,
            'total': len(rows),
            'current': current,
            'all_cleared': current is None and bool(rows),
        }


class SpeedrunBossProgress(models.Model):
    _name = 'speedrun.boss.progress'
    _description = 'Speedrun PvE Boss Progress'
    _order = 'boss_id, id'

    user_id = fields.Many2one('res.users', required=True, index=True, ondelete='cascade')
    boss_id = fields.Many2one('speedrun.boss', required=True, index=True, ondelete='cascade')
    combat_done = fields.Boolean(default=False)
    epreuve_done = fields.Boolean(default=False)
    epreuve_count = fields.Integer(default=0)
    epreuve_start_time = fields.Datetime()
    attempts_left = fields.Integer(default=0)
    cooldown_until = fields.Datetime()
    defeated = fields.Boolean(default=False, index=True)
    defeated_date = fields.Date()

    _unique_progress = models.Constraint(
        'UNIQUE(user_id, boss_id)',
        'One progress record per player and boss.',
    )
