from odoo import api, fields, models


class SpeedrunProfileActivity(models.Model):
    """Read-only activity collections shown on the admin player form.

    These are computed (non-stored) Many2many views of records that reference
    the player's user_id, so the whole player history is visible in one place.
    """
    _inherit = 'speedrun.profile'

    boss_progress_ids = fields.Many2many(
        'speedrun.boss.progress', compute='_compute_activity', string='Boss Progress')
    round_result_ids = fields.Many2many(
        'speedrun.round.result', compute='_compute_activity', string='Task History')
    game_player_ids = fields.Many2many(
        'speedrun.player', compute='_compute_activity', string='Games')
    daily_result_ids = fields.Many2many(
        'speedrun.daily.result', compute='_compute_activity', string='Daily Results')
    task_score_ids = fields.Many2many(
        'speedrun.task.score', compute='_compute_activity', string='Per-Task ELO')
    personal_best_ids = fields.Many2many(
        'speedrun.personal.best', compute='_compute_activity', string='Best Times')
    shop_purchase_ids = fields.Many2many(
        'speedrun.shop.purchase', compute='_compute_activity', string='Shop Purchases')

    @api.depends('user_id')
    def _compute_activity(self):
        RR = self.env['speedrun.round.result']
        PL = self.env['speedrun.player']
        DR = self.env['speedrun.daily.result']
        TS = self.env['speedrun.task.score']
        PB = self.env['speedrun.personal.best']
        SP = self.env['speedrun.shop.purchase']
        BP = self.env['speedrun.boss.progress']
        for p in self:
            uid = p.user_id.id
            if not uid:
                p.boss_progress_ids = p.round_result_ids = p.game_player_ids = False
                p.daily_result_ids = p.task_score_ids = p.personal_best_ids = False
                p.shop_purchase_ids = False
                continue
            p.boss_progress_ids = BP.search([('user_id', '=', uid)])
            p.round_result_ids = RR.search(
                [('user_id', '=', uid)], order='create_date desc', limit=300)
            p.game_player_ids = PL.search([('user_id', '=', uid)], order='id desc', limit=300)
            p.daily_result_ids = DR.search([('user_id', '=', uid)], order='id desc', limit=150)
            p.task_score_ids = TS.search([('user_id', '=', uid)], order='elo desc')
            p.personal_best_ids = PB.search(
                [('user_id', '=', uid)], order='best_time_ms asc')
            p.shop_purchase_ids = SP.search([('user_id', '=', uid)], order='id desc', limit=150)
