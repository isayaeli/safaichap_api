"""
Savings goal lifecycle (guide §7). Every state change that touches money runs
inside transaction.atomic() with the goal row locked (select_for_update).
"""
from dataclasses import dataclass
from datetime import date

from django.db import transaction
from django.utils import timezone

from apps.catalogue.models import Itinerary, RefundPolicy
from apps.core.choices import AgeCategory, GoalStatus, InstallmentStatus, NotificationType
from apps.core.fx import get_rate
from apps.core.models import AppSetting
from apps.goals.models import Installment, SavingsGoal, Traveller
from apps.notifications.services import notify
from utils.dates import today as local_today
from utils.exceptions import BadRequest, Conflict, ScheduleValidationError
from utils.money import ceil_div, format_major, is_supported
from . import pricing as pricing_rules
from . import schedule as schedule_rules
from .schedule import Entry

ACCEPTS_PAYMENTS = (GoalStatus.ACTIVE, GoalStatus.PAUSED)
RESCHEDULABLE = (GoalStatus.ACTIVE, GoalStatus.PAUSED, GoalStatus.EXPIRED)
CANCELLABLE = (GoalStatus.DRAFT, GoalStatus.ACTIVE, GoalStatus.PAUSED, GoalStatus.EXPIRED)


# ── Schedule persistence ────────────────────────────────────────────────

def load_entries(goal: SavingsGoal) -> list[Entry]:
    return [
        Entry(due_date=i.due_date, amount=i.amount, amount_paid=i.amount_paid, status=i.status,
              is_deposit=i.is_deposit, obj=i)
        for i in goal.installments.order_by('due_date', 'position')
    ]


def write_schedule(goal: SavingsGoal, entries: list[Entry]) -> None:
    """Persists entries in due-date order; updates rows in place, creates new ones, deletes dropped ones."""
    entries = sorted(entries, key=lambda e: (e.due_date, not e.is_deposit))
    keep_ids = []
    for position, e in enumerate(entries):
        if e.obj is not None:
            inst = e.obj
            inst.due_date, inst.amount, inst.amount_paid = e.due_date, e.amount, e.amount_paid
            inst.status, inst.is_deposit, inst.position = e.status, e.is_deposit, position
            inst.save(update_fields=['due_date', 'amount', 'amount_paid', 'status', 'is_deposit', 'position',
                                     'updated_at'])
        else:
            inst = Installment.objects.create(
                goal=goal, due_date=e.due_date, amount=e.amount, amount_paid=e.amount_paid,
                status=e.status, is_deposit=e.is_deposit, position=position,
            )
            e.obj = inst
        keep_ids.append(inst.pk)
    goal.installments.exclude(pk__in=keep_ids).delete()


def next_open_installment(installments) -> Installment | None:
    """installment_amount / next_due_date come from the next open installment by due date."""
    for inst in sorted(installments, key=lambda i: (i.due_date, i.position)):
        if inst.status in schedule_rules.OPEN_STATUSES:
            return inst
    return None


# ── Plan (quote / create / activate) ────────────────────────────────────

@dataclass
class Plan:
    itinerary: Itinerary
    travellers: list[dict]
    travel_date: date
    pay_by_date: date
    currency: str
    frequency: str
    custom_days: int
    deposit: int
    breakdown: pricing_rules.PriceBreakdown
    fx: tuple[int, int]
    schedule: list[Entry]
    pricing_snapshot: dict

    def quote_dict(self) -> dict:
        return {
            'currency': self.currency,
            'total_amount': self.breakdown.total,
            'deposit_amount': self.deposit,
            'pay_by_date': self.pay_by_date.isoformat(),
            'season_label': self.breakdown.season_label,
            'lines': [line.to_dict() for line in self.breakdown.lines],
            'installments': [
                {'due_date': e.due_date.isoformat(), 'amount': e.amount, 'is_deposit': e.is_deposit}
                for e in self.schedule
            ],
        }


