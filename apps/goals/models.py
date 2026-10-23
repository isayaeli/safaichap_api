from django.conf import settings
from django.db import models

from apps.catalogue.models import Itinerary
from apps.core.choices import AgeCategory, GoalStatus, InstallmentStatus, PaymentFrequency, Residency
from apps.core.models import TimeStampedModel
from utils.money import CURRENCY_CHOICES


class SavingsGoal(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='goals')
    itinerary = models.ForeignKey(Itinerary, on_delete=models.PROTECT, related_name='goals')
    title = models.CharField(max_length=200)

    travel_date = models.DateField()
    pay_by_date = models.DateField()

    # Money: integers in minor units of `currency`. The currency never changes.
    currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    total_amount = models.BigIntegerField()
    deposit_amount = models.BigIntegerField(default=0)
    amount_paid = models.BigIntegerField(default=0)

    frequency = models.CharField(max_length=20, choices=PaymentFrequency.choices, default=PaymentFrequency.MONTHLY)
    custom_days = models.PositiveIntegerField(default=30)

    status = models.CharField(max_length=20, choices=GoalStatus.choices, default=GoalStatus.DRAFT, db_index=True)
    consecutive_missed = models.PositiveIntegerField(default=0)
    completed_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(null=True, blank=True)

    # Locked at activation: after this, itinerary price or FX changes never touch the goal.
    locked_fx_numerator = models.BigIntegerField(null=True, blank=True)
    locked_fx_denominator = models.BigIntegerField(null=True, blank=True)
    locked_pricing_snapshot = models.JSONField(null=True, blank=True)
    activated_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.user}) — {self.status}"

    @property
    def remaining(self) -> int:
        return max(0, self.total_amount - self.amount_paid)


class Traveller(models.Model):
    goal = models.ForeignKey(SavingsGoal, on_delete=models.CASCADE, related_name='travellers')
    name = models.CharField(max_length=150)
    age_category = models.CharField(max_length=10, choices=AgeCategory.choices)
    residency = models.CharField(max_length=20, choices=Residency.choices)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return self.name


class Installment(TimeStampedModel):
    goal = models.ForeignKey(SavingsGoal, on_delete=models.CASCADE, related_name='installments')
    due_date = models.DateField()
    amount = models.BigIntegerField()
    amount_paid = models.BigIntegerField(default=0)
    status = models.CharField(max_length=20, choices=InstallmentStatus.choices, default=InstallmentStatus.UPCOMING)
    is_deposit = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['due_date', 'position']

    def __str__(self):
        return f"{self.goal_id} · {self.due_date} · {self.amount_paid}/{self.amount} ({self.status})"
