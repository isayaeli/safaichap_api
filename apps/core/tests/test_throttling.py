from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from rest_framework.test import APIClient
from rest_framework.throttling import AnonRateThrottle, SimpleRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from apps.core.tests.factories import days_from_today, make_fx, make_itinerary, make_user
from utils.throttling import ScopedWriteRateThrottle

RATES = {
    'user': '6/min', 'anon': '1/min', 'payments': '2/min', 'kyc': '2/min', 'webhooks': '2/min',
    'quotes': '2/min', 'goal_changes': '2/min', 'account': '2/min',
}
WEBHOOK_URL = '/api/payments/webhooks/clickpesa/?secret=test-clickpesa-secret'


class ThrottlingTests(TestCase):
    """Test settings switch throttling off, so these turn the production classes back on with tiny rates."""

    def setUp(self):
        cache.clear()
        for patcher in (
            mock.patch.object(APIView, 'throttle_classes', [UserRateThrottle, AnonRateThrottle,
                                                            ScopedWriteRateThrottle]),
            mock.patch.object(SimpleRateThrottle, 'THROTTLE_RATES', RATES),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        make_fx()
        self.itinerary, _ = make_itinerary()
        self.client = APIClient()
        self.client.force_authenticate(make_user())

    def plan(self):
        return {
            'itinerary_uuid': str(self.itinerary.uuid),
            'travellers': [{'name': 'Asha', 'age_category': 'adult', 'residency': 'resident'}],
            'travel_date': days_from_today(200).isoformat(), 'currency': 'TZS', 'frequency': 'monthly',
        }

    def test_quote_scope_returns_429(self):
        for _ in range(2):
            self.assertEqual(self.client.post('/api/goals/quote/', self.plan(), format='json').status_code, 200)
        self.assertEqual(self.client.post('/api/goals/quote/', self.plan(), format='json').status_code, 429)

    def test_scope_limits_writes_but_not_reads(self):
        for _ in range(2):
            self.assertEqual(self.client.post('/api/goals/', self.plan(), format='json').status_code, 201)
        self.assertEqual(self.client.post('/api/goals/', self.plan(), format='json').status_code, 429)
        self.assertEqual(self.client.get('/api/goals/').status_code, 200)

    def test_global_user_rate(self):
        for _ in range(6):
            self.assertEqual(self.client.get('/api/notifications/').status_code, 200)
        self.assertEqual(self.client.get('/api/itineraries/').status_code, 429)

    def test_webhooks_skip_anon_rate_and_ignore_spoofed_forwarded_for(self):
        # nginx appends the real client IP; whatever the client put before it must not open a new bucket.
        for spoofed in ('1.1.1.1', '2.2.2.2'):
            res = APIClient().post(WEBHOOK_URL, {}, format='json', HTTP_X_FORWARDED_FOR=f'{spoofed}, 5.5.5.5')
            self.assertNotEqual(res.status_code, 429)
        res = APIClient().post(WEBHOOK_URL, {}, format='json', HTTP_X_FORWARDED_FOR='3.3.3.3, 5.5.5.5')
        self.assertEqual(res.status_code, 429)
