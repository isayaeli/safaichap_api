import logging
from datetime import timedelta

from celery import shared_task
from django.utils import timezone

from apps.core.choices import PaymentStatus
from apps.core.models import AppSetting
from .models import Payment, Refund
from .services import process_refund, reconcile_payment

logger = logging.getLogger(__name__)

MAX_REFUND_ATTEMPTS = 5


@shared_task
def reconcile_pending_payments():
    """Every 2 min: settle pending payments older than 1 min from the provider; fail them after the timeout."""
    timeout = AppSetting.get().pending_payment_timeout_minutes
    cutoff = timezone.now() - timedelta(minutes=1)
    pending = Payment.objects.filter(status=PaymentStatus.PENDING, created_at__lt=cutoff)
    count = 0
    for payment in pending.iterator():
        try:
            reconcile_payment(payment, timeout)
            count += 1
        except Exception:
            logger.exception("Reconcile failed for payment %s", payment.order_reference)
    return {"checked": count}


@shared_task
def process_refunds():
    """Every 10 min: send pending refunds (and retry failed ones) through the provider."""
    ids = list(
        Refund.objects.filter(status__in=('pending', 'failed'), attempts__lt=MAX_REFUND_ATTEMPTS)
        .values_list('id', flat=True)
    )
    for refund_id in ids:
        try:
            process_refund(refund_id)
        except Exception:
            logger.exception("Refund %s crashed", refund_id)
    return {"processed": len(ids)}
