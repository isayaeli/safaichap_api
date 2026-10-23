from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.tests.factories import make_user
from apps.userauth.models import DeviceToken, KycDocument, UserAccount

USER_KEYS = {'uuid', 'full_name', 'phone_number', 'email', 'residency', 'preferred_currency', 'country',
             'kyc_status', 'notifications_enabled', 'created_at'}


class FirebaseAuthTests(TestCase):
    def test_missing_token_is_401(self):
        self.assertEqual(APIClient().get('/api/users/me/').status_code, 401)

    def test_invalid_token_is_401(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer bad-token')
        with mock.patch('apps.userauth.authentication.auth.verify_id_token', side_effect=ValueError('expired')):
            res = client.get('/api/users/me/')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data['detail'], 'Your session has expired. Please sign in again.')

    def test_first_call_creates_profile(self):
        client = APIClient()
        client.credentials(HTTP_AUTHORIZATION='Bearer good-token')
        decoded = {'uid': 'firebase-uid-1', 'phone_number': '+255712345678'}
        with mock.patch('apps.userauth.authentication.auth.verify_id_token', return_value=decoded):
            res = client.get('/api/users/me/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(set(res.data), USER_KEYS)
        self.assertEqual(res.data['phone_number'], '+255712345678')
        self.assertIsNone(res.data['full_name'])
        self.assertIsNone(res.data['residency'])
        self.assertEqual(res.data['country'], 'TZ')
        self.assertEqual(res.data['kyc_status'], 'not_required')
        self.assertTrue(UserAccount.objects.filter(username='firebase-uid-1').exists())


class ProfileTests(TestCase):
    def setUp(self):
        self.user = make_user(full_name=None, residency=None, preferred_currency=None)
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_patch_profile(self):
        res = self.client.patch('/api/users/me/', {'full_name': 'Asha Mushi', 'residency': 'resident',
                                                   'preferred_currency': 'TZS'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['residency'], 'resident')
        res = self.client.patch('/api/users/me/', {'residency': 'alien'}, format='json')
        self.assertEqual(res.status_code, 400)
        self.assertIn('residency', res.data)

    def test_device_upsert_reassigns(self):
        other = make_user('uid-2')
        DeviceToken.objects.create(user=other, token='tok-1', platform='ios')
        res = self.client.post('/api/users/devices/', {'token': 'tok-1', 'platform': 'android'}, format='json')
        self.assertEqual(res.data, {'ok': True})
        device = DeviceToken.objects.get(token='tok-1')
        self.assertEqual((device.user, device.platform), (self.user, 'android'))

    def test_kyc_is_encrypted_and_pending(self):
        res = self.client.post('/api/users/kyc/', {'document_type': 'nida',
                                                   'document_number': '1234'}, format='json')
        self.assertEqual(res.status_code, 400)
        res = self.client.post('/api/users/kyc/', {'document_type': 'passport', 'document_number': 'ab123456'},
                               format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['kyc_status'], 'pending')
        doc = KycDocument.objects.get()
        self.assertEqual(doc.document_number, 'AB123456')
        from django.db import connection
        with connection.cursor() as cursor:
            cursor.execute('SELECT document_number FROM userauth_kycdocument')
            stored = cursor.fetchone()[0]
        self.assertNotIn('AB123456', stored)
