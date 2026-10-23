from django.test import TestCase
from rest_framework.test import APIClient

from apps.core.choices import NotificationType
from apps.core.tests.factories import make_user
from apps.notifications.models import Notification


class NotificationTests(TestCase):
    def setUp(self):
        self.user = make_user()
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def _make(self, user):
        return Notification.objects.create(user=user, title='Paid', message='Thanks',
                                           type=NotificationType.PAYMENT_SUCCESS)

    def test_delete_own_notification(self):
        n = self._make(self.user)
        res = self.client.delete(f'/api/notifications/{n.uuid}/')
        self.assertEqual(res.status_code, 204)
        self.assertFalse(Notification.objects.filter(pk=n.pk).exists())

    def test_cannot_delete_other_users_notification(self):
        other = self._make(make_user(username='uid-2', phone_number='+255700000002'))
        res = self.client.delete(f'/api/notifications/{other.uuid}/')
        self.assertEqual(res.status_code, 404)
        self.assertTrue(Notification.objects.filter(pk=other.pk).exists())
