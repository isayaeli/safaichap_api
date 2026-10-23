from datetime import timedelta
from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.bookings.models import Booking
from apps.core.choices import GoalStatus, InstallmentStatus
from apps.core.tests.factories import add_season, days_from_today, make_fx, make_itinerary, make_user
from apps.goals.models import SavingsGoal
from apps.goals.services.goals import process_goal_schedule
from apps.notifications.models import Notification
from apps.payments.models import Payment, Refund

GOAL_KEYS = {
    'uuid', 'itinerary_uuid', 'title', 'travellers', 'travel_date', 'pay_by_date', 'currency', 'total_amount',
    'deposit_amount', 'amount_paid', 'frequency', 'installment_amount', 'next_due_date', 'status',
    'consecutive_missed', 'cover_image', 'booking_uuid', 'created_at', 'completed_at', 'installments',
}
INSTALLMENT_KEYS = {'uuid', 'due_date', 'amount', 'amount_paid', 'status', 'is_deposit'}
PAYMENT_KEYS = {
    'uuid', 'goal_uuid', 'goal_title', 'amount', 'currency', 'method', 'phone_number', 'provider_reference',
    'status', 'failure_reason', 'receipt_number', 'checkout_url', 'created_at',
}
BOOKING_KEYS = {
    'uuid', 'goal_uuid', 'itinerary_uuid', 'itinerary_title', 'confirmation_code', 'status', 'travel_date',
    'documents', 'operator_contact', 'created_at',
}
QUOTE_KEYS = {'currency', 'total_amount', 'deposit_amount', 'pay_by_date', 'season_label', 'lines', 'installments'}
CANCEL_KEYS = {'currency', 'amount_paid', 'refund_percentage', 'processing_fee', 'refund_amount', 'policy'}

WEBHOOK_URL = '/api/payments/webhooks/clickpesa/?secret=test-clickpesa-secret'


class GoalFlowBase(TestCase):
    def setUp(self):
        make_fx()
        self.user = make_user()
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.itinerary, self.pricing = make_itinerary()
        self.travel_date = days_from_today(200)

    def plan(self, **overrides):
        body = {
            'itinerary_uuid': str(self.itinerary.uuid),
            'travellers': [{'name': 'Asha', 'age_category': 'adult', 'residency': 'resident'}],
            'travel_date': self.travel_date.isoformat(),
            'currency': 'TZS',
            'frequency': 'monthly',
            'deposit_amount': 0,
        }
        body.update(overrides)
        return body

    def create_active_goal(self, **overrides):
        created = self.client.post('/api/goals/', self.plan(**overrides), format='json')
        self.assertEqual(created.status_code, 201, created.data)
        activated = self.client.post(f"/api/goals/{created.data['uuid']}/activate/")
        self.assertEqual(activated.status_code, 200, activated.data)
        return activated.data

    def initiate(self, goal_uuid, amount, ref='SC1729260000123A7F3', **overrides):
        body = {'goal_uuid': goal_uuid, 'amount': amount, 'currency': 'TZS', 'method': 'mpesa',
                'order_reference': ref, 'phone_number': '255712345678'}
        body.update(overrides)
        with mock.patch('apps.payments.services.clickpesa.initiate_ussd_push', return_value={'id': 'CP123'}):
            return self.client.post('/api/payments/initiate/', body, format='json')

    def webhook(self, ref, status='SUCCESS'):
        payload = {'event': 'PAYMENT RECEIVED', 'data': {'orderReference': ref, 'status': status, 'id': 'CP123',
                                                         'paymentReference': 'MP123456789'}}
        with self.captureOnCommitCallbacks(execute=True):
            return APIClient().post(WEBHOOK_URL, payload, format='json')