def build_plan(itinerary: Itinerary, travellers: list[dict], travel_date: date, currency: str,
               frequency: str, custom_days: int = 30, deposit: int = 0, today: date | None = None) -> Plan:
    """Validates the plan and prices it with current prices and FX. Saves nothing."""
    today = today or local_today()
    app_settings = AppSetting.get()

    if not itinerary.is_active:
        raise BadRequest("This trip isn't available any more.")
    if not is_supported(currency):
        raise BadRequest("That currency isn't supported.")
    if not travellers:
        raise BadRequest("Add at least one traveller.")
    if not itinerary.min_group_size <= len(travellers) <= itinerary.max_group_size:
        raise BadRequest(f"This trip takes {itinerary.min_group_size}–{itinerary.max_group_size} travellers.")
    if not any(t['age_category'] == AgeCategory.ADULT for t in travellers):
        raise BadRequest("At least one adult must travel.")

    lead = itinerary.effective_lead_time_days(app_settings.default_lead_time_days)
    try:
        pay_by_date = schedule_rules.validate(today, travel_date, lead, frequency, custom_days)
    except ScheduleValidationError as e:
        raise BadRequest(str(e))

    pricing = itinerary.pricing.to_dict()
    fx = get_rate(pricing['base_currency'], currency)
    breakdown = pricing_rules.quote(pricing, travellers, travel_date, currency, *fx)

    if deposit < 0 or deposit >= breakdown.total:
        raise BadRequest("Deposit must be less than the total.")

    entries = schedule_rules.generate(
        total=breakdown.total, deposit=deposit, today=today, pay_by_date=pay_by_date,
        frequency=frequency, custom_days=custom_days,
        minimum_payment=app_settings.minimum_payment(currency),
    )
    snapshot = {
        'pricing': pricing,
        'season_label': breakdown.season_label,
        'multiplier_bps': breakdown.multiplier_bps,
        'lines': [line.to_dict() for line in breakdown.lines],
        'fx': {'from': pricing['base_currency'], 'to': currency, 'numerator': fx[0], 'denominator': fx[1]},
        'priced_on': today.isoformat(),
    }
    return Plan(
        itinerary=itinerary, travellers=travellers, travel_date=travel_date, pay_by_date=pay_by_date,
        currency=currency, frequency=frequency, custom_days=custom_days, deposit=deposit,
        breakdown=breakdown, fx=fx, schedule=entries, pricing_snapshot=snapshot,
    )


def _goal_travellers(goal: SavingsGoal) -> list[dict]:
    return [{'name': t.name, 'age_category': t.age_category, 'residency': t.residency}
            for t in goal.travellers.all()]


@transaction.atomic
def create_goal(user, plan: Plan, title: str | None = None) -> SavingsGoal:
    goal = SavingsGoal.objects.create(
        user=user, itinerary=plan.itinerary, title=(title or '').strip() or plan.itinerary.title,
        travel_date=plan.travel_date, pay_by_date=plan.pay_by_date, currency=plan.currency,
        total_amount=plan.breakdown.total, deposit_amount=plan.deposit, frequency=plan.frequency,
        custom_days=plan.custom_days, status=GoalStatus.DRAFT,
    )
    Traveller.objects.bulk_create([
        Traveller(goal=goal, name=t['name'], age_category=t['age_category'], residency=t['residency'], position=i)
        for i, t in enumerate(plan.travellers)
    ])
    return goal


def lock_goal(user, goal_uuid) -> SavingsGoal:
    """Fetches the user's goal with a row lock (call inside transaction.atomic)."""
    from django.http import Http404
    try:
        return SavingsGoal.objects.select_for_update().get(uuid=goal_uuid, user=user)
    except SavingsGoal.DoesNotExist:
        raise Http404("Goal not found.")


@transaction.atomic
def activate_goal(user, goal_uuid) -> SavingsGoal:
    """draft → active: re-price with today's prices and FX, build the schedule, then lock the price."""
    goal = lock_goal(user, goal_uuid)
    if goal.status != GoalStatus.DRAFT:
        raise Conflict("Only draft goals can be activated.")

    plan = build_plan(
        goal.itinerary, _goal_travellers(goal), goal.travel_date, goal.currency,
        goal.frequency, goal.custom_days, goal.deposit_amount,
    )
    goal.total_amount = plan.breakdown.total
    goal.pay_by_date = plan.pay_by_date
    goal.locked_fx_numerator, goal.locked_fx_denominator = plan.fx
    goal.locked_pricing_snapshot = plan.pricing_snapshot
    goal.status = GoalStatus.ACTIVE
    goal.activated_at = timezone.now()
    goal.save()
    write_schedule(goal, plan.schedule)
    return goal


@transaction.atomic
def delete_draft(user, goal_uuid) -> None:
    goal = lock_goal(user, goal_uuid)
    if goal.status != GoalStatus.DRAFT:
        raise Conflict("Only drafts can be deleted.")
    goal.delete()


# ── Reschedule & cancellation ───────────────────────────────────────────

@transaction.atomic
def reschedule_goal(user, goal_uuid, travel_date: date, frequency: str | None = None) -> SavingsGoal:
    """New travel date (and optionally frequency); the price stays locked, only the balance is re-spread."""
    goal = lock_goal(user, goal_uuid)
    if goal.status not in RESCHEDULABLE:
        raise Conflict("This goal can't be rescheduled.")

    app_settings = AppSetting.get()
    today = local_today()
    frequency = frequency or goal.frequency
    lead = goal.itinerary.effective_lead_time_days(app_settings.default_lead_time_days)
    try:
        pay_by_date = schedule_rules.validate(today, travel_date, lead, frequency, goal.custom_days)
    except ScheduleValidationError as e:
        raise BadRequest(str(e))

    kept = []
    for e in load_entries(goal):
        if e.amount_paid > 0:
            e.amount = e.amount_paid
            e.status = InstallmentStatus.PAID
            kept.append(e)
    fresh = schedule_rules.generate(
        total=goal.remaining, deposit=0, today=today, pay_by_date=pay_by_date,
        frequency=frequency, custom_days=goal.custom_days,
        minimum_payment=app_settings.minimum_payment(goal.currency),
    )
    goal.travel_date = travel_date
    goal.pay_by_date = pay_by_date
    goal.frequency = frequency
    goal.status = GoalStatus.ACTIVE
    goal.consecutive_missed = 0
    goal.save()
    write_schedule(goal, kept + fresh)
    return goal


