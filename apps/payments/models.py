from django.conf import settings
from django.db import models

from apps.core.choices import PaymentMethod, PaymentStatus
from apps.core.models import TimeStampedModel
from apps.goals.models import SavingsGoal
from utils.money import CURRENCY_CHOICES


class Payment(TimeStampedModel):
    PROVIDER_CHOICES = (
        ('clickpesa', 'ClickPesa'),
        ('flutterwave', 'Flutterwave'),
    )

    goal = models.ForeignKey(SavingsGoal, on_delete=models.PROTECT, related_name='payments')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='payments')
    amount = models.BigIntegerField()
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    method = models.CharField(max_length=20, choices=PaymentMethod.choices)
    phone_number = models.CharField(max_length=12, null=True, blank=True)

    # Client-supplied idempotency key, also sent to the provider.
    order_reference = models.CharField(max_length=64, unique=True)
    provider = models.CharField(max_length=20, choices=PROVIDER_CHOICES)
    provider_reference = models.CharField(max_length=100, null=True, blank=True)
    provider_txn_id = models.CharField(max_length=100, null=True, blank=True)
    checkout_url = models.URLField(max_length=500, null=True, blank=True)

    status = models.CharField(max_length=20, choices=PaymentStatus.choices, default=PaymentStatus.PENDING,
                              db_index=True)
    failure_reason = models.CharField(max_length=255, null=True, blank=True)
    receipt_number = models.CharField(max_length=32, unique=True, null=True, blank=True)
    raw_webhook = models.JSONField(null=True, blank=True)
    settled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.order_reference} · {self.amount} {self.currency} · {self.status}"

    @property
    def is_final(self) -> bool:
        return self.status != PaymentStatus.PENDING


class Refund(TimeStampedModel):
    """Created when a goal is cancelled with money to return; processed by a Celery task."""
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    )

    goal = models.ForeignKey(SavingsGoal, on_delete=models.PROTECT, related_name='refunds')
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name='refunds')
    amount = models.BigIntegerField()
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    order_reference = models.CharField(max_length=64, unique=True)
    phone_number = models.CharField(max_length=12, null=True, blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', db_index=True)
    provider_reference = models.CharField(max_length=255, null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    failure_reason = models.TextField(null=True, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Refund {self.amount} {self.currency} for {self.goal_id} ({self.status})"
