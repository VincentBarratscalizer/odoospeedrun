import math

from odoo import api, fields, models
from odoo.exceptions import UserError


class SpeedrunProfileClan(models.Model):
    _inherit = 'speedrun.profile'

    clan_id = fields.Many2one('speedrun.clan', string='Clan', ondelete='set null', index=True)
    clan_role = fields.Selection([
        ('leader', 'Chef'),
        ('officer', 'Officier'),
        ('member', 'Membre'),
    ], default='member', string='Clan Role')

    # Weekly login-reward streak (tied to completing the daily challenge)
    loot_sequence_id = fields.Many2one(
        'speedrun.loot.sequence', string='Current Reward Cycle', ondelete='set null')
    loot_day = fields.Integer(string='Reward Cycle Day', default=0)
    loot_last_claim = fields.Date(string='Last Reward Claim')

    def _reward_in_progress(self):
        """True when the player is inside a live (unbroken) 7-day cycle."""
        self.ensure_one()
        yesterday = fields.Date.subtract(fields.Date.today(), days=1)
        return bool(
            self.loot_sequence_id and 1 <= self.loot_day <= 7
            and self.loot_last_claim and self.loot_last_claim >= yesterday
        )

    def _ensure_reward_preview(self):
        """Guarantee an upcoming cycle is assigned so rewards are always visible.

        When the player is not inside a live cycle, a random cycle is drawn and
        stored (at day 0) so the whole 7-day track is shown in advance — and
        honored when the player next claims.
        """
        self.ensure_one()
        if self._reward_in_progress():
            return
        if self.loot_day != 0 or not self.loot_sequence_id:
            seq = self.env['speedrun.loot.sequence'].sudo()._pick_random()
            vals = {'loot_day': 0}
            if seq:
                vals['loot_sequence_id'] = seq.id
            self.write(vals)

    def _advance_weekly_reward(self):
        """Claim today's weekly-streak reward after completing the daily task.

        Continues the current cycle if the previous claim was yesterday and the
        cycle is not finished; otherwise starts a fresh cycle at day 1 using the
        already-previewed (visible) sequence. Returns the granted reward dict,
        or None if today was already claimed.
        """
        self.ensure_one()
        today = fields.Date.today()
        if self.loot_last_claim == today:
            return None
        yesterday = fields.Date.subtract(today, days=1)
        continuing = (
            self.loot_last_claim == yesterday
            and self.loot_sequence_id
            and 1 <= self.loot_day < 7
        )
        if continuing:
            seq = self.loot_sequence_id
            new_day = self.loot_day + 1
        else:
            # Honor the previewed cycle if one is assigned; else draw a new one.
            seq = self.loot_sequence_id if (self.loot_sequence_id and self.loot_day == 0) \
                else self.env['speedrun.loot.sequence'].sudo()._pick_random()
            new_day = 1
        if not seq:
            return None
        self.write({
            'loot_sequence_id': seq.id,
            'loot_day': new_day,
            'loot_last_claim': today,
        })
        day_rec = seq._day(new_day)
        reward = day_rec._grant(self) if day_rec else {'type': 'chest', 'rarity': 'common'}
        reward['day'] = new_day
        reward['is_new_cycle'] = not continuing
        # If the cycle just finished, reveal the next one straight away.
        if new_day >= 7:
            nxt = self.env['speedrun.loot.sequence'].sudo()._pick_random()
            self.write({'loot_sequence_id': nxt.id if nxt else False, 'loot_day': 0})
        return reward

    def _weekly_reward_payload(self):
        """Reward-track state for the frontend (7 visible slots + progress)."""
        self.ensure_one()
        self._ensure_reward_preview()
        today = fields.Date.today()
        in_progress = self._reward_in_progress()
        seq = self.loot_sequence_id
        claimed_day = self.loot_day if in_progress else 0
        claimed_today = self.loot_last_claim == today
        next_day = min(claimed_day + 1, 7) if in_progress else 1
        days = []
        for d in range(1, 8):
            rec = seq._day(d) if seq else self.env['speedrun.loot.sequence.day']
            disp = rec._display() if rec else {'icon': '❓', 'label': 'Surprise'}
            days.append({
                'day': d,
                'icon': disp['icon'],
                'label': disp['label'],
                'coins': rec.coins if rec else 0,
                'claimed': d <= claimed_day,
                'is_next': d == next_day and claimed_day < 7,
            })
        return {
            'sequence_name': seq.name if seq else '',
            'known': bool(seq),
            'claimed_day': claimed_day,
            'claimed_today': claimed_today,
            'next_day': next_day,
            'days': days,
        }

