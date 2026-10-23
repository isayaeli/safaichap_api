"""Parity tests with the app's Dart calculators (guide §11)."""
from datetime import date

from django.test import SimpleTestCase

from apps.core.choices import InstallmentStatus
from apps.goals.services import pricing, schedule
from apps.goals.services.schedule import Entry
from utils.exceptions import ScheduleValidationError
from utils.money import convert

SERENGETI_PRICING = {
    'base_currency': 'USD',
    'resident_adult': 45000, 'resident_child': 25000,
    'non_resident_adult': 128000, 'non_resident_child': 72000,
    'seasonal_adjustments': [
        {'start_date': '2027-07-01', 'end_date': '2027-10-31', 'multiplier_bps': 12000, 'label': 'High season (+20%)'},
    ],
}


class SplitTests(SimpleTestCase):
    def test_split_examples(self):
        self.assertEqual(schedule.split(100, 3), [34, 34, 32])
        self.assertEqual(schedule.split(5, 4), [2, 2, 1])

    def test_split_edge_cases(self):
        self.assertEqual(schedule.split(0, 3), [])
        self.assertEqual(schedule.split(10, 0), [])
        self.assertEqual(schedule.split(7, 1), [7])
        for remaining in (1, 99, 480000, 3993600):
            for n in range(1, 15):
                self.assertEqual(sum(schedule.split(remaining, n)), remaining)


class PeriodTests(SimpleTestCase):
    def test_monthly_clamps_to_end_of_month(self):
        self.assertEqual(schedule.add_period(date(2026, 1, 31), 'monthly'), date(2026, 2, 28))
        self.assertEqual(schedule.add_period(date(2028, 1, 31), 'monthly'), date(2028, 2, 29))
        self.assertEqual(schedule.add_period(date(2026, 12, 15), 'monthly'), date(2027, 1, 15))

    def test_fixed_periods(self):
        self.assertEqual(schedule.add_period(date(2026, 1, 1), 'weekly'), date(2026, 1, 8))
        self.assertEqual(schedule.add_period(date(2026, 1, 1), 'bi_weekly'), date(2026, 1, 15))
        self.assertEqual(schedule.add_period(date(2026, 1, 1), 'custom', 10), date(2026, 1, 11))

    def test_monthly_steps_from_previous_due_date(self):
        dates = schedule.due_dates(date(2026, 1, 31), date(2026, 5, 31), 'monthly')
        self.assertEqual(dates, [date(2026, 2, 28), date(2026, 3, 28), date(2026, 4, 28), date(2026, 5, 28)])

    def test_pay_by(self):
        self.assertEqual(schedule.pay_by(date(2026, 8, 15), 14), date(2026, 8, 1))


class ValidationTests(SimpleTestCase):
    def test_too_soon(self):
        with self.assertRaisesMessage(ScheduleValidationError,
                                      "Travel date is too soon: full payment is due 14 days before travel."):
            schedule.validate(date(2026, 10, 18), date(2026, 11, 1), 14, 'monthly')

    def test_not_enough_time(self):
        with self.assertRaisesMessage(ScheduleValidationError, "Not enough time for a weekly plan."):
            schedule.validate(date(2026, 10, 18), date(2026, 11, 5), 14, 'weekly')


