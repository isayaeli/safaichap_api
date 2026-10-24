import datetime
import decimal
import uuid

from django.db import transaction
from django.forms.models import model_to_dict

from .models import AuditLog, Permission, Role
from .permissions import PERMISSIONS, SUPER_ADMIN, SYSTEM_ROLES


def _jsonable(value):
    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()
    if isinstance(value, (uuid.UUID, decimal.Decimal)):
        return str(value)
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if hasattr(value, 'pk'):
        return str(value.pk)
    return value


def snapshot(obj, fields: list[str] | None = None) -> dict | None:
    """Plain-JSON copy of a model instance for the audit log (secrets are never in `fields`)."""
    if obj is None:
        return None
    data = model_to_dict(obj, fields=fields)
    if fields is None:
        data.pop('password', None)
    for name in ('uuid', 'created_at', 'updated_at'):
        if (fields is None or name in fields) and hasattr(obj, name):
            data[name] = getattr(obj, name)
    return _jsonable(data)


def _client_ip(request):
    if request is None:
        return None
    forwarded = request.META.get('HTTP_X_FORWARDED_FOR')
    if forwarded:
        return forwarded.split(',')[-1].strip() or None
    return request.META.get('REMOTE_ADDR')


def audit(request, action: str, obj=None, before: dict | None = None, after: dict | None = None,
          target_type: str | None = None, target_id: str | None = None, label: str | None = None) -> AuditLog:
    """Records one staff action. Call it from every mutating admin view."""
    if obj is not None:
        target_type = target_type or obj._meta.model_name
        target_id = target_id or str(getattr(obj, 'uuid', None) or obj.pk)
        label = label or str(obj)[:255]
    return AuditLog.objects.create(
        actor=request.user if request is not None and request.user.is_authenticated else None,
        action=action, target_type=target_type or '', target_id=target_id or '', target_label=label or '',
        before=_jsonable(before), after=_jsonable(after), ip_address=_client_ip(request),
    )


@transaction.atomic
def sync_rbac() -> None:
    """
    Upserts every permission code and the system roles. Super Admin always gets every code; the other
    system roles get their defaults only when first created, so edits made in the dashboard survive.
    """
    codes = {code for code, _, _ in PERMISSIONS}
    for code, label, group in PERMISSIONS:
        Permission.objects.update_or_create(code=code, defaults={'label': label, 'group': group})
    Permission.objects.exclude(code__in=codes).delete()

    for name, (description, role_codes) in SYSTEM_ROLES.items():
        role, created = Role.objects.get_or_create(name=name, defaults={'description': description, 'is_system': True})
        if created or name == SUPER_ADMIN:
            role.permissions.set(Permission.objects.filter(code__in=role_codes))
