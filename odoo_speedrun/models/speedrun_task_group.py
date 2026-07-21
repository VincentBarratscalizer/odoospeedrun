from odoo import api, fields, models


class SpeedrunTaskGroup(models.Model):
    _name = 'speedrun.task.group'
    _description = 'Speedrun Task Group'
    _order = 'sequence, name'

    name = fields.Char(required=True, translate=True)
    icon = fields.Char(help="Emoji shown next to the group (used when no image is set).")
    image_128 = fields.Image(
        string="Image", max_width=128, max_height=128,
        help="Optional icon (PNG) shown for the group. Takes precedence over the emoji.")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    task_ids = fields.Many2many(
        'speedrun.task',
        'speedrun_task_group_rel', 'group_id', 'task_id',
        string='Tasks',
    )
    task_count = fields.Integer(compute='_compute_task_count')
    available_task_count = fields.Integer(compute='_compute_task_count')

    @api.depends('task_ids')
    def _compute_task_count(self):
        for group in self:
            group.task_count = len(group.task_ids)
            group.available_task_count = len(group.task_ids.filtered(
                lambda t: t.active and t._check_modules_installed()
            ))

    def _image_url(self):
        """Return a web image URL for the group icon, or False if none set."""
        self.ensure_one()
        if not self.image_128:
            return False
        return '/web/image/speedrun.task.group/%s/image_128' % self.id

    @api.model
    def _get_selectable_groups(self):
        """Return active groups that currently have at least one playable task
        (i.e. whose required modules are installed)."""
        groups = self.search([])
        return groups.filtered(lambda g: g.available_task_count > 0)