class MoneyTests(SimpleTestCase):
    def test_convert_rounds_up(self):
        # TSh 1,000 → USD at 1/2600 rounds UP to 39 cents
        self.assertEqual(convert(1000, 'TZS', 'USD', 1, 2600), 39)

    def test_convert_usd_to_tzs(self):
        self.assertEqual(convert(128000, 'USD', 'TZS', 2600, 1), 3_328_000)

    def test_quote_total_high_season(self):
        # $1,280 non-resident adult × 1.2 season → TZS at 2600/1
        travellers = [{'name': 'A', 'age_category': 'adult', 'residency': 'non_resident'}]
        q = pricing.quote(SERENGETI_PRICING, travellers, date(2027, 8, 15), 'TZS', 2600, 1)
        self.assertEqual(q.total, 3_993_600)
        self.assertEqual(q.season_label, 'High season (+20%)')
        self.assertEqual(q.lines[0].to_dict(), {
            'residency': 'non_resident', 'age_category': 'adult', 'count': 1,
            'unit_price': 3_993_600, 'subtotal': 3_993_600,
        })

    def test_quote_lines_unit_times_count(self):
        travellers = [
            {'name': 'A', 'age_category': 'adult', 'residency': 'resident'},
            {'name': 'B', 'age_category': 'adult', 'residency': 'resident'},
            {'name': 'C', 'age_category': 'child', 'residency': 'non_resident'},
        ]
        q = pricing.quote(SERENGETI_PRICING, travellers, date(2027, 3, 1), 'TZS', 2600, 1)
        self.assertIsNone(q.season_label)
        self.assertEqual([(l.residency, l.age_category, l.count) for l in q.lines],
                         [('resident', 'adult', 2), ('non_resident', 'child', 1)])
        self.assertEqual(q.total, sum(l.unit_price * l.count for l in q.lines))


class GenerateTests(SimpleTestCase):
    def test_schedule_sums_to_total(self):
        today = date(2026, 10, 18)
        for deposit in (0, 50000):
            for freq in ('weekly', 'bi_weekly', 'monthly'):
                entries = schedule.generate(480000, deposit, today, date(2027, 11, 1), freq, minimum_payment=5000)
                self.assertEqual(sum(e.amount for e in entries), 480000)
                if deposit:
                    self.assertTrue(entries[0].is_deposit)
                    self.assertEqual(entries[0].due_date, today)

    def test_minimum_payment_keeps_latest_dates(self):
        today = date(2026, 10, 18)
        entries = schedule.generate(12000, 0, today, date(2027, 11, 1), 'monthly', minimum_payment=5000)
        self.assertEqual([e.amount for e in entries], [6000, 6000])
        self.assertEqual(entries[-1].due_date, date(2027, 10, 18))

    def test_below_minimum_uses_first_date(self):
        today = date(2026, 10, 18)
        entries = schedule.generate(3000, 0, today, date(2027, 11, 1), 'monthly', minimum_payment=5000)
        self.assertEqual([(e.due_date, e.amount) for e in entries], [(date(2026, 11, 18), 3000)])


class ApplyPaymentTests(SimpleTestCase):
    def _entries(self):
        return [Entry(date(2026, 11, d), 100) for d in (1, 2, 3)]

    def test_overpayment_flows_forward(self):
        entries = self._entries()
        schedule.apply_payment(entries, 150)
        self.assertEqual([e.status for e in entries],
                         [InstallmentStatus.PAID, InstallmentStatus.PARTIALLY_PAID, InstallmentStatus.UPCOMING])
        self.assertEqual(entries[1].outstanding, 50)


class MissedTests(SimpleTestCase):
    def test_shortfall_rolls_into_future(self):
        entries = [Entry(date(2026, 11, 1), 100), Entry(date(2026, 12, 1), 100), Entry(date(2027, 1, 1), 100)]
        schedule.apply_payment(entries, 40)
        missed = schedule.mark_missed(entries, date(2026, 11, 5))
        self.assertEqual(missed, 1)
        self.assertEqual(entries[0].status, InstallmentStatus.MISSED)
        self.assertEqual(entries[0].amount, 40)
        future = [e for e in entries if e.is_open]
        self.assertEqual(sum(e.outstanding for e in future), 300 - 40)
        self.assertEqual(sum(e.amount for e in entries), 300)

    def test_rebalance_drops_unpaid_tail(self):
        entries = [Entry(date(2026, 12, 1), 1), Entry(date(2027, 1, 1), 1), Entry(date(2027, 2, 1), 0)]
        schedule.rebalance(entries, date(2026, 11, 1))
        self.assertEqual([e.amount for e in entries], [1, 1])
