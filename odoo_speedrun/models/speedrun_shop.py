import random

from odoo import api, fields, models

# Number of equipment items offered each day (same for everyone).
SHOP_ITEMS_PER_DAY = 6


class SpeedrunShopDay(models.Model):
    _name = 'speedrun.shop.day'
    _description = 'Daily Equipment Shop'
    _order = 'date desc'

    date = fields.Date(required=True, index=True, default=fields.Date.today)
    item_ids = fields.Many2many(
        'speedrun.equipment',
        'speedrun_shop_day_item_rel', 'shop_id', 'equipment_id',
        string='Offered Items',
    )
    purchase_ids = fields.One2many('speedrun.shop.purchase', 'shop_id', string='Purchases')

    _unique_date = models.Constraint('UNIQUE(date)', 'Only one shop per day.')

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------
    @api.model
    def _get_or_create_today(self):
        """Return today's shop, creating (and stocking) it if needed.

        The selection is generated once and stored, so every player sees the
        exact same shop for the whole day.
        """
        today = fields.Date.today()
        shop = self.sudo().search([('date', '=', today)], limit=1)
        if not shop:
            items = self._pick_items()
            shop = self.sudo().create({
                'date': today,
                'item_ids': [(6, 0, items.ids)],
            })
        return shop

    @api.model
    def _pick_items(self):
        """Pick the day's line-up: a spread across rarities when possible."""
        Equipment = self.env['speedrun.equipment'].sudo()
        chosen = self.env['speedrun.equipment']
        # Try to guarantee some variety across rarities.
        for rarity in ('legendary', 'epic', 'rare', 'common'):
            pool = Equipment.search([('rarity', '=', rarity)])
            if pool:
                chosen |= Equipment.browse(random.choice(pool.ids))
        # Fill up the rest with random distinct items.
        remaining = Equipment.search([('id', 'not in', chosen.ids)])
        random.shuffle(remaining_ids := remaining.ids)
        for eid in remaining_ids:
            if len(chosen) >= SHOP_ITEMS_PER_DAY:
                break
            chosen |= Equipment.browse(eid)
        return chosen[:SHOP_ITEMS_PER_DAY]

    # ------------------------------------------------------------------
    # Purchase flow
    # ------------------------------------------------------------------
    def _my_purchase(self, user):
        self.ensure_one()
        return self.sudo().purchase_ids.filtered(lambda p: p.user_id.id == user.id)

    def _buy(self, equipment_id):
        """Buy one item from today's shop for the current user (once per day)."""
        self.ensure_one()
        user = self.env.user
        profile = self.env['speedrun.profile'].sudo()._get_or_create(user)
        if self._my_purchase(user):
            return {'error': "Vous avez déjà acheté un équipement aujourd'hui. Revenez demain !"}
        equipment = self.env['speedrun.equipment'].sudo().browse(int(equipment_id)).exists()
        if not equipment or equipment.id not in self.item_ids.ids:
            return {'error': "Cet article n'est pas en vente aujourd'hui."}
        price = equipment._shop_price()
        if profile.coins < price:
            return {
                'error': f"Pas assez de pièces : {price} 💰 requises (vous en avez {profile.coins}).",
                'need_coins': price,
                'coins': profile.coins,
            }
        profile._add_coins(-price)
        profile._grant_equipment(equipment)
        self.sudo().env['speedrun.shop.purchase'].create({
            'shop_id': self.id,
            'user_id': user.id,
            'equipment_id': equipment.id,
            'price_paid': price,
        })
        return {
            'success': True,
            'coins': profile.coins,
            'equipment': {
                'id': equipment.id,
                'name': equipment.name,
                'rarity': equipment.rarity,
                'icon': equipment.icon or '',
                'category': equipment.category or '',
                'description': equipment.description or '',
            },
        }

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------
    def _get_info(self, user=None):
        self.ensure_one()
        user = user or self.env.user
        profile = self.env['speedrun.profile'].sudo()._get_or_create(user)
        purchase = self._my_purchase(user)
        owned_ids = set(profile.equipment_collection_ids.mapped('equipment_id').ids)
        return {
            'date': fields.Date.to_string(self.date),
            'coins': profile.coins,
            'purchased_today': bool(purchase),
            'purchased_equipment_id': purchase.equipment_id.id if purchase else None,
            'items': [{
                'id': e.id,
                'name': e.name,
                'rarity': e.rarity,
                'icon': e.icon or '',
                'category': e.category or '',
                'description': e.description or '',
                'price': e._shop_price(),
                'owned': e.id in owned_ids,
                'stats': {
                    'hp': e.stat_hp, 'atk': e.stat_atk, 'def': e.stat_def,
                    'spd': e.stat_spd, 'crit': e.stat_crit,
                },
            } for e in self.item_ids],
        }


class SpeedrunShopPurchase(models.Model):
    _name = 'speedrun.shop.purchase'
    _description = 'Daily Shop Purchase'
    _order = 'create_date desc'

    shop_id = fields.Many2one('speedrun.shop.day', required=True, ondelete='cascade', index=True)
    user_id = fields.Many2one('res.users', required=True, index=True)
    equipment_id = fields.Many2one('speedrun.equipment', required=True, ondelete='cascade')
    price_paid = fields.Integer()

    _unique_purchase = models.Constraint(
        'UNIQUE(shop_id, user_id)',
        'One equipment purchase per player per day.',
    )
