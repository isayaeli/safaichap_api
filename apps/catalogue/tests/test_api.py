from unittest import mock

from django.core.management import call_command
from django.test import TestCase
from rest_framework.test import APIClient

from apps.catalogue.models import Itinerary
from apps.core.tests.factories import make_fx, make_itinerary, make_user

ITINERARY_KEYS = {
    'uuid', 'title', 'slug', 'summary', 'destinations', 'duration_days', 'accommodation_level', 'days',
    'inclusions', 'exclusions', 'images', 'operator_uuid', 'operator_name', 'operator_lead_time_days',
    'min_group_size', 'max_group_size', 'is_active', 'pricing', 'display_price', 'display_currency',
}
PRICING_KEYS = {'base_currency', 'resident_adult', 'resident_child', 'non_resident_adult', 'non_resident_child',
                'seasonal_adjustments'}


class CatalogueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command('seed_catalogue', stdout=mock.MagicMock())

    def setUp(self):
        self.user = make_user(residency=None, preferred_currency=None)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_list_is_paginated_with_results_key(self):
        res = self.client.get('/api/itineraries/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(set(res.data), {'count', 'next', 'previous', 'results'})
        self.assertEqual(res.data['count'], 6)
        item = res.data['results'][0]
        self.assertEqual(set(item), ITINERARY_KEYS)
        self.assertEqual(set(item['pricing']), PRICING_KEYS)
        self.assertEqual(item['title'], '3-Day Serengeti & Ngorongoro')  # featured first
        self.assertEqual(item['destinations'], ['Serengeti', 'Ngorongoro'])
        self.assertEqual(item['operator_lead_time_days'], 14)

    def test_display_price_defaults_and_params(self):
        serengeti = Itinerary.objects.get(slug='3-day-serengeti-ngorongoro')
        url = f'/api/itineraries/{serengeti.uuid}/'
        default = self.client.get(url).data  # non_resident / USD
        self.assertEqual((default['display_price'], default['display_currency']), (128000, 'USD'))
        tzs = self.client.get(url + '?residency=resident&currency=TZS').data
        self.assertEqual((tzs['display_price'], tzs['display_currency']), (1170000, 'TZS'))

        self.user.residency, self.user.preferred_currency = 'resident', 'TZS'
        self.user.save()
        self.assertEqual(self.client.get(url).data['display_price'], 1170000)

    def test_filters(self):
        def titles(qs):
            return {i['title'] for i in self.client.get('/api/itineraries/' + qs).data['results']}

        self.assertEqual(titles('?search=zanzibar'), {'Zanzibar Beach + Mikumi'})
        self.assertEqual(titles('?destination=Ruaha'), {'Nyerere & Ruaha Southern Circuit'})
        self.assertEqual(titles('?min_days=5'), {'Zanzibar Beach + Mikumi', '7-Day Great Migration Luxury Safari'})
        self.assertEqual(titles('?max_days=1'), {'Kilimanjaro Day Hike & Materuni Falls'})
        self.assertEqual(titles('?accommodation_level=luxury'), {'7-Day Great Migration Luxury Safari'})
        # non_resident/USD: Kilimanjaro hike is TSh 520,000 → $200.00
        self.assertIn('Kilimanjaro Day Hike & Materuni Falls', titles('?max_price=20000'))
        self.assertNotIn('7-Day Great Migration Luxury Safari', titles('?max_price=20000'))
        self.assertEqual(self.client.get('/api/itineraries/?month=13').status_code, 400)

    def test_destinations_plain_array(self):
        res = self.client.get('/api/itineraries/destinations/')
        self.assertEqual(len(res.data), 9)
        self.assertEqual(set(res.data[0]), {'name', 'region', 'image'})

    def test_unknown_itinerary_404(self):
        self.assertEqual(self.client.get('/api/itineraries/00000000-0000-0000-0000-000000000000/').status_code, 404)

    def test_wishlist_idempotent(self):
        itinerary = Itinerary.objects.get(slug='kilimanjaro-day-hike')
        url = f'/api/users/wishlist/{itinerary.uuid}/'
        self.assertEqual(self.client.post(url).data, {'message': 'Saved to wishlist'})
        self.assertEqual(self.client.post(url).status_code, 200)
        items = self.client.get('/api/users/wishlist/').data
        self.assertEqual([i['slug'] for i in items], ['kilimanjaro-day-hike'])
        self.assertEqual(self.client.delete(url).data, {'message': 'Removed from wishlist'})
        self.assertEqual(self.client.delete(url).status_code, 200)
        self.assertEqual(self.client.get('/api/users/wishlist/').data, [])


class SeedTests(TestCase):
    def test_seed_is_idempotent(self):
        call_command('seed_catalogue', stdout=mock.MagicMock())
        call_command('seed_catalogue', stdout=mock.MagicMock())
        self.assertEqual(Itinerary.objects.count(), 6)
        serengeti = Itinerary.objects.get(slug='3-day-serengeti-ngorongoro')
        self.assertEqual(serengeti.pricing.seasonal_adjustments.count(), 9)
        self.assertEqual(serengeti.days.count(), 3)
