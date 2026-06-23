from odoo import models


class IrWebsocket(models.AbstractModel):
    _inherit = 'ir.websocket'

    def _build_bus_channel_list(self, channels):
        channels = super()._build_bus_channel_list(channels)
        if self.env.uid:
            # Subscribe user to all their active game rooms
            # sudo: speedrun.game - need to read games regardless of ACLs for bus channels
            active_games = self.env['speedrun.game'].sudo().search([
                ('player_ids.user_id', '=', self.env.uid),
                ('state', 'in', ['waiting', 'countdown', 'running']),
            ])
            channels.extend(active_games)
        return channels
