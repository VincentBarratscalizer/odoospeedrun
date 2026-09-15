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

    # ------------------------------------------------------------------
    # Clan wars
    # ------------------------------------------------------------------
    speedrun_blitz_hour = fields.Integer(
        string="Clan War Blitz Hour",
        config_parameter='odoo_speedrun.blitz_hour',
        default=18,
        help="Hour of day (0-23, server/UTC time) at which the collective Blitz "
             "épreuve of a clan war takes place. During the Blitz window every "
             "normal-game task completion by a clan's members counts.",
    )
    speedrun_blitz_duration_minutes = fields.Integer(
        string="Clan War Blitz Duration (min)",
        config_parameter='odoo_speedrun.blitz_duration_minutes',
        default=60,
        help="Length in minutes of the clan war Blitz window.",
    )
    # --- Clan war victory loot (chests awarded to each winning member) ---
    speedrun_clan_war_loot_common = fields.Integer(
        string="Victory Common Chests",
        config_parameter='odoo_speedrun.clan_war_loot_common',
        default=0,
        help="Number of Common chests each member of the winning clan receives.",
    )
    speedrun_clan_war_loot_rare = fields.Integer(
        string="Victory Rare Chests",
        config_parameter='odoo_speedrun.clan_war_loot_rare',
        default=1,
        help="Number of Rare chests each member of the winning clan receives.",
    )
    speedrun_clan_war_loot_epic = fields.Integer(
        string="Victory Epic Chests",
        config_parameter='odoo_speedrun.clan_war_loot_epic',
        default=0,
        help="Number of Epic chests each member of the winning clan receives.",
    )
    speedrun_clan_war_loot_legendary = fields.Integer(
        string="Victory Legendary Chests",
        config_parameter='odoo_speedrun.clan_war_loot_legendary',
        default=0,
        help="Number of Legendary chests each member of the winning clan receives.",
    )
    speedrun_clan_war_win_coins = fields.Integer(
        string="Victory Coins",
        config_parameter='odoo_speedrun.clan_war_win_coins',
        default=150,
        help="Coins awarded to each member of the winning clan.",
    )
    speedrun_clan_war_loss_coins = fields.Integer(
        string="Consolation Coins",
        config_parameter='odoo_speedrun.clan_war_loss_coins',
        default=40,
        help="Coins awarded to each member of the losing clan.",
    )

    # ------------------------------------------------------------------
    # Data cleanup / demo reset
    # ------------------------------------------------------------------
    speedrun_cleanup_enabled = fields.Boolean(
        string="Enable Demo Reset",
        config_parameter='odoo_speedrun.cleanup_enabled',
        default=True,
        help="When enabled, the scheduled action periodically deletes all "
             "records players created during rounds and reloads the demo data. "
             "The game's own data (scores, profiles, chests...) is preserved.",
    )
    speedrun_cleanup_reload_demo = fields.Boolean(
        string="Reload Demo Data",
        config_parameter='odoo_speedrun.cleanup_reload_demo',
        default=True,
        help="Also reload the demo data of every installed module (except the "
             "speedrun ones) to revert any modification or deletion of demo "
             "records made by players. Slower — disable to only delete created "
             "records.",
    )

    def action_speedrun_reset_now(self):
        """Run the demo reset immediately from the settings button."""
        self.ensure_one()
        return self.env['speedrun.cleanup'].action_reset_now()