class QuoteCreateActivateTests(GoalFlowBase):
    def test_quote_saves_nothing(self):
        res = self.client.post('/api/goals/quote/', self.plan(), format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(set(res.data), QUOTE_KEYS)
        self.assertEqual(res.data['total_amount'], 480000)
        self.assertEqual(sum(i['amount'] for i in res.data['installments']), 480000)
        self.assertFalse(SavingsGoal.objects.exists())

    def test_quote_high_season_tzs(self):
        itinerary, pricing = make_itinerary(base_currency='USD', prices=(45000, 25000, 128000, 72000),
                                            slug='serengeti')
        add_season(pricing, self.travel_date - timedelta(days=5), self.travel_date + timedelta(days=5))
        res = self.client.post('/api/goals/quote/', self.plan(
            itinerary_uuid=str(itinerary.uuid),
            travellers=[{'name': 'Tom', 'age_category': 'adult', 'residency': 'non_resident'}],
        ), format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['total_amount'], 3_993_600)
        self.assertEqual(res.data['season_label'], 'High season (+20%)')

    def test_validation_errors(self):
        cases = [
            (self.plan(travel_date=days_from_today(10).isoformat()), "Travel date is too soon"),
            (self.plan(travellers=[{'name': 'Kid', 'age_category': 'child', 'residency': 'resident'}]),
             "At least one adult must travel."),
            (self.plan(travellers=[{'name': str(i), 'age_category': 'adult', 'residency': 'resident'}
                                   for i in range(7)]), "This trip takes 1–6 travellers."),
            (self.plan(deposit_amount=480000), "Deposit must be less than the total."),
        ]
        for body, message in cases:
            res = self.client.post('/api/goals/quote/', body, format='json')
            self.assertEqual(res.status_code, 400)
            self.assertIn(message, res.data['detail'])

    def test_create_then_activate_locks_price(self):
        created = self.client.post('/api/goals/', self.plan(title='  '), format='json')
        self.assertEqual(created.status_code, 201)
        self.assertEqual(set(created.data), GOAL_KEYS)
        self.assertEqual(created.data['status'], 'draft')
        self.assertEqual(created.data['installments'], [])
        self.assertEqual(created.data['title'], self.itinerary.title)

        activated = self.client.post(f"/api/goals/{created.data['uuid']}/activate/").data
        self.assertEqual(activated['status'], 'active')
        self.assertEqual(set(activated['installments'][0]), INSTALLMENT_KEYS)
        self.assertEqual(sum(i['amount'] for i in activated['installments']), 480000)
        self.assertEqual(activated['next_due_date'], activated['installments'][0]['due_date'])
        self.assertEqual(activated['installment_amount'], activated['installments'][0]['amount'])

        # Later price changes don't touch the goal.
        self.pricing.resident_adult = 999999
        self.pricing.save()
        again = self.client.get(f"/api/goals/{created.data['uuid']}/").data
        self.assertEqual(again['total_amount'], 480000)
        goal = SavingsGoal.objects.get(uuid=created.data['uuid'])
        self.assertEqual((goal.locked_fx_numerator, goal.locked_fx_denominator), (1, 1))
        self.assertEqual(goal.locked_pricing_snapshot['pricing']['resident_adult'], 480000)

        self.assertEqual(self.client.post(f"/api/goals/{created.data['uuid']}/activate/").status_code, 409)

    def test_deposit_is_due_today(self):
        goal = self.create_active_goal(deposit_amount=80000)
        first = goal['installments'][0]
        self.assertTrue(first['is_deposit'])
        self.assertEqual(first['amount'], 80000)
        self.assertEqual(sum(i['amount'] for i in goal['installments']), 480000)

    def test_delete_only_drafts(self):
        draft = self.client.post('/api/goals/', self.plan(), format='json').data
        self.assertEqual(self.client.delete(f"/api/goals/{draft['uuid']}/").status_code, 204)
        active = self.create_active_goal()
        self.assertEqual(self.client.delete(f"/api/goals/{active['uuid']}/").status_code, 409)

    def test_list_and_status_filter(self):
        self.client.post('/api/goals/', self.plan(), format='json')
        self.create_active_goal()
        self.assertEqual(len(self.client.get('/api/goals/').data), 2)
        self.assertEqual(len(self.client.get('/api/goals/?status=active').data), 1)

    def test_ownership_returns_404(self):
        goal = self.create_active_goal()
        other = APIClient()
        other.force_authenticate(make_user('uid-2'))
        for method, url in [
            ('get', f"/api/goals/{goal['uuid']}/"),
            ('post', f"/api/goals/{goal['uuid']}/activate/"),
            ('get', f"/api/goals/{goal['uuid']}/payments/"),
            ('get', f"/api/goals/{goal['uuid']}/cancellation-quote/"),
            ('post', f"/api/goals/{goal['uuid']}/cancel/"),
            ('delete', f"/api/goals/{goal['uuid']}/"),
        ]:
            self.assertEqual(getattr(other, method)(url).status_code, 404, url)
        res = self.initiate(goal['uuid'], 50000)
        payment_uuid = res.data['uuid']
        self.assertEqual(other.get(f"/api/payments/{payment_uuid}/").status_code, 404)
        self.assertEqual(other.get('/api/payments/').data, [])


class PaymentTests(GoalFlowBase):
    def setUp(self):
        super().setUp()
        self.goal = self.create_active_goal()

    def test_initiate_returns_pending_payment(self):
        res = self.initiate(self.goal['uuid'], 50000)
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(set(res.data), PAYMENT_KEYS)
        self.assertEqual(res.data['status'], 'pending')
        self.assertEqual(res.data['goal_title'], self.goal['title'])

    def test_initiate_validation(self):
        cases = [
            ({'amount': 480001}, 400, "Amount is more than the remaining balance."),
            ({'amount': 4999}, 400, "Minimum payment is TZS 5000."),
            ({'currency': 'USD', 'method': 'card'}, 400, "Payments for this goal must be in TZS."),
            ({'method': 'card'}, 400, "TZS goals are paid with mobile money."),
        ]
        for i, (overrides, code, message) in enumerate(cases):
            res = self.initiate(self.goal['uuid'], overrides.pop('amount', 50000), ref=f"REFVAL000{i}", **overrides)
            self.assertEqual(res.status_code, code, res.data)
            self.assertEqual(res.data['detail'], message)
        res = self.initiate(self.goal['uuid'], 50000, ref='REFVAL0009', phone_number='0712345678')
        self.assertEqual(res.status_code, 400)
        self.assertIn('phone_number', res.data)

    def test_full_remaining_below_minimum_is_allowed(self):
        self.initiate(self.goal['uuid'], 477000, ref='REFBIG0001')
        self.webhook('REFBIG0001')
        res = self.initiate(self.goal['uuid'], 3000, ref='REFSMALL01')
        self.assertEqual(res.status_code, 201, res.data)

    def test_duplicate_order_reference_single_charge(self):
        with mock.patch('apps.payments.services.clickpesa.initiate_ussd_push', return_value={}) as push:
            body = {'goal_uuid': self.goal['uuid'], 'amount': 50000, 'currency': 'TZS', 'method': 'mpesa',
                    'order_reference': 'SCDUP00001', 'phone_number': '255712345678'}
            first = self.client.post('/api/payments/initiate/', body, format='json')
            second = self.client.post('/api/payments/initiate/', body, format='json')
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertEqual(first.data['uuid'], second.data['uuid'])
        self.assertEqual(push.call_count, 1)
        self.assertEqual(Payment.objects.count(), 1)

    def test_provider_error_marks_failed(self):
        from utils.exceptions import ProviderError
        body = {'goal_uuid': self.goal['uuid'], 'amount': 50000, 'currency': 'TZS', 'method': 'mpesa',
                'order_reference': 'SCERR00001', 'phone_number': '255712345678'}
        with mock.patch('apps.payments.services.clickpesa.initiate_ussd_push',
                        side_effect=ProviderError('boom', 'Try again later.')):
            res = self.client.post('/api/payments/initiate/', body, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['status'], 'failed')
        self.assertEqual(res.data['failure_reason'], 'Try again later.')

    def test_webhook_requires_secret(self):
        self.initiate(self.goal['uuid'], 50000, ref='SCSEC00001')
        res = APIClient().post('/api/payments/webhooks/clickpesa/',
                               {'data': {'orderReference': 'SCSEC00001', 'status': 'SUCCESS'}}, format='json')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(Payment.objects.get().status, 'pending')

    def test_duplicate_webhook_applied_once(self):
        self.initiate(self.goal['uuid'], 150000, ref='SCWH000001')
        self.assertEqual(self.webhook('SCWH000001').status_code, 200)
        self.assertEqual(self.webhook('SCWH000001').status_code, 200)
        goal = SavingsGoal.objects.get(uuid=self.goal['uuid'])
        self.assertEqual(goal.amount_paid, 150000)
        payment = Payment.objects.get()
        self.assertEqual(payment.status, 'success')
        self.assertTrue(payment.receipt_number.startswith('SC-RCPT-'))
        self.assertEqual(Notification.objects.filter(type='payment_success').count(), 1)

        data = self.client.get(f"/api/goals/{self.goal['uuid']}/").data
        statuses = [i['status'] for i in data['installments']]
        self.assertEqual(data['installments'][0]['amount'], 80000)
        self.assertEqual(statuses[:3], ['paid', 'partially_paid', 'upcoming'])
        partial = data['installments'][1]
        self.assertEqual(data['installment_amount'], partial['amount'] - partial['amount_paid'])

    def test_failed_webhook_leaves_goal(self):
        self.initiate(self.goal['uuid'], 50000, ref='SCFAIL0001')
        self.webhook('SCFAIL0001', status='FAILED')
        self.assertEqual(Payment.objects.get().status, 'failed')
        self.assertEqual(SavingsGoal.objects.get(uuid=self.goal['uuid']).amount_paid, 0)
        self.assertTrue(Notification.objects.filter(type='payment_failed').exists())

    def test_full_payment_completes_with_one_booking(self):
        self.initiate(self.goal['uuid'], 480000, ref='SCFULL0001')
        self.webhook('SCFULL0001')
        self.webhook('SCFULL0001')
        goal = self.client.get(f"/api/goals/{self.goal['uuid']}/").data
        self.assertEqual(goal['status'], 'completed')
        self.assertIsNone(goal['next_due_date'])
        self.assertEqual(goal['installment_amount'], 0)
        self.assertIsNotNone(goal['completed_at'])
        self.assertEqual(Booking.objects.count(), 1)

        booking = self.client.get(f"/api/bookings/{goal['booking_uuid']}/").data
        self.assertEqual(set(booking), BOOKING_KEYS)
        self.assertRegex(booking['confirmation_code'], r'^SC-[A-Z0-9]{6}$')
        self.assertEqual([d['type'] for d in booking['documents']], ['voucher', 'operator_contacts', 'packing_list'])
        self.assertEqual(set(booking['operator_contact']), {'name', 'phone_number', 'email', 'whatsapp'})
        self.assertEqual(len(self.client.get('/api/bookings/').data), 1)
        self.assertTrue(Notification.objects.filter(type='goal_completed').exists())

        res = self.initiate(self.goal['uuid'], 5000, ref='SCAFTER001')
        self.assertEqual(res.status_code, 409)
        self.assertEqual(res.data['detail'], "This goal is completed and can't take payments.")

    def test_goal_payments_listing(self):
        self.initiate(self.goal['uuid'], 50000, ref='SCLIST0001')
        self.initiate(self.goal['uuid'], 60000, ref='SCLIST0002')
        data = self.client.get(f"/api/goals/{self.goal['uuid']}/payments/").data
        self.assertEqual([p['amount'] for p in data], [60000, 50000])


class MissedAndExpiryTests(GoalFlowBase):
    def test_three_misses_pause_then_payment_resumes(self):
        data = self.create_active_goal(frequency='weekly')
        goal = SavingsGoal.objects.get(uuid=data['uuid'])
        dates = [i['due_date'] for i in data['installments']]
        from datetime import date
        third_due = date.fromisoformat(dates[2])

        process_goal_schedule(goal.id, today=third_due + timedelta(days=1))
        goal.refresh_from_db()
        self.assertEqual(goal.status, GoalStatus.PAUSED)
        self.assertEqual(goal.consecutive_missed, 3)
        self.assertEqual(goal.installments.filter(status=InstallmentStatus.MISSED).count(), 3)
        open_sum = sum(i.amount - i.amount_paid for i in goal.installments.exclude(status=InstallmentStatus.MISSED))
        self.assertEqual(open_sum, goal.total_amount - goal.amount_paid)
        self.assertTrue(Notification.objects.filter(type='goal_paused').exists())

        self.initiate(data['uuid'], 50000, ref='SCRESUME01')
        self.webhook('SCRESUME01')
        goal.refresh_from_db()
        self.assertEqual(goal.status, GoalStatus.ACTIVE)
        self.assertEqual(goal.consecutive_missed, 0)

    def test_expiry_after_pay_by(self):
        data = self.create_active_goal()
        goal = SavingsGoal.objects.get(uuid=data['uuid'])
        process_goal_schedule(goal.id, today=goal.pay_by_date + timedelta(days=1))
        goal.refresh_from_db()
        self.assertEqual(goal.status, GoalStatus.EXPIRED)
        self.assertTrue(Notification.objects.filter(type='goal_expired').exists())

        res = self.client.post(f"/api/goals/{data['uuid']}/reschedule/",
                               {'travel_date': days_from_today(300).isoformat(), 'frequency': 'bi_weekly'},
                               format='json')
        self.assertEqual(res.status_code, 200, res.data)
        self.assertEqual(res.data['status'], 'active')
        self.assertEqual(res.data['frequency'], 'bi_weekly')
        self.assertEqual(res.data['total_amount'], 480000)
        self.assertEqual(sum(i['amount'] for i in res.data['installments']), 480000)


class CancellationTests(GoalFlowBase):
    def test_quote_and_cancel_create_refund(self):
        data = self.create_active_goal()
        self.initiate(data['uuid'], 200000, ref='SCCANC0001')
        self.webhook('SCCANC0001')

        quote = self.client.get(f"/api/goals/{data['uuid']}/cancellation-quote/").data
        self.assertEqual(set(quote), CANCEL_KEYS)
        self.assertEqual(quote['refund_percentage'], 90)
        self.assertEqual(quote['processing_fee'], 5000)
        self.assertEqual(quote['refund_amount'], 175000)

        res = self.client.post(f"/api/goals/{data['uuid']}/cancel/", {'reason': 'Plans changed'}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, quote)
        goal = SavingsGoal.objects.get(uuid=data['uuid'])
        self.assertEqual(goal.status, GoalStatus.CANCELLED)
        refund = Refund.objects.get()
        self.assertEqual((refund.amount, refund.phone_number), (175000, '255712345678'))

        with mock.patch('apps.payments.services.clickpesa.create_mobile_payout', return_value={'id': 'PO1'}):
            from apps.payments.tasks import process_refunds
            process_refunds()
        refund.refresh_from_db()
        self.assertEqual(refund.status, 'completed')
        self.assertEqual(Payment.objects.get().status, 'refunded')

        self.assertEqual(self.client.post(f"/api/goals/{data['uuid']}/cancel/").status_code, 409)
