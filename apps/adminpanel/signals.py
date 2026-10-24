from django.db.models.signals import m2m_changed, post_delete, post_save
from django.dispatch import receiver

from .access import invalidate_permission_cache
from .models import Role, StaffProfile


@receiver([post_save, post_delete], sender=Role)
@receiver([post_save, post_delete], sender=StaffProfile)
def _role_or_staff_changed(**kwargs):
    invalidate_permission_cache()


@receiver(m2m_changed, sender=Role.permissions.through)
@receiver(m2m_changed, sender=StaffProfile.roles.through)
def _memberships_changed(action, **kwargs):
    if action in ('post_add', 'post_remove', 'post_clear'):
        invalidate_permission_cache()
