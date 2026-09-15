from odoo import fields, models
from odoo.addons.odoo_speedrun.models.speedrun_profile import ELEMENT_META

# Class upgrade tuning (spend coins to strengthen the element's passive only).
CLASS_LEVEL_MAX = 10
CLASS_UPGRADE_BASE = 500           # coin cost of a level = BASE * (level + 1)
CLASS_LEVEL_STEP = 0.06            # passive multiplier gained per class level
DOMAIN_MAX_BONUS = 0.25            # extra passive multiplier at domain rating 100

ELEMENTS = ('peripheral', 'display', 'badge', 'module', 'tech', 'desk')

# Correspondence between each class (element) and its task categories (by the
# task-group name). Being highly ranked in these categories boosts the class.
ELEMENT_CATEGORIES = {
    'badge':      ['Sales', 'CRM'],                       # Bourreau — conclure
    'peripheral': ['Point of Sale', 'Marketing'],         # Vitesse — tempo
    'display':    ['Accounting', 'Purchase'],             # Précision — chiffres
    'tech':       ['Inventory', 'Manufacturing'],         # Blindage — opérations
    'module':     ['Website', 'Productivity'],            # Arcane — digital
    'desk':       ['Human Resources', 'Project', 'General'],  # Épines — back-office
}


class SpeedrunProfileClass(models.Model):
    _inherit = 'speedrun.profile'

    # Coin-upgraded class levels (one per element) — strengthen the passive.
    class_level_peripheral = fields.Integer(default=0)
    class_level_display = fields.Integer(default=0)
    class_level_badge = fields.Integer(default=0)
    class_level_module = fields.Integer(default=0)
    class_level_tech = fields.Integer(default=0)
    class_level_desk = fields.Integer(default=0)

    # Cached domain rating (0-100) per class, from the per-task percentiles.
    class_rating_peripheral = fields.Integer(default=0)
    class_rating_display = fields.Integer(default=0)
    class_rating_badge = fields.Integer(default=0)
    class_rating_module = fields.Integer(default=0)
    class_rating_tech = fields.Integer(default=0)
    class_rating_desk = fields.Integer(default=0)

    # ------------------------------------------------------------------
    # Ratings (percentile of best time, aggregated by domain then class)
    # ------------------------------------------------------------------
    def _percentile_for_task(self, task_id, my_time):
        """Percentile of a best time for a task (100 = record/fastest)."""
        if not my_time:
            return 0.0
        Score = self.env['speedrun.task.score'].sudo()
        total = Score.search_count([('task_id', '=', task_id), ('best_time_ms', '>', 0)])
        if total <= 1:
            return 100.0
        slower_or_equal = Score.search_count([
            ('task_id', '=', task_id), ('best_time_ms', '>=', my_time)])
        return 100.0 * slower_or_equal / total

    def _domain_rating(self, category_names):
        """Average per-task percentile over the player's scores in these categories."""
        self.ensure_one()
        groups = self.env['speedrun.task.group'].sudo().search(
            [('name', 'in', category_names)])
        task_ids = groups.task_ids.ids
        if not task_ids:
            return 0.0
        scores = self.env['speedrun.task.score'].sudo().search([
            ('user_id', '=', self.user_id.id),
            ('task_id', 'in', task_ids),
            ('best_time_ms', '>', 0),
        ])
        if not scores:
            return 0.0
        vals = [self._percentile_for_task(s.task_id.id, s.best_time_ms) for s in scores]
        return sum(vals) / len(vals)

    def _recompute_class_ratings(self):
        """Refresh the cached domain rating of each class for these profiles."""
        for p in self:
            vals = {}
            for el, cats in ELEMENT_CATEGORIES.items():
                vals['class_rating_%s' % el] = round(p._domain_rating(cats))
            p.write(vals)

    # ------------------------------------------------------------------
    # Passive power (fed into the battle engine)
    # ------------------------------------------------------------------
    def _passive_power(self, element=None):
        """Passive strength multiplier for an element (>= 1.0).

        Combines the coin-upgraded class level and the domain rating. Only the
        magnitude of the element's passive is affected (no raw stats).
        """
        self.ensure_one()
        el = element or self.combat_element
        if not el or el not in ELEMENT_CATEGORIES:
            return 1.0
        level = getattr(self, 'class_level_%s' % el, 0) or 0
        rating = getattr(self, 'class_rating_%s' % el, 0) or 0
        return 1.0 + CLASS_LEVEL_STEP * level + DOMAIN_MAX_BONUS * (rating / 100.0)

    # ------------------------------------------------------------------
    # Upgrade & payload
    # ------------------------------------------------------------------
    def _upgrade_class(self, element):
        """Spend coins to raise a class level by one (passive-only bonus)."""
        self.ensure_one()
        if element not in ELEMENT_CATEGORIES:
            return {'error': 'Classe inconnue.'}
        fname = 'class_level_%s' % element
        level = getattr(self, fname)
        if level >= CLASS_LEVEL_MAX:
            return {'error': 'Niveau de classe maximum atteint (%d).' % CLASS_LEVEL_MAX}
        cost = CLASS_UPGRADE_BASE * (level + 1)
        if self.coins < cost:
            return {'error': "Pas assez de pièces : %d 💰 requises (vous en avez %d)." % (
                cost, self.coins), 'coins': self.coins, 'need_coins': cost}
        self._add_coins(-cost)
        self.write({fname: level + 1})
        return {'success': True, 'element': element, 'level': level + 1,
                'coins': self.coins, 'passive_power': round(self._passive_power(element), 2)}

    def _class_info_payload(self, recompute=True):
        """Full class overview for the frontend."""
        self.ensure_one()
        if recompute:
            self._recompute_class_ratings()
        classes = []
        for el in ELEMENTS:
            meta = ELEMENT_META.get(el, {})
            level = getattr(self, 'class_level_%s' % el)
            rating = getattr(self, 'class_rating_%s' % el)
            classes.append({
                'element': el,
                'icon': meta.get('icon', ''),
                'label': meta.get('label', el),
                'passive': meta.get('passive', ''),
                'passive_desc': meta.get('passive_desc', ''),
                'categories': ELEMENT_CATEGORIES.get(el, []),
                'level': level,
                'max_level': CLASS_LEVEL_MAX,
                'rating': rating,
                'passive_power': round(self._passive_power(el), 2),
                'next_cost': CLASS_UPGRADE_BASE * (level + 1) if level < CLASS_LEVEL_MAX else None,
                'is_active': el == self.combat_element,
            })
        return {'coins': self.coins, 'classes': classes}
