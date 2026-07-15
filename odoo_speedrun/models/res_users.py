import logging

from odoo import api, models

_logger = logging.getLogger(__name__)


class ResUsers(models.Model):
    _inherit = 'res.users'

    @api.model
    def _signup_create_user(self, values):
        """Public signups become internal users with the Speedrun Player group.

        This allows anyone to register from the portal signup page
        (/web/signup) and immediately play speedrun games in the backend.
        """
        user = super()._signup_create_user(values)
        internal_group = self.env.ref('base.group_user')
        player_group = self.env.ref('odoo_speedrun.group_speedrun_player')
        user.write({'group_ids': [(6, 0, [internal_group.id, player_group.id])]})
        # Create the speedrun profile right away
        self.env['speedrun.profile'].sudo()._get_or_create(user)
        _logger.info("Speedrun signup: created internal user %s (login: %s)", user.name, user.login)
        return user
