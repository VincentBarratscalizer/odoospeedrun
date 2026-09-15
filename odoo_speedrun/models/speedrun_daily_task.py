import random

from odoo import api, fields, models


class SpeedrunDailyTask(models.Model):
    _name = 'speedrun.daily.task'
    _description = 'Daily Speedrun Challenge'
    _order = 'date desc'

    date = fields.Date(required=True, index=True, default=fields.Date.today)
    task_id = fields.Many2one('speedrun.task', required=True, ondelete='restrict')
    result_ids = fields.One2many('speedrun.daily.result', 'daily_id', string='Results')
    completion_count = fields.Integer(compute='_compute_completion_count', store=True)

    _sql_constraints = [
        ('unique_date', 'UNIQUE(date)', 'Only one daily task per day.'),
    ]

    @api.depends('result_ids.completed')
    def _compute_completion_count(self):
        for daily in self:
            daily.completion_count = len(daily.result_ids.filtered('completed'))

    # ------------------------------------------------------------------
    # Class-level helpers
    # ------------------------------------------------------------------

    @api.model
    def _get_or_create_today(self):
        """Return today's daily task, creating it if it doesn't exist yet."""
        today = fields.Date.today()
        daily = self.sudo().search([('date', '=', today)], limit=1)
        if not daily:
            available = self.env['speedrun.task'].sudo()._get_available_tasks()
            if not available:
                return self.browse()
            task = self.env['speedrun.task'].browse(random.choice(available.ids))
            daily = self.sudo().create({'date': today, 'task_id': task.id})
        return daily

    # ------------------------------------------------------------------
    # Instance helpers
    # ------------------------------------------------------------------

    def _get_my_result(self, uid):
        """Return this user's result record for today (may be empty)."""
        self.ensure_one()
        return self.sudo().result_ids.filtered(lambda r: r.user_id.id == uid)

    def _get_my_rank(self, uid):
        """Return the user's rank among completions (1 = fastest). 0 if not completed."""
        self.ensure_one()
        completed = self.sudo().result_ids.filtered('completed').sorted('duration_ms')
        for idx, r in enumerate(completed):
            if r.user_id.id == uid:
                return idx + 1
        return 0

    def _get_leaderboard_data(self, limit=50):
        """Return the top completions sorted by duration_ms."""
        self.ensure_one()
        completed = self.sudo().result_ids.filtered('completed').sorted('duration_ms')
        return [{
            'rank': idx + 1,
            'user_id': r.user_id.id,
            'user_name': r.user_id.name,
            'duration_ms': r.duration_ms,
        } for idx, r in enumerate(completed[:limit])]

    def _get_info(self, uid):
        """Full payload for the frontend."""
        self.ensure_one()
        my = self._get_my_result(uid)
        if my and my.completed:
            my_status = 'completed'
        elif my and my.start_time:
            my_status = 'in_progress'
        else:
            my_status = 'not_started'

        profile = self.env['speedrun.profile'].sudo()._get_or_create(
            self.env['res.users'].browse(uid))
        return {
            'date': fields.Date.to_string(self.date),
            'task_name': self.task_id.name,
            'task_description': self.task_id.description or '',
            'my_status': my_status,
            'my_duration_ms': my.duration_ms if my else 0,
            'my_start_time': fields.Datetime.to_string(my.start_time) if my and my.start_time else None,
            'my_rank': self._get_my_rank(uid),
            'completion_count': self.completion_count,
            'leaderboard': self._get_leaderboard_data(),
            'weekly_reward': profile._weekly_reward_payload(),
        }

    def _start_for_user(self, uid):
        """Record the start of the daily challenge for this user."""
        self.ensure_one()
        my = self._get_my_result(uid)
        if my and my.completed:
            return {'error': "You already completed today's challenge!"}
        if my and my.start_time:
            # Already started — just return current info (resume)
            return self._get_info(uid)
        # Create result row with start_time
        now = fields.Datetime.now()
        self.sudo().env['speedrun.daily.result'].create({
            'daily_id': self.id,
            'user_id': uid,
            'start_time': now,
        })
        return self._get_info(uid)

    def _check_completion(self, uid):
        """Verify the task and, if done, record finish_time."""
        self.ensure_one()
        my = self._get_my_result(uid)
        if not my or not my.start_time:
            return {'error': 'Start the challenge first!'}
        if my.completed:
            return {'already_completed': True, **self._get_info(uid)}

        completed = self.sudo().task_id._verify_completion(uid, my.start_time)
        if not completed:
            return {'success': False, 'error': 'Task not completed yet. Keep going!'}

        now = fields.Datetime.now()
        duration_ms = int((now - my.start_time).total_seconds() * 1000)
        my.sudo().write({
            'finish_time': now,
            'duration_ms': duration_ms,
            'completed': True,
        })
        # Recompute completion_count
        self.sudo()._compute_completion_count()

        # Weekly login-reward streak: advance the cycle and grant today's reward.
        profile = self.env['speedrun.profile'].sudo()._get_or_create(
            self.env['res.users'].browse(uid))
        streak_reward = profile._advance_weekly_reward()

        info = self._get_info(uid)
        info['success'] = True
        if streak_reward:
            info['streak_reward'] = streak_reward
        return info


class SpeedrunDailyResult(models.Model):
    _name = 'speedrun.daily.result'
    _description = 'Daily Challenge Result'
    _order = 'duration_ms asc'

    daily_id = fields.Many2one('speedrun.daily.task', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', required=True, index=True)
    start_time = fields.Datetime(string='Started At')
    finish_time = fields.Datetime(string='Finished At')
    duration_ms = fields.Integer(string='Duration (ms)', default=0)
    completed = fields.Boolean(default=False)

    _sql_constraints = [
        ('unique_user_daily', 'UNIQUE(daily_id, user_id)', 'One attempt per user per day.'),
    ]
