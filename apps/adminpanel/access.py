"""
Who may do what in the dashboard. The backend is the authority; the dashboard
only hides what `GET /api/admin/me/` says the user can't do.
"""
from django.core.cache import cache
from rest_framework.permissions import SAFE_METHODS, BasePermission

from .permissions import ALL_CODES

_VERSION_KEY = 'adminperm:version'
_TTL = 60


def _version() -> int:
    return cache.get_or_set(_VERSION_KEY, 1, None)


def invalidate_permission_cache() -> None:
    """Call after any change to roles, role permissions or staff roles."""
    try:
        cache.incr(_VERSION_KEY)
    except ValueError:
        cache.set(_VERSION_KEY, 2, None)


def staff_profile(user):
    if not user or not user.is_authenticated or not user.is_staff:
        return None
    profile = getattr(user, 'staff_profile', None)
    if profile is None or not profile.is_active:
        return None
    return profile


def permission_codes(user) -> set[str]:
    """Union of the user's role permissions; every code for Django superusers. Empty for non-staff."""
    if staff_profile(user) is None:
        return set()
    if user.is_superuser:
        return set(ALL_CODES)
    key = f'adminperm:{_version()}:{user.pk}'
    codes = cache.get(key)
    if codes is None:
        from .models import Permission
        codes = list(
            Permission.objects.filter(roles__staff=user.staff_profile).values_list('code', flat=True).distinct()
        )
        cache.set(key, codes, _TTL)
    return set(codes)


def has_permission(user, code: str) -> bool:
    return code in permission_codes(user)


class HasAdminPermission(BasePermission):
    """
    Views set `view_permission` (safe methods) and `manage_permission` (writes),
    and may override per viewset action with `action_permissions = {'approve': 'kyc.review'}`.
    Not staff, or missing the code → 403. Unauthenticated stays 401 (FirebaseAuthentication).
    """
    message = "You don't have permission to do this."

    def required_code(self, request, view):
        action = getattr(view, 'action', None)
        overrides = getattr(view, 'action_permissions', {}) or {}
        if action in overrides:
            return overrides[action]
        if request.method in SAFE_METHODS:
            return getattr(view, 'view_permission', None)
        return getattr(view, 'manage_permission', None) or getattr(view, 'view_permission', None)

    def has_permission(self, request, view):
        user = request.user
        if not user or not user.is_authenticated:
            return False
        if staff_profile(user) is None:
            return False
        code = self.required_code(request, view)
        return code is None or has_permission(user, code)
