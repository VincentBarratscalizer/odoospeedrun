from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    speedrun_pity_enabled = fields.Boolean(
        string="Enable Chest Pity",
        config_parameter='odoo_speedrun.pity_enabled',
        default=True,
        help="When enabled, unlucky streaks of chest openings gradually raise "
             "the odds of a high-rarity drop and eventually guarantee one.",
    )
    speedrun_pity_legendary_hard = fields.Integer(
        string="Guaranteed Legendary after",
        config_parameter='odoo_speedrun.pity_legendary_hard',
        default=50,
        help="Number of chest openings without a legendary after which the "
             "next opening is guaranteed to drop a legendary item (0 = off).",
    )
    speedrun_pity_epic_hard = fields.Integer(
        string="Guaranteed Epic (or better) after",
        config_parameter='odoo_speedrun.pity_epic_hard',
        default=10,
        help="Number of chest openings without an epic-or-better after which "
             "the next opening is guaranteed to drop at least an epic (0 = off).",
    )
    speedrun_pity_soft_start = fields.Integer(
        string="Legendary Soft Pity starts at",
        config_parameter='odoo_speedrun.pity_soft_start',
        default=40,
        help="From this many openings without a legendary, each further "
             "opening increases the legendary drop weight (0 = off).",
    )
    speedrun_pity_soft_step = fields.Integer(
        string="Soft Pity increment (weight)",
        config_parameter='odoo_speedrun.pity_soft_step',
        default=5,
        help="Legendary drop weight added per opening once soft pity started.",
    )
