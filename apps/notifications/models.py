from django.conf import settings
from django.db import models

from apps.core.choices import NotificationType
from apps.core.models import TimeStampedModel


class Notification(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='notifications')
    goal = models.ForeignKey('goals.SavingsGoal', on_delete=models.SET_NULL, null=True, blank=True,
                             related_name='notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    type = models.CharField(max_length=30, choices=NotificationType.choices)
    is_read = models.BooleanField(default=False)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"To {self.user}: {self.title}"