def refund_policy_for(goal: SavingsGoal) -> RefundPolicy:
    return (
        goal.itinerary.operator.refund_policy
        or RefundPolicy.objects.filter(is_default=True).first()
        or RefundPolicy(name='Default')  # unsaved; the model defaults are the global policy
    )


def cancellation_quote(goal: SavingsGoal, today: date | None = None) -> dict:
    today = today or local_today()
    policy = refund_policy_for(goal)
    paid = goal.amount_paid
    days_to_travel = (goal.travel_date - today).days
    pct = policy.percentage_for(days_to_travel)
    fee = ceil_div(paid * policy.processing_fee_bps, 10000)
    refund = max(0, paid * pct // 100 - fee)
    return {
        'currency': goal.currency,
        'amount_paid': paid,
        'refund_percentage': pct,
        'processing_fee': fee,
        'refund_amount': refund,
        'policy': policy.description,
    }


@transaction.atomic
def cancel_goal(user, goal_uuid, reason: str | None = None) -> dict:
    from apps.payments.services import create_refund

    goal = lock_goal(user, goal_uuid)
    if goal.status not in CANCELLABLE:
        raise Conflict("This goal can't be cancelled.")

    quote = cancellation_quote(goal)
    goal.status = GoalStatus.CANCELLED
    goal.cancellation_reason = (reason or '').strip() or None
    goal.save(update_fields=['status', 'cancellation_reason', 'updated_at'])

    if quote['refund_amount'] > 0:
        create_refund(goal, quote['refund_amount'])
        message = f"Your refund of {format_major(quote['refund_amount'], goal.currency)} is being processed."
    else:
        message = f"{goal.title} has been cancelled."
    notify(goal.user, "Goal cancelled", message, NotificationType.GOAL_CANCELLED, goal)
    return quote


# ── Payments, completion, missed installments ──────────────────────────

def apply_successful_payment(goal: SavingsGoal, amount: int) -> SavingsGoal:
    """
    §7.5. Caller must hold the goal row lock (select_for_update) in a transaction.
    Fills open installments in due order, resets missed count, resumes paused
    goals and completes the goal when fully paid.
    """
    entries = load_entries(goal)
    schedule_rules.apply_payment(entries, amount)
    write_schedule(goal, entries)

    goal.amount_paid += amount
    goal.consecutive_missed = 0
    if goal.status == GoalStatus.PAUSED:
        goal.status = GoalStatus.ACTIVE
    goal.save(update_fields=['amount_paid', 'consecutive_missed', 'status', 'updated_at'])

    if goal.amount_paid >= goal.total_amount:
        complete_goal(goal)
    return goal


def complete_goal(goal: SavingsGoal):
    from apps.bookings.services import create_booking

    goal.status = GoalStatus.COMPLETED
    goal.completed_at = timezone.now()
    goal.save(update_fields=['status', 'completed_at', 'updated_at'])
    return create_booking(goal)


def process_goal_schedule(goal_id: int, today: date | None = None) -> None:
    """§7.8 for one goal: mark missed, roll shortfall forward, pause after N misses, expire after pay-by."""
    today = today or local_today()
    app_settings = AppSetting.get()
    with transaction.atomic():
        goal = SavingsGoal.objects.select_for_update().select_related('user').get(pk=goal_id)
        if goal.status not in ACCEPTS_PAYMENTS:
            return

        entries = load_entries(goal)
        missed = schedule_rules.mark_missed(entries, today)
        if missed:
            # Nothing left to roll into (the missed one was the last): catch up on the pay-by date.
            scheduled = sum(e.amount for e in entries)
            catch_up = goal.total_amount - scheduled
            if catch_up > 0 and not any(e.is_open for e in entries) and today <= goal.pay_by_date:
                entries.append(Entry(due_date=goal.pay_by_date, amount=catch_up))

            goal.consecutive_missed += missed
            notify(goal.user, "Installment missed",
                   f"You missed a payment for {goal.title}. We've spread it over your remaining installments.",
                   NotificationType.INSTALLMENT_MISSED, goal)
            if goal.consecutive_missed >= app_settings.missed_before_pause and goal.status == GoalStatus.ACTIVE:
                goal.status = GoalStatus.PAUSED
                notify(goal.user, "Goal paused",
                       f"{goal.title} is paused after {goal.consecutive_missed} missed installments. "
                       "Make a payment to resume.",
                       NotificationType.GOAL_PAUSED, goal)
            write_schedule(goal, entries)

        if today > goal.pay_by_date and goal.amount_paid < goal.total_amount:
            goal.status = GoalStatus.EXPIRED
            notify(goal.user, "Goal expired",
                   f"The pay-by date for {goal.title} has passed. Reschedule your trip or request a cancellation.",
                   NotificationType.GOAL_EXPIRED, goal)
        goal.save(update_fields=['status', 'consecutive_missed', 'updated_at'])
