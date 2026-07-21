import json
import logging

from odoo import api, fields, models
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class SpeedrunTask(models.Model):
    _name = 'speedrun.task'
    _description = 'Speedrun Task Definition'
    _order = 'difficulty, name'

    name = fields.Char(required=True, translate=True)
    description = fields.Text(translate=True, help="Detailed instructions shown to players during the game.")
    target_model = fields.Char(
        required=True,
        help="Technical name of the Odoo model to check (e.g. res.partner, account.move).",
    )
    verification_method = fields.Selection(
        [('domain', 'Domain'), ('python', 'Python Code')],
        default='domain',
        required=True,
    )
    verification_domain = fields.Text(
        default='[]',
        help="JSON domain with placeholders: __uid__ (current user ID), "
             "__game_start__ (game start datetime as string).",
    )
    verification_code = fields.Text(
        help="Python code for complex verification. Available variables: env, uid, start_time. "
             "Must set result = True/False.",
    )
    verification_count = fields.Integer(default=1, help="Number of matching records needed.")
    difficulty = fields.Selection(
        [('easy', 'Easy'), ('medium', 'Medium'), ('hard', 'Hard')],
        default='medium',
        required=True,
    )
    required_modules = fields.Char(
        help="Comma-separated module technical names required for this task (e.g. sale,account).",
    )
    group_ids = fields.Many2many(
        'speedrun.task.group',
        'speedrun_task_group_rel', 'task_id', 'group_id',
        string='Groups',
    )
    active = fields.Boolean(default=True)

    def _check_modules_installed(self):
        """Return True if all required modules for this task are installed."""
        self.ensure_one()
        if not self.required_modules:
            return True
        module_names = [m.strip() for m in self.required_modules.split(',') if m.strip()]
        if not module_names:
            return True
        installed = self.env['ir.module.module'].search_count([
            ('name', 'in', module_names),
            ('state', '=', 'installed'),
        ])
        return installed == len(module_names)

    def _verify_completion(self, user_id, start_time):
        """Check if a user has completed this task.

        :param int user_id: The user ID to check.
        :param datetime start_time: The game start time.
        :return: True if the task is completed.
        """
        self.ensure_one()
        if self.verification_method == 'domain':
            return self._verify_domain(user_id, start_time)
        elif self.verification_method == 'python':
            return self._verify_python(user_id, start_time)
        return False

    def _verify_domain(self, user_id, start_time):
        """Verify task completion using a domain search."""
        self.ensure_one()
        domain_str = self.verification_domain or '[]'
        # Replace placeholders
        domain_str = domain_str.replace('"__uid__"', str(user_id))
        domain_str = domain_str.replace(
            '"__game_start__"',
            '"%s"' % fields.Datetime.to_string(start_time),
        )
        try:
            domain = json.loads(domain_str)
        except (ValueError, json.JSONDecodeError):
            _logger.error("Invalid verification domain for task %s: %s", self.name, domain_str)
            return False
        try:
            count = self.env[self.target_model].with_user(user_id).search_count(domain)
        except Exception:
            _logger.exception("Error verifying task %s for user %s", self.name, user_id)
            return False
        return count >= self.verification_count

    def _verify_python(self, user_id, start_time):
        """Verify task completion using Python safe_eval."""
        self.ensure_one()
        if not self.verification_code:
            return False
        local_vars = {
            'env': self.env,
            'uid': user_id,
            'start_time': start_time,
            'result': False,
        }
        try:
            safe_eval(self.verification_code, local_vars, mode='exec')
        except Exception:
            _logger.exception("Error in Python verification for task %s", self.name)
            return False
        return bool(local_vars.get('result', False))

    @api.model
    def _get_available_tasks(self):
        """Return tasks whose required modules are all installed."""
        tasks = self.search([('active', '=', True)])
        return tasks.filtered(lambda t: t._check_modules_installed())
