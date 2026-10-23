import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.choices import KycStatus, Residency
from apps.core.models import TimeStampedModel
from utils.encryption import EncryptedTextField
from utils.money import CURRENCY_CHOICES


class UserAccount(AbstractUser):
    """`username` is the Firebase uid."""
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    full_name = models.CharField(_("Full name"), max_length=150, null=True, blank=True)
    phone_number = models.CharField(max_length=20, null=True, blank=True)
    email = models.EmailField(_("Email Address"), null=True, blank=True)
    residency = models.CharField(max_length=20, choices=Residency.choices, null=True, blank=True)
    preferred_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, null=True, blank=True)
    country = models.CharField(max_length=2, default='TZ')
    kyc_status = models.CharField(max_length=20, choices=KycStatus.choices, default=KycStatus.NOT_REQUIRED)
    notifications_enabled = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.full_name or self.username


class DeviceToken(TimeStampedModel):
    PLATFORM_CHOICES = (
        ('android', 'android'),
        ('ios', 'ios'),
    )
    user = models.ForeignKey(UserAccount, on_delete=models.CASCADE, related_name="device_tokens")
    token = models.CharField(max_length=512, unique=True)
    platform = models.CharField(max_length=10, choices=PLATFORM_CHOICES)
    notifications_enabled = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.user} ({self.platform})"


class KycDocument(TimeStampedModel):
    DOCUMENT_TYPE_CHOICES = (
        ('nida', 'NIDA'),
        ('passport', 'Passport'),
    )
    user = models.ForeignKey(UserAccount, on_delete=models.CASCADE, related_name='kyc_documents')
    document_type = models.CharField(max_length=10, choices=DOCUMENT_TYPE_CHOICES)
    document_number = EncryptedTextField()
    status = models.CharField(max_length=20, choices=KycStatus.choices, default=KycStatus.PENDING)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.user} — {self.get_document_type_display()} ({self.status})"