# Tuning
MAX_CLAN_MEMBERS = 20
CLAN_NAME_MIN = 3
CLAN_TAG_MIN = 2
CLAN_TAG_MAX = 5


class SpeedrunClan(models.Model):
    _name = 'speedrun.clan'
    _description = 'Speedrun Clan'
    _order = 'clan_elo desc, trophies desc, id'

    name = fields.Char(required=True, index=True)
    tag = fields.Char(required=True, help="Short clan tag, shown as [TAG] next to members.")
    emblem = fields.Char(string='Emblem', default='🛡️', help="Emoji used as the clan emblem.")
    description = fields.Text()
    motto = fields.Char(string='Motto')

    leader_id = fields.Many2one('res.users', string='Clan Leader', required=True, index=True)
    member_profile_ids = fields.One2many('speedrun.profile', 'clan_id', string='Members')
    member_count = fields.Integer(compute='_compute_member_count', store=True)
    max_members = fields.Integer(default=MAX_CLAN_MEMBERS)

    clan_elo = fields.Integer(string='Clan ELO', default=1000, index=True)
    clan_peak_elo = fields.Integer(string='Peak Clan ELO', default=1000)
    clan_xp = fields.Integer(string='Clan XP', default=0)
    clan_level = fields.Integer(compute='_compute_clan_level', store=True)
    treasury = fields.Integer(string='Treasury 💰', default=0)

    wars_played = fields.Integer(default=0)
    wars_won = fields.Integer(default=0)
    war_streak = fields.Integer(default=0)
    trophies = fields.Integer(default=0, index=True)
    win_rate = fields.Float(string='War Win Rate (%)', compute='_compute_win_rate')

    total_power = fields.Integer(compute='_compute_strength')
    avg_gear_score = fields.Integer(compute='_compute_strength')

    active = fields.Boolean(default=True)

    _unique_name = models.Constraint('UNIQUE(name)', 'A clan with this name already exists.')
    _unique_tag = models.Constraint('UNIQUE(tag)', 'A clan with this tag already exists.')

    # ------------------------------------------------------------------
    # Computes
    # ------------------------------------------------------------------
    @api.depends('member_profile_ids')
    def _compute_member_count(self):
        for clan in self:
            clan.member_count = len(clan.member_profile_ids)

    @api.depends('clan_xp')
    def _compute_clan_level(self):
        for clan in self:
            clan.clan_level = math.isqrt(max(clan.clan_xp, 0) // 500) + 1

    @api.depends('wars_played', 'wars_won')
    def _compute_win_rate(self):
        for clan in self:
            clan.win_rate = (
                clan.wars_won * 100.0 / clan.wars_played if clan.wars_played else 0.0
            )

    @api.depends('member_profile_ids.power', 'member_profile_ids.gear_score')
    def _compute_strength(self):
        for clan in self:
            members = clan.member_profile_ids
            clan.total_power = sum(members.mapped('power'))
            clan.avg_gear_score = int(
                sum(members.mapped('gear_score')) / len(members)) if members else 0

    # ------------------------------------------------------------------
    # Membership helpers
    # ------------------------------------------------------------------
    @api.model
    def _profile_for(self, user):
        return self.env['speedrun.profile'].sudo()._get_or_create(user)

    @api.model
    def _my_clan(self, user=None):
        """Return the clan of the given (or current) user, empty recordset if none."""
        user = user or self.env.user
        profile = self._profile_for(user)
        return profile.clan_id

    def _is_leader(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        return self.leader_id.id == user.id

    # ------------------------------------------------------------------
    # Clan lifecycle
    # ------------------------------------------------------------------
    @api.model
    def _create_clan(self, name, tag, emblem=None, description=None, motto=None):
        """Create a clan with the current user as leader."""
        user = self.env.user
        name = (name or '').strip()
        tag = (tag or '').strip().upper()
        if len(name) < CLAN_NAME_MIN:
            raise UserError("Le nom du clan doit contenir au moins %d caractères." % CLAN_NAME_MIN)
        if not (CLAN_TAG_MIN <= len(tag) <= CLAN_TAG_MAX):
            raise UserError("Le tag doit contenir entre %d et %d caractères." % (CLAN_TAG_MIN, CLAN_TAG_MAX))
        profile = self._profile_for(user)
        if profile.clan_id:
            raise UserError("Vous êtes déjà membre d'un clan. Quittez-le d'abord.")
        if self.sudo().search_count([('name', '=ilike', name)]):
            raise UserError("Un clan porte déjà ce nom.")
        if self.sudo().search_count([('tag', '=ilike', tag)]):
            raise UserError("Ce tag est déjà pris.")
        clan = self.sudo().create({
            'name': name,
            'tag': tag,
            'emblem': (emblem or '🛡️')[:4],
            'description': description or '',
            'motto': motto or '',
            'leader_id': user.id,
        })
        profile.sudo().write({'clan_id': clan.id, 'clan_role': 'leader'})
        return clan

    def _join(self, user=None):
        """Add a user to this clan."""
        self.ensure_one()
        user = user or self.env.user
        profile = self._profile_for(user)
        if profile.clan_id:
            raise UserError("Vous êtes déjà membre d'un clan.")
        if self.member_count >= self.max_members:
            raise UserError("Ce clan est complet (%d membres)." % self.max_members)
        profile.sudo().write({'clan_id': self.id, 'clan_role': 'member'})
        self.leader_id._bus_send('speedrun/clan_update', {
            'event': 'member_joined', 'clan_id': self.id, 'user_name': user.name,
        })
        return True

    def _leave(self, user=None):
        """Remove a user from this clan (handles leader succession / disband)."""
        self.ensure_one()
        user = user or self.env.user
        profile = self._profile_for(user)
        if profile.clan_id.id != self.id:
            raise UserError("Vous n'appartenez pas à ce clan.")
        if self._has_active_war():
            raise UserError("Impossible de quitter le clan pendant une guerre.")
        if self._is_leader(user):
            others = self.member_profile_ids.filtered(lambda p: p.user_id.id != user.id)
            if others:
                # Promote the strongest remaining member.
                heir = others.sorted(lambda p: (p.power, p.gear_score), reverse=True)[0]
                profile.sudo().write({'clan_id': False, 'clan_role': 'member'})
                self.sudo().write({'leader_id': heir.user_id.id})
                heir.sudo().write({'clan_role': 'leader'})
                heir.user_id._bus_send('speedrun/clan_update', {
                    'event': 'promoted_leader', 'clan_id': self.id,
                })
            else:
                # Last member leaving -> disband.
                profile.sudo().write({'clan_id': False, 'clan_role': 'member'})
                self.sudo()._disband(force=True)
        else:
            profile.sudo().write({'clan_id': False, 'clan_role': 'member'})
        return True

    def _kick(self, target_profile):
        """Leader kicks a member out."""
        self.ensure_one()
        if not self._is_leader():
            raise UserError("Seul le chef de clan peut exclure un membre.")
        target = self.env['speedrun.profile'].sudo().browse(int(target_profile))
        if not target.exists() or target.clan_id.id != self.id:
            raise UserError("Membre introuvable.")
        if target.user_id.id == self.leader_id.id:
            raise UserError("Le chef ne peut pas s'exclure lui-même.")
        if self._has_active_war():
            raise UserError("Impossible d'exclure un membre pendant une guerre.")
        target.sudo().write({'clan_id': False, 'clan_role': 'member'})
        target.user_id._bus_send('speedrun/clan_update', {
            'event': 'kicked', 'clan_id': self.id,
        })
        return True

    def _transfer_lead(self, target_profile):
        """Leader hands leadership to another member."""
        self.ensure_one()
        if not self._is_leader():
            raise UserError("Seul le chef de clan peut transmettre le commandement.")
        target = self.env['speedrun.profile'].sudo().browse(int(target_profile))
        if not target.exists() or target.clan_id.id != self.id:
            raise UserError("Membre introuvable.")
        old_leader = self._profile_for(self.leader_id)
        old_leader.sudo().write({'clan_role': 'member'})
        target.sudo().write({'clan_role': 'leader'})
        self.sudo().write({'leader_id': target.user_id.id})
        return True

    def _disband(self, force=False):
        """Disband the clan: clear members and delete it."""
        self.ensure_one()
        if not force and not self._is_leader():
            raise UserError("Seul le chef de clan peut dissoudre le clan.")
        if self._has_active_war():
            raise UserError("Impossible de dissoudre le clan pendant une guerre.")
        members = self.member_profile_ids
        member_users = members.user_id
        members.sudo().write({'clan_id': False, 'clan_role': 'member'})
        for u in member_users:
            u._bus_send('speedrun/clan_update', {'event': 'disbanded', 'clan_id': self.id})
        self.sudo().unlink()
        return True

    # ------------------------------------------------------------------
    # War helpers
    # ------------------------------------------------------------------
    def _active_war(self):
        """Return this clan's current (declared/running) war, if any."""
        self.ensure_one()
        return self.env['speedrun.clan.war'].sudo().search([
            '|', ('challenger_clan_id', '=', self.id), ('defender_clan_id', '=', self.id),
            ('state', 'in', ('declared', 'running')),
        ], limit=1, order='id desc')

    def _has_active_war(self):
        self.ensure_one()
        return bool(self._active_war())

    # ------------------------------------------------------------------
    # Rewards from a war (called by speedrun.clan.war)
    # ------------------------------------------------------------------
    def _add_clan_xp(self, amount):
        self.ensure_one()
        self.sudo().clan_xp = max(0, self.clan_xp + amount)

    # ------------------------------------------------------------------
    # Payloads
    # ------------------------------------------------------------------
    def _member_payload(self):
        self.ensure_one()
        rows = []
        for p in self.member_profile_ids.sorted(lambda m: (m.clan_role != 'leader', -m.power)):
            rows.append({
                'profile_id': p.id,
                'user_id': p.user_id.id,
                'name': p.user_id.name,
                'avatar_url': f'/web/image/res.users/{p.user_id.id}/avatar_128',
                'level': p.level,
                'role': p.clan_role,
                'power': p.power,
                'gear_score': p.gear_score,
                'is_leader': p.user_id.id == self.leader_id.id,
            })
        return rows

    def _info(self, user=None):
        """Full clan payload for the frontend."""
        self.ensure_one()
        user = user or self.env.user
        war = self._active_war()
        last_war = None
        if not war:
            recent = self.env['speedrun.clan.war'].sudo().search([
                '|', ('challenger_clan_id', '=', self.id), ('defender_clan_id', '=', self.id),
                ('state', '=', 'finished'),
            ], limit=1, order='write_date desc')
            if recent:
                last_war = recent._info(user)
        return {
            'id': self.id,
            'name': self.name,
            'tag': self.tag,
            'emblem': self.emblem or '🛡️',
            'description': self.description or '',
            'motto': self.motto or '',
            'leader_id': self.leader_id.id,
            'leader_name': self.leader_id.name,
            'member_count': self.member_count,
            'max_members': self.max_members,
            'clan_elo': self.clan_elo,
            'clan_level': self.clan_level,
            'clan_xp': self.clan_xp,
            'treasury': self.treasury,
            'wars_played': self.wars_played,
            'wars_won': self.wars_won,
            'war_streak': self.war_streak,
            'trophies': self.trophies,
            'win_rate': round(self.win_rate, 1),
            'total_power': self.total_power,
            'avg_gear_score': self.avg_gear_score,
            'is_leader': self._is_leader(user),
            'members': self._member_payload(),
            'war': war._info(user) if war else None,
            'last_war': last_war,
        }

    @api.model
    def _browse_list(self, limit=50):
        """Return a lightweight list of clans (for the browse/join screen)."""
        clans = self.sudo().search([], limit=int(limit))
        return [{
            'id': c.id,
            'name': c.name,
            'tag': c.tag,
            'emblem': c.emblem or '🛡️',
            'motto': c.motto or '',
            'member_count': c.member_count,
            'max_members': c.max_members,
            'clan_elo': c.clan_elo,
            'clan_level': c.clan_level,
            'trophies': c.trophies,
            'total_power': c.total_power,
        } for c in clans]

    @api.model
    def _leaderboard_rows(self, limit=25):
        """Rows for the unified leaderboard (kind='clans')."""
        my_clan = self._my_clan()
        clans = self.sudo().search(
            [('wars_played', '>', 0)], order='clan_elo desc, trophies desc', limit=int(limit))
        if not clans:
            clans = self.sudo().search([], order='clan_elo desc, trophies desc', limit=int(limit))
        return [{
            'clan_id': c.id,
            'name': c.name,
            'tag': c.tag,
            'emblem': c.emblem or '🛡️',
            'value': c.clan_elo,
            'level': c.clan_level,
            'members': c.member_count,
            'trophies': c.trophies,
            'wars_won': c.wars_won,
            'win_rate': round(c.win_rate, 1),
            'power': c.total_power,
            'is_me': c.id == my_clan.id,
        } for c in clans]
