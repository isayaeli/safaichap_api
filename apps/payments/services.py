"""
Payment rules (guide §7.6–7.7, §7.9 refunds). The client never decides the
outcome: only webhooks or reconciliation move a payment to success/failed,
always through settle_payment().
"""
import logging
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from apps.core.choices import GoalStatus, MOBILE_MONEY_METHODS, NotificationType, PaymentMethod, PaymentStatus
from apps.core.models import AppSetting
from apps.goals.models import SavingsGoal
from apps.goals.services.goals import ACCEPTS_PAYMENTS, apply_successful_payment
from apps.notifications.services import notify
from utils import card_gateway, clickpesa
from utils.exceptions import BadRequest, Conflict, ProviderError
from utils.money import MOBILE_MONEY_CURRENCY, format_major, minor_per_major
from utils.order_reference import generate_order_reference, receipt_number
from .models import Payment, Refund

logger = logging.getLogger(__name__)


# ── Initiation ─────────────────────────────────────────────────────────

def initiate_payment(user, data: dict) -> Payment:
    """Validated serializer data → a pending Payment with the provider call made."""
    order_reference = data['order_reference']

    # 1. Idempotency: a retried request returns the original payment unchanged.
    existing = Payment.objects.filter(order_reference=order_reference).first()
    if existing:
        if existing.user_id != user.pk:
            raise Conflict("This payment reference has already been used.")
        return existing

    try:
        goal = SavingsGoal.objects.get(uuid=data['goal_uuid'], user=user)
    except SavingsGoal.DoesNotExist:
        raise Http404("Goal not found.")

    amount, currency, method = data['amount'], data['currency'], data['method']
    phone = data.get('phone_number') or None
    app_settings = AppSetting.get()

    if goal.status not in ACCEPTS_PAYMENTS:
        raise Conflict(f"This goal is {goal.get_status_display().lower()} and can't take payments.")
    if currency != goal.currency:
        raise BadRequest(f"Payments for this goal must be in {goal.currency}.")
    remaining = goal.remaining
    minimum = app_settings.minimum_payment(currency)
    if amount > remaining:
        raise BadRequest("Amount is more than the remaining balance.")
    if amount < minimum and amount != remaining:
        raise BadRequest(f"Minimum payment is {currency} {minimum // minor_per_major(currency)}.")
    is_mobile = method in MOBILE_MONEY_METHODS
    if currency == MOBILE_MONEY_CURRENCY and not is_mobile:
        raise BadRequest("TZS goals are paid with mobile money.")
    if currency != MOBILE_MONEY_CURRENCY and is_mobile:
        raise BadRequest(f"{currency} goals are paid by card.")
    if is_mobile and not phone:
        raise BadRequest("Enter the mobile money number to charge.")

    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                goal=goal, user=user, amount=amount, currency=currency, method=method,
                phone_number=phone if is_mobile else None, order_reference=order_reference,
                provider='clickpesa' if is_mobile else 'flutterwave', status=PaymentStatus.PENDING,
            )
    except IntegrityError:
        # A parallel request with the same reference won the race.
        existing = Payment.objects.filter(order_reference=order_reference, user=user).first()
        if existing:
            return existing
        raise Conflict("This payment reference has already been used.")

    try:
        if is_mobile:
            response = clickpesa.initiate_ussd_push(order_reference, amount, phone)
            payment.provider_txn_id = response.get('id') or None
            payment.save(update_fields=['provider_txn_id', 'updated_at'])
        else:
            payment.checkout_url = card_gateway.create_checkout(order_reference, amount, currency, user, goal.title)
            payment.save(update_fields=['checkout_url', 'updated_at'])
    except ProviderError as e:
        logger.warning("Payment %s initiation failed: %s", order_reference, e)
        payment.status = PaymentStatus.FAILED
        payment.failure_reason = e.user_message
        payment.save(update_fields=['status', 'failure_reason', 'updated_at'])
    return payment


# ── Settlement (webhooks + reconciliation) ─────────────────────────────

def _unique_receipt() -> str:
    for _ in range(10):
        number = receipt_number()
        if not Payment.objects.filter(receipt_number=number).exists():
            return number
    raise RuntimeError("Could not generate a unique receipt number")


def settle_payment(order_reference: str, success: bool, provider_reference: str | None = None,
                   provider_txn_id: str | None = None, failure_reason: str | None = None,
                   raw: dict | None = None) -> Payment | None:
    """
    Moves a pending payment to success/failed exactly once (duplicate or
    parallel webhooks are no-ops) and applies it to the goal under row locks.
    """
    with transaction.atomic():
        payment = (
            Payment.objects.select_for_update().select_related('user')
            .filter(order_reference=order_reference).first()
        )
        if payment is None:
            logger.warning("Settlement for unknown order_reference %s", order_reference)
            return None
        if raw is not None:
            payment.raw_webhook = raw
        if payment.is_final:
            payment.save(update_fields=['raw_webhook', 'updated_at'])
            return payment

        if provider_txn_id:
            payment.provider_txn_id = provider_txn_id
        payment.settled_at = timezone.now()

        if not success:
            payment.status = PaymentStatus.FAILED
            payment.failure_reason = failure_reason or "The payment was declined or cancelled."
            payment.save()
            notify(payment.user, "Payment failed",
                   f"Your {format_major(payment.amount, payment.currency)} payment didn't go through.",
                   NotificationType.PAYMENT_FAILED, payment.goal)
            return payment

        payment.status = PaymentStatus.SUCCESS
        payment.provider_reference = provider_reference or payment.provider_reference
        payment.receipt_number = _unique_receipt()
        payment.failure_reason = None
        payment.save()

        goal = SavingsGoal.objects.select_for_update().get(pk=payment.goal_id)
        if goal.status in (GoalStatus.CANCELLED, GoalStatus.COMPLETED):
            # Money arrived after the goal closed: give all of it back.
            create_refund(goal, payment.amount)
            notify(payment.user, "Payment received",
                   f"We received {format_major(payment.amount, payment.currency)} for {goal.title}, "
                   "but this goal is closed, so we're refunding it in full.",
                   NotificationType.PAYMENT_SUCCESS, goal)
            return payment

        notify(payment.user, "Payment received",
               f"We received {format_major(payment.amount, payment.currency)} for {goal.title}.",
               NotificationType.PAYMENT_SUCCESS, goal)
        apply_successful_payment(goal, payment.amount)
        return payment


