from odoo import api, fields, models


class SpeedrunBadge(models.Model):
    _name = 'speedrun.badge'
    _description = 'Speedrun Badge'
    _order = 'sequence, id'

    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True)
    icon = fields.Char(default='🏅', help="Emoji shown next to the badge.")
    sequence = fields.Integer(default=10)
    criteria_type = fields.Selection([
        ('games_played', 'Games Played'),
        ('games_won', 'Games Won'),
        ('rounds_won', 'Rounds Won'),
        ('best_time_under', 'Best Time Under (ms)'),
        ('elo_reached', 'ELO Reached'),
        ('level_reached', 'Level Reached'),
    ], required=True, default='games_played')
    threshold = fields.Integer(
        required=True, default=1,
        help="Value to reach (count, ELO, level, or milliseconds for time-based badges).",
    )
    xp_reward = fields.Integer(default=0, help="Bonus XP granted when the badge is earned.")
    active = fields.Boolean(default=True)
    award_ids = fields.One2many('speedrun.badge.award', 'badge_id')
    award_count = fields.Integer(compute='_compute_award_count')

    @api.depends('award_ids')
    def _compute_award_count(self):
        for badge in self:
            badge.award_count = len(badge.award_ids)

    def _matches_profile(self, profile):
        """Return True if the profile meets this badge's criteria."""
        self.ensure_one()
        if self.criteria_type == 'games_played':
            return profile.games_played >= self.threshold
        if self.criteria_type == 'games_won':
            return profile.games_won >= self.threshold
        if self.criteria_type == 'rounds_won':
            return profile.rounds_won >= self.threshold
        if self.criteria_type == 'best_time_under':
            return bool(profile.best_time_ms) and profile.best_time_ms <= self.threshold
        if self.criteria_type == 'elo_reached':
            return profile.elo >= self.threshold
        if self.criteria_type == 'level_reached':
            return profile.level >= self.threshold
        return False


class SpeedrunBadgeAward(models.Model):
    _name = 'speedrun.badge.award'
    _description = 'Speedrun Badge Award'
    _order = 'create_date desc, id desc'
    _rec_name = 'badge_id'

    profile_id = fields.Many2one('speedrun.profile', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one(related='profile_id.user_id', store=True)
    badge_id = fields.Many2one('speedrun.badge', required=True, ondelete='cascade')
    game_id = fields.Many2one('speedrun.game', ondelete='set null', help="Game during which the badge was earned.")

    _unique_badge_per_profile = models.Constraint(
        'UNIQUE(profile_id, badge_id)',
        'A badge can only be awarded once per player.',
    )
