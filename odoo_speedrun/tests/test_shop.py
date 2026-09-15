from odoo.tests.common import tagged

from .common import SpeedrunCommon


@tagged('post_install', '-at_install')
class TestShop(SpeedrunCommon):

    def test_daily_shop_is_shared_and_stocked(self):
        Shop = self.env['speedrun.shop.day']
        shop1 = Shop._get_or_create_today()
        shop2 = Shop._get_or_create_today()
        self.assertEqual(shop1, shop2)  # same shop for everyone that day
        self.assertTrue(shop1.item_ids)

    def test_buy_debits_coins_and_grants_item(self):
        shop = self.env['speedrun.shop.day']._get_or_create_today()
        profile = self.env['speedrun.profile']._get_or_create(self.user_a)
        profile.coins = 100000
        item = min(shop.item_ids, key=lambda e: e._shop_price())
        price = item._shop_price()
        before = profile.coins
        result = shop.with_user(self.user_a)._buy(item.id)
        self.assertTrue(result.get('success'))
        self.assertEqual(profile.coins, before - price)
        owned = self.env['speedrun.player.equipment'].search([
            ('profile_id', '=', profile.id), ('equipment_id', '=', item.id)])
        self.assertTrue(owned)

    def test_one_purchase_per_day(self):
        shop = self.env['speedrun.shop.day']._get_or_create_today()
        profile = self.env['speedrun.profile']._get_or_create(self.user_a)
        profile.coins = 100000
        shop.with_user(self.user_a)._buy(shop.item_ids[0].id)
        second = shop.with_user(self.user_a)._buy(shop.item_ids[0].id)
        self.assertTrue(second.get('error'))

    def test_not_enough_coins(self):
        shop = self.env['speedrun.shop.day']._get_or_create_today()
        profile = self.env['speedrun.profile']._get_or_create(self.user_a)
        profile.coins = 0
        result = shop.with_user(self.user_a)._buy(shop.item_ids[0].id)
        self.assertTrue(result.get('error'))
