from django.db import models

from apps.core.choices import BookingStatus, TripDocumentType
from apps.core.models import TimeStampedModel
from apps.goals.models import SavingsGoal


class Booking(TimeStampedModel):
    goal = models.OneToOneField(SavingsGoal, on_delete=models.PROTECT, related_name='booking')
    confirmation_code = models.CharField(max_length=16, unique=True)
    status = models.CharField(max_length=20, choices=BookingStatus.choices, default=BookingStatus.CONFIRMED)
    travel_date = models.DateField()

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.confirmation_code


class TripDocument(TimeStampedModel):
    booking = models.ForeignKey(Booking, on_delete=models.CASCADE, related_name='documents')
    type = models.CharField(max_length=30, choices=TripDocumentType.choices)
    title = models.CharField(max_length=200)
    url = models.URLField(max_length=500, null=True, blank=True)
    content = models.TextField(null=True, blank=True, help_text="Packing lists: one item per line.")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']

    def __str__(self):
        return f"{self.booking} · {self.title}"