def reconcile_payment(payment: Payment, timeout_minutes: int) -> None:
    """Asks the provider for the status of a pending payment and settles it; fails it after the timeout."""
    status = None
    provider_reference = txn_id = None
    try:
        if payment.provider == 'clickpesa':
            record = clickpesa.query_payment_status(payment.order_reference)
            if record:
                status = (record.get('status') or '').upper()
                provider_reference = record.get('paymentReference') or record.get('id')
                txn_id = record.get('id')
                if status in clickpesa.SUCCESS_STATUSES:
                    status = 'success'
                elif status in clickpesa.FAILED_STATUSES:
                    status = 'failed'
        else:
            record = card_gateway.verify_by_reference(payment.order_reference)
            if record:
                fw_status = (record.get('status') or '').lower()
                txn_id = str(record.get('id') or '') or None
                provider_reference = record.get('flw_ref') or txn_id
                if fw_status in card_gateway.SUCCESS_STATUSES and card_amount_matches(payment, record):
                    status = 'success'
                elif fw_status in card_gateway.FAILED_STATUSES:
                    status = 'failed'
    except ProviderError as e:
        logger.warning("Reconcile query failed for %s: %s", payment.order_reference, e)

    if status == 'success':
        settle_payment(payment.order_reference, True, provider_reference, txn_id)
    elif status == 'failed':
        settle_payment(payment.order_reference, False, provider_reference, txn_id,
                       "The payment was declined or cancelled.")
    elif payment.created_at < timezone.now() - timedelta(minutes=timeout_minutes):
        settle_payment(payment.order_reference, False, failure_reason=(
            "We didn't get a confirmation in time. If money left your account, contact support with your reference."
        ))


def card_amount_matches(payment: Payment, record: dict) -> bool:
    try:
        charged = round(float(record.get('amount', 0)) * minor_per_major(payment.currency))
    except (TypeError, ValueError):
        return False
    return record.get('currency') == payment.currency and charged >= payment.amount


# ── Refunds ────────────────────────────────────────────────────────────

def create_refund(goal: SavingsGoal, amount: int) -> Refund:
    last_mobile = (
        goal.payments.filter(status=PaymentStatus.SUCCESS).exclude(phone_number__isnull=True)
        .order_by('-created_at').values_list('phone_number', flat=True).first()
    )
    return Refund.objects.create(
        goal=goal, user=goal.user, amount=amount, currency=goal.currency,
        order_reference=generate_order_reference('SCRF'), phone_number=last_mobile,
    )


def process_refund(refund_id: int) -> None:
    """
    TZS: one ClickPesa mobile payout to the number that last paid.
    Cards: refund settled card transactions newest first until the amount is covered.
    """
    with transaction.atomic():
        refund = Refund.objects.select_for_update().get(pk=refund_id)
        if refund.status not in ('pending', 'failed'):
            return
        refund.status = 'processing'
        refund.attempts += 1
        refund.save(update_fields=['status', 'attempts', 'updated_at'])

    try:
        if refund.currency == MOBILE_MONEY_CURRENCY:
            if not refund.phone_number:
                raise ProviderError("No mobile money number to refund to")
            response = clickpesa.create_mobile_payout(refund.order_reference, refund.amount, refund.phone_number)
            references = [str(response.get('id') or refund.order_reference)]
        else:
            references = []
            left = refund.amount
            payments = refund.goal.payments.filter(status=PaymentStatus.SUCCESS, method=PaymentMethod.CARD) \
                .exclude(provider_txn_id__isnull=True).order_by('-created_at')
            for p in payments:
                if left <= 0:
                    break
                part = min(left, p.amount)
                response = card_gateway.refund(p.provider_txn_id, part, refund.currency)
                references.append(str(response.get('id') or p.provider_txn_id))
                left -= part
            if left > 0:
                raise ProviderError(f"Only part of the refund could be placed ({left} left)")
    except ProviderError as e:
        logger.error("Refund %s failed: %s", refund.order_reference, e)
        Refund.objects.filter(pk=refund.pk).update(status='failed', failure_reason=str(e), updated_at=timezone.now())
        return

    with transaction.atomic():
        Refund.objects.filter(pk=refund.pk).update(
            status='completed', provider_reference=",".join(references)[:255],
            processed_at=timezone.now(), failure_reason=None, updated_at=timezone.now(),
        )
        if refund.goal.status == GoalStatus.CANCELLED:
            refund.goal.payments.filter(status=PaymentStatus.SUCCESS).update(
                status=PaymentStatus.REFUNDED, updated_at=timezone.now(),
            )
