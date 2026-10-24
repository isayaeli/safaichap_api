import uuid

from django.conf import settings
from django.db import models

from apps.core.models import TimeStampedModel


class Permission(models.Model):
    """A dashboard permission code like `payments.reconcile`. Rows come from permissions.PERMISSIONS."""
    code = models.CharField(max_length=64, unique=True)
    label = models.CharField(max_length=150)
    group = models.CharField(max_length=50)

    class Meta:
        ordering = ['group', 'code']

    def __str__(self):
        return self.code


class Role(TimeStampedModel):
    name = models.CharField(max_length=80, unique=True)
    description = models.CharField(max_length=255, blank=True, default='')
    is_system = models.BooleanField(default=False, help_text="Seeded roles can't be renamed or deleted.")
    permissions = models.ManyToManyField(Permission, related_name='roles', blank=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class StaffProfile(TimeStampedModel):
    """Makes a UserAccount a dashboard user. Access is the union of the roles' permissions."""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='staff_profile')
    roles = models.ManyToManyField(Role, related_name='staff', blank=True)
    is_active = models.BooleanField(default=True)
    invited_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='+')
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"Staff: {self.user}"


class AuditLog(models.Model):
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')
    action = models.CharField(max_length=64, db_index=True, help_text="e.g. goal.pause, role.update")
    target_type = models.CharField(max_length=64, db_index=True)
    target_id = models.CharField(max_length=64, blank=True, default='', db_index=True)
    target_label = models.CharField(max_length=255, blank=True, default='')
    before = models.JSONField(null=True, blank=True)
    after = models.JSONField(null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.actor} {self.action} {self.target_type}:{self.target_id}"


class Broadcast(TimeStampedModel):
    """A notification staff sent to a group of customers (each recipient also gets a Notification row)."""
    title = models.CharField(max_length=255)
    message = models.TextField()
    audience = models.JSONField(default=dict, help_text='e.g. {"kind": "residency", "value": "resident"}')
    recipients = models.PositiveIntegerField(default=0)
    sent_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='+')

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title
