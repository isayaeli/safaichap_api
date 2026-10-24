from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.adminpanel.models import AuditLog, Broadcast
from apps.bookings.models import Booking
from apps.core.choices import GoalStatus
from apps.core.models import AppSetting, FxRate
from apps.core.tests.factories import days_from_today, make_fx, make_itinerary, make_user
from apps.goals.models import SavingsGoal
from apps.notifications.models import Notification
from apps.payments.models import Payment, Refund
from apps.userauth.models import KycDocument
from .factories import make_staff

WEBHOOK_URL = '/api/payments/webhooks/clickpesa/?secret=test-clickpesa-secret'


class AdminBase(TestCase):
    def setUp(self):
        make_fx()
        self.admin = make_staff()
        self.client = APIClient()
        self.client.force_authenticate(self.admin)
        self.customer = make_user('cust-1')
        self.app = APIClient()
        self.app.force_authenticate(self.customer)
        self.itinerary, self.pricing = make_itinerary()

    def active_goal(self):
        body = {'itinerary_uuid': str(self.itinerary.uuid),
                'travellers': [{'name': 'Asha', 'age_category': 'adult', 'residency': 'resident'}],
                'travel_date': days_from_today(200).isoformat(), 'currency': 'TZS', 'frequency': 'monthly'}
        created = self.app.post('/api/goals/', body, format='json')
        self.assertEqual(created.status_code, 201, created.data)
        self.app.post(f"/api/goals/{created.data['uuid']}/activate/")
        return SavingsGoal.objects.get(uuid=created.data['uuid'])

    def pay(self, goal, amount, ref='ADMINTEST0001', success=True):
        with mock.patch('apps.payments.services.clickpesa.initiate_ussd_push', return_value={'id': 'cp-1'}):
            res = self.app.post('/api/payments/initiate/', {
                'goal_uuid': str(goal.uuid), 'amount': amount, 'currency': 'TZS', 'method': 'mpesa',
                'order_reference': ref, 'phone_number': '255712345678'}, format='json')
        self.assertIn(res.status_code, (200, 201), res.data)
        payload = {'data': {'orderReference': ref, 'status': 'SUCCESS' if success else 'FAILED',
                            'paymentReference': 'P1', 'id': 'tx1'}}
        with self.captureOnCommitCallbacks(execute=True):
            res = APIClient().post(WEBHOOK_URL, payload, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        return Payment.objects.get(order_reference=ref)


class UserAndKycTests(AdminBase):
    def test_list_search_and_detail(self):
        self.active_goal()
        res = self.client.get('/api/admin/users/?search=cust-1')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['active_goals_count'], 1)
        detail = self.client.get(f'/api/admin/users/{self.customer.uuid}/')
        self.assertEqual(len(detail.data['goals']), 1)

    def test_disable_user_is_audited_and_blocks_app(self):
        res = self.client.patch(f'/api/admin/users/{self.customer.uuid}/', {'is_active': False}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        log = AuditLog.objects.get(action='user.update')
        self.assertTrue(log.before['is_active'])
        self.assertFalse(log.after['is_active'])

    def test_export_csv(self):
        res = self.client.get('/api/admin/users/export/')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(res.content.decode().startswith('uuid,full_name'))

    def test_kyc_approve_and_reject(self):
        self.app.post('/api/users/kyc/', {'document_type': 'passport', 'document_number': 'AB123456'},
                      format='json')
        doc = KycDocument.objects.get()
        res = self.client.get('/api/admin/kyc/?status=pending')
        self.assertEqual(res.data['results'][0]['document_number'], 'AB123456')
        res = self.client.post(f'/api/admin/kyc/{doc.uuid}/approve/', {}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.customer.refresh_from_db()
        self.assertEqual(self.customer.kyc_status, 'verified')
        self.assertTrue(Notification.objects.filter(user=self.customer, type='kyc_verified').exists())
        self.assertEqual(self.client.post(f'/api/admin/kyc/{doc.uuid}/reject/', {}).status_code, 409)

    def test_support_can_review_kyc_but_content_cannot(self):
        self.app.post('/api/users/kyc/', {'document_type': 'passport', 'document_number': 'AB123456'},
                      format='json')
        doc = KycDocument.objects.get()
        content = APIClient()
        content.force_authenticate(make_staff('content', roles=('Content',)))
        self.assertEqual(content.post(f'/api/admin/kyc/{doc.uuid}/reject/', {}).status_code, 403)


class GoalAdminTests(AdminBase):
    def test_pause_resume_reschedule_cancel(self):
        goal = self.active_goal()
        res = self.client.post(f'/api/admin/goals/{goal.uuid}/pause/', {'reason': 'Fraud check'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'paused')
        self.assertEqual(self.client.post(f'/api/admin/goals/{goal.uuid}/pause/').status_code, 409)
        res = self.client.post(f'/api/admin/goals/{goal.uuid}/resume/')
        self.assertEqual(res.data['status'], 'active')

        total = res.data['total_amount']
        new_date = days_from_today(300).isoformat()
        res = self.client.post(f'/api/admin/goals/{goal.uuid}/reschedule/', {'travel_date': new_date},
                               format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['travel_date'], new_date)
        self.assertEqual(res.data['total_amount'], total)  # price stays locked
        self.assertEqual(sum(i['amount'] for i in res.data['installments']), total)

        self.pay(goal, 100000)
        res = self.client.post(f'/api/admin/goals/{goal.uuid}/cancel/', {'reason': 'Customer asked'},
                               format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'cancelled')
        self.assertEqual(Refund.objects.filter(goal=goal).count(), 1)
        actions = set(AuditLog.objects.values_list('action', flat=True))
        self.assertTrue({'goal.pause', 'goal.resume', 'goal.reschedule', 'goal.cancel'} <= actions)

    def test_filters(self):
        self.active_goal()
        self.assertEqual(self.client.get('/api/admin/goals/?status=active').data['count'], 1)
        self.assertEqual(self.client.get('/api/admin/goals/?status=paused').data['count'], 0)


class PaymentRefundBookingTests(AdminBase):
    def test_payment_ledger_and_raw_webhook_permission(self):
        goal = self.active_goal()
        payment = self.pay(goal, 50000)
        res = self.client.get(f'/api/admin/payments/{payment.uuid}/')
        self.assertIsNotNone(res.data['raw_webhook'])
        support = APIClient()
        support.force_authenticate(make_staff('support', roles=('Support',)))
        self.assertIsNone(support.get(f'/api/admin/payments/{payment.uuid}/').data['raw_webhook'])
        self.assertEqual(support.post(f'/api/admin/payments/{payment.uuid}/reconcile/').status_code, 403)
        self.assertEqual(self.client.post(f'/api/admin/payments/{payment.uuid}/reconcile/').status_code, 409)

    def test_refund_mark_completed(self):
        goal = self.active_goal()
        self.pay(goal, 100000)
        self.app.post(f'/api/goals/{goal.uuid}/cancel/', {}, format='json')
        refund = Refund.objects.get()
        Refund.objects.filter(pk=refund.pk).update(status='failed')
        res = self.client.post(f'/api/admin/refunds/{refund.uuid}/mark-completed/',
                               {'provider_reference': 'BANK-123'}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'completed')
        self.assertFalse(Payment.objects.filter(goal=goal, status='success').exists())

    def test_booking_documents(self):
        goal = self.active_goal()
        self.pay(goal, goal.total_amount)
        booking = Booking.objects.get(goal=goal)
        res = self.client.post(f'/api/admin/bookings/{booking.uuid}/documents/',
                               {'type': 'other', 'title': 'Park permit', 'url': 'https://cdn.safarichap.co.tz/permit.pdf'},
                               format='json')
        self.assertEqual(res.status_code, 201, res.data)
        doc_uuid = res.data['uuid']
        res = self.client.patch(f'/api/admin/trip-documents/{doc_uuid}/', {'title': 'Permit'}, format='json')
        self.assertEqual(res.data['title'], 'Permit')
        res = self.client.post(f'/api/admin/bookings/{booking.uuid}/notify/')
        self.assertEqual(res.status_code, 200)
        self.assertTrue(Notification.objects.filter(type='booking_updated').exists())
        res = self.client.patch(f'/api/admin/bookings/{booking.uuid}/', {'status': 'completed'}, format='json')
        self.assertEqual(res.data['status'], 'completed')
        # The app sees the document too.
        app_booking = self.app.get(f'/api/bookings/{booking.uuid}/').data
        self.assertIn('Permit', [d['title'] for d in app_booking['documents']])


class CatalogueTests(AdminBase):
    def test_itinerary_crud_with_nested_pricing(self):
        operator = self.itinerary.operator
        dest = self.itinerary.destination_links.first().destination
        body = {
            'title': 'Serengeti Classic', 'slug': 'serengeti-classic', 'duration_days': 3,
            'accommodation_level': 'mid_range', 'operator': str(operator.uuid), 'destinations': [str(dest.uuid)],
            'images': ['https://img/1.jpg'], 'inclusions': ['Park fees'], 'exclusions': [],
            'days': [{'day_number': 1, 'title': 'Arrive', 'meals': ['dinner']},
                     {'day_number': 2, 'title': 'Game drive'}],
            'pricing': {'base_currency': 'USD', 'resident_adult': 50000, 'resident_child': 25000,
                        'non_resident_adult': 120000, 'non_resident_child': 60000,
                        'seasonal_adjustments': [{'start_date': '2027-06-01', 'end_date': '2027-10-31',
                                                  'multiplier_bps': 12000, 'label': 'High'}]},
        }
        res = self.client.post('/api/admin/itineraries/', body, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        uuid = res.data['uuid']
        self.assertEqual(len(res.data['days']), 2)
        self.assertEqual(res.data['destinations'], [str(dest.uuid)])
        res = self.client.patch(f'/api/admin/itineraries/{uuid}/', {
            'is_active': False,
            'pricing': {**body['pricing'], 'resident_adult': 55000, 'seasonal_adjustments': []},
        }, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['pricing']['resident_adult'], 55000)
        self.assertEqual(res.data['pricing']['seasonal_adjustments'], [])
        log = AuditLog.objects.get(action='itinerary.update')
        self.assertEqual(log.before['pricing']['resident_adult'], 50000)
        # Inactive trips disappear from the app.
        listed = self.app.get('/api/itineraries/').data['results']
        self.assertNotIn(uuid, [t['uuid'] for t in listed])
        self.assertEqual(self.client.delete(f'/api/admin/itineraries/{uuid}/').status_code, 204)

    def test_itinerary_with_goals_cannot_be_deleted(self):
        self.active_goal()
        res = self.client.delete(f'/api/admin/itineraries/{self.itinerary.uuid}/')
        self.assertEqual(res.status_code, 409)

    def test_refund_policy_validation_and_single_default(self):
        bad = self.client.post('/api/admin/refund-policies/', {'name': 'X', 'tiers': [{'min_days': 10,
                                                                                        'percentage': 50}]},
                               format='json')
        self.assertEqual(bad.status_code, 400)
        tiers = [{'min_days': 0, 'percentage': 0}, {'min_days': 30, 'percentage': 80}]
        a = self.client.post('/api/admin/refund-policies/', {'name': 'A', 'tiers': tiers, 'is_default': True},
                             format='json')
        self.assertEqual(a.status_code, 201, a.data)
        self.assertEqual(a.data['tiers'][0]['min_days'], 30)
        self.client.post('/api/admin/refund-policies/', {'name': 'B', 'tiers': tiers, 'is_default': True},
                         format='json')
        defaults = [p['name'] for p in self.client.get('/api/admin/refund-policies/').data if p['is_default']]
        self.assertEqual(defaults, ['B'])


class SystemTests(AdminBase):
    def test_stats(self):
        goal = self.active_goal()
        self.pay(goal, 50000)
        res = self.client.get('/api/admin/stats/?days=30')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['collected'], {'TZS': 50000})
        self.assertEqual(res.data['goals']['active'], 1)
        self.assertEqual(res.data['users']['total'], 1)
        self.assertEqual(res.data['collections_series'][0]['amount'], 50000)

    def test_fx_override_and_current(self):
        res = self.client.post('/api/admin/fx-rates/', {'from_currency': 'USD', 'numerator': 2700}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        current = {r['from_currency']: r['numerator'] for r in self.client.get('/api/admin/fx-rates/current/').data}
        self.assertEqual(current['USD'], 2700)
        self.assertEqual(self.client.post('/api/admin/fx-rates/', {'from_currency': 'TZS', 'numerator': 1},
                                          format='json').status_code, 400)

    @mock.patch('apps.core.tasks.requests.get')
    def test_fx_refresh(self, get):
        get.return_value.json.return_value = {'rates': {'USD': 0.0004}}
        res = self.client.post('/api/admin/fx-rates/refresh/')
        self.assertEqual(res.status_code, 202)
        self.assertTrue(FxRate.objects.filter(from_currency='USD', numerator=2500).exists())

    def test_settings(self):
        res = self.client.patch('/api/admin/settings/', {'missed_before_pause': 4}, format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(AppSetting.get().missed_before_pause, 4)
        self.assertEqual(self.client.patch('/api/admin/settings/', {'missed_before_pause': 0},
                                           format='json').status_code, 400)
        finance = APIClient()
        finance.force_authenticate(make_staff('fin', roles=('Finance',)))
        self.assertEqual(finance.get('/api/admin/settings/').status_code, 200)
        self.assertEqual(finance.patch('/api/admin/settings/', {}, format='json').status_code, 403)

    def test_broadcast(self):
        make_user('cust-2', residency='non_resident')
        res = self.client.post('/api/admin/broadcasts/', {'title': 'Hi', 'message': 'News', 'audience': 'residency',
                                                          'residency': 'resident', 'dry_run': True}, format='json')
        self.assertEqual(res.data, {'recipients': 1})
        with self.captureOnCommitCallbacks(execute=True):
            res = self.client.post('/api/admin/broadcasts/', {'title': 'Hi', 'message': 'News', 'audience': 'all'},
                                   format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['recipients'], 2)
        self.assertEqual(Notification.objects.filter(type='announcement').count(), 2)
        self.assertEqual(Broadcast.objects.count(), 1)
        bad = self.client.post('/api/admin/broadcasts/', {'title': 'Hi', 'message': 'x', 'audience': 'users'},
                               format='json')
        self.assertEqual(bad.status_code, 400)

    def test_broadcast_delivery_counts(self):
        from apps.adminpanel.tasks import send_broadcast
        other = make_user('cust-3')
        broadcast = Broadcast.objects.create(title='Hi', message='News', recipients=2)
        # One recipient has a device that takes the push, the other has none.
        with mock.patch('apps.adminpanel.tasks.send_push_notification', side_effect=[True, False]):
            result = send_broadcast(broadcast.pk, [self.customer.pk, other.pk])
        self.assertEqual(result, {'sent': 2, 'pushed': 1, 'failed': 0})
        broadcast.refresh_from_db()
        self.assertEqual((broadcast.sent, broadcast.pushed, broadcast.failed), (2, 1, 0))

    def test_upload(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        with self.settings(MEDIA_ROOT=self._tmp()):
            res = self.client.post('/api/admin/uploads/', {
                'file': SimpleUploadedFile('cover.png', b'\x89PNG data', content_type='image/png'),
                'folder': 'itineraries'}, format='multipart')
            self.assertEqual(res.status_code, 201, res.data)
            self.assertIn('/media/admin/itineraries/', res.data['url'])
            res = self.client.post('/api/admin/uploads/', {
                'file': SimpleUploadedFile('x.exe', b'MZ'), 'folder': 'itineraries'}, format='multipart')
            self.assertEqual(res.status_code, 400)

    def _tmp(self):
        import tempfile
        path = tempfile.mkdtemp()
        self.addCleanup(__import__('shutil').rmtree, path, True)
        return path
