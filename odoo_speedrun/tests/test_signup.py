from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged('post_install', '-at_install', 'speedrun')
class TestSignup(TransactionCase):

    def test_signup_enabled(self):
        """The module enables uninvited (b2c) signup."""
        scope = self.env['ir.config_parameter'].sudo().get_param('auth_signup.invitation_scope')
        self.assertEqual(scope, 'b2c')

    def test_signup_creates_internal_user(self):
        """A portal signup creates an internal user with the player group and a profile."""
        self.env['ir.config_parameter'].sudo().set_param('auth_signup.invitation_scope', 'b2c')
        self.env['res.users'].signup({
            'login': 'newplayer@example.com',
            'name': 'New Player',
            'password': 'SuperSecret!42',
        })
        user = self.env['res.users'].search([('login', '=', 'newplayer@example.com')])
        self.assertTrue(user)
        self.assertFalse(user.share, "Signed-up user must be an internal user")
        self.assertTrue(user.has_group('base.group_user'))
        self.assertTrue(user.has_group('odoo_speedrun.group_speedrun_player'))
        profile = self.env['speedrun.profile'].search([('user_id', '=', user.id)])
        self.assertTrue(profile, "A speedrun profile is created on signup")
        self.assertEqual(profile.elo, 1000)
        self.assertEqual(profile.level, 1)
