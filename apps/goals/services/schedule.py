"""
Pure scheduling rules, ported one-to-one from the app's
lib/src/core/utils/schedule_calculator.dart. Keep them in sync.
"""
import calendar
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from apps.core.choices import InstallmentStatus, PaymentFrequency
from utils.exceptions import ScheduleValidationError

OPEN_STATUSES = (InstallmentStatus.UPCOMING, InstallmentStatus.PARTIALLY_PAID)

FREQUENCY_LABELS = {
    PaymentFrequency.WEEKLY: 'weekly',
    PaymentFrequency.BI_WEEKLY: 'every 2 weeks',
    PaymentFrequency.MONTHLY: 'monthly',
    PaymentFrequency.CUSTOM: 'custom',
}


@dataclass
class Entry:
    """A single scheduled installment, independent of persistence."""
    due_date: date
    amount: int
    amount_paid: int = 0
    status: str = InstallmentStatus.UPCOMING
    is_deposit: bool = False
    obj: Any = field(default=None, compare=False, repr=False)  # backing Installment row, if any

    @property
    def outstanding(self) -> int:
        return self.amount - self.amount_paid

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES


def pay_by(travel_date: date, lead_time_days: int) -> date:
    """Pay-by date = travel date − operator lead time."""
    return travel_date - timedelta(days=lead_time_days)


def add_period(d: date, frequency: str, custom_days: int = 30) -> date:
    """One period after `d`. Monthly clamps to the end of month (Jan 31 → Feb 28/29)."""
    if frequency == PaymentFrequency.WEEKLY:
        return d + timedelta(days=7)
    if frequency == PaymentFrequency.BI_WEEKLY:
        return d + timedelta(days=14)
    if frequency == PaymentFrequency.CUSTOM:
        return d + timedelta(days=custom_days)
    if frequency == PaymentFrequency.MONTHLY:
        y, m = (d.year + 1, 1) if d.month == 12 else (d.year, d.month + 1)
        last_day = calendar.monthrange(y, m)[1]
        return date(y, m, min(d.day, last_day))
    raise ValueError(f"Unknown frequency: {frequency}")


def due_dates(start: date, pay_by_date: date, frequency: str, custom_days: int = 30) -> list[date]:
    """Due dates from one period after `start` up to and including `pay_by_date`."""
    dates = []
    d = add_period(start, frequency, custom_days)
    while d <= pay_by_date:
        dates.append(d)
        d = add_period(d, frequency, custom_days)
    return dates


def validate(today: date, travel_date: date, lead_time_days: int, frequency: str, custom_days: int = 30) -> date:
    """Raises if the travel date doesn't leave one full period before pay-by. Returns pay-by."""
    pay_by_date = pay_by(travel_date, lead_time_days)
    if pay_by_date <= today:
        raise ScheduleValidationError(
            f"Travel date is too soon: full payment is due {lead_time_days} days before travel."
        )
    if not due_dates(today, pay_by_date, frequency, custom_days):
        raise ScheduleValidationError(
            f"Not enough time for a {FREQUENCY_LABELS.get(frequency, frequency)} plan. "
            "Choose a later travel date or a shorter frequency."
        )
    return pay_by_date


def split(remaining: int, periods: int) -> list[int]:
    """
    Each part is ceil(remaining / periods), the last absorbs the remainder so the
    parts sum exactly to `remaining`. Zero-amount tail parts are dropped.
    """
    if remaining <= 0 or periods <= 0:
        return []
    each = -(-remaining // periods)
    parts = []
    left = remaining
    for i in range(periods):
        if left <= 0:
            break
        amount = left if i == periods - 1 else min(each, left)
        parts.append(amount)
        left -= amount
    return parts


def generate(total: int, deposit: int, today: date, pay_by_date: date, frequency: str,
             custom_days: int = 30, minimum_payment: int | None = None) -> list[Entry]:
    """
    Builds a fresh schedule. A positive deposit is due today. With
    `minimum_payment`, periods are reduced (keeping the latest dates) so no
    regular installment falls below it.
    """
    entries = []
    if deposit > 0:
        entries.append(Entry(due_date=today, amount=deposit, is_deposit=True))
    dates = due_dates(today, pay_by_date, frequency, custom_days)
    remaining = total - deposit
    if minimum_payment and minimum_payment > 0 and dates:
        max_periods = remaining // minimum_payment
        if max_periods < 1:
            dates = [dates[0]]
        elif max_periods < len(dates):
            dates = dates[-max_periods:]
    for due, amount in zip(dates, split(remaining, len(dates))):
        entries.append(Entry(due_date=due, amount=amount))
    return entries


def apply_payment(entries: list[Entry], amount: int) -> None:
    """Fills open installments in due order; overpayment flows into the next ones."""
    left = amount
    for e in entries:
        if left <= 0:
            break
        if not e.is_open:
            continue
        take = min(left, e.outstanding)
        e.amount_paid += take
        left -= take
        e.status = InstallmentStatus.PAID if e.outstanding == 0 else InstallmentStatus.PARTIALLY_PAID


def mark_missed(entries: list[Entry], today: date) -> int:
    """
    Marks open installments due before `today` as missed (amount collapses to
    what was paid) and rolls the shortfall into future open installments.
    Returns the number newly missed.
    """
    shortfall = 0
    missed = 0
    for e in entries:
        if e.is_open and e.due_date < today:
            shortfall += e.outstanding
            e.amount = e.amount_paid
            e.status = InstallmentStatus.MISSED
            missed += 1
    if shortfall > 0:
        rebalance(entries, today, extra=shortfall)
    return missed


def rebalance(entries: list[Entry], today: date, extra: int = 0) -> None:
    """
    Re-spreads what is still owed (plus `extra`) across future open installments,
    keeping their due dates. Fully covered tail entries with nothing paid are removed.
    """
    future = [e for e in entries if e.is_open and e.due_date >= today]
    if not future:
        return
    owed = sum(e.outstanding for e in future) + extra
    parts = split(owed, len(future))
    for i, e in enumerate(future):
        if i < len(parts):
            e.amount = e.amount_paid + parts[i]
            e.status = InstallmentStatus.PARTIALLY_PAID if e.amount_paid > 0 else InstallmentStatus.UPCOMING
        elif e.amount_paid == 0:
            entries.remove(e)
        else:
            e.amount = e.amount_paid
            e.status = InstallmentStatus.PAID


def next_open(entries: list[Entry]) -> Entry | None:
    for e in sorted(entries, key=lambda e: e.due_date):
        if e.is_open:
            return e
    return None
