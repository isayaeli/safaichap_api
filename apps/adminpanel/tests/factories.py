from apps.adminpanel.models import Role, StaffProfile
from apps.adminpanel.services import sync_rbac
from apps.core.tests.factories import make_user


def make_staff(username='staff-1', roles=('Super Admin',), **kwargs):
    sync_rbac()
    user = make_user(username, is_staff=True, email=f'{username}@safarichap.co.tz', **kwargs)
    profile = StaffProfile.objects.create(user=user)
    profile.roles.set(Role.objects.filter(name__in=roles))
    return user
