from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from apps.adminpanel.models import AuditLog, Role, StaffProfile
from apps.adminpanel.permissions import ALL_CODES, SYSTEM_ROLES
from apps.core.tests.factories import make_user
from apps.userauth.models import UserAccount
from .factories import make_staff


def client_for(user):
    """Fresh instance per client, like a real request (no stale cached staff_profile)."""
    client = APIClient()
    client.force_authenticate(UserAccount.objects.get(pk=user.pk))
    return client


class AccessTests(TestCase):
    def test_unauthenticated_is_401(self):
        self.assertEqual(APIClient().get('/api/admin/me/').status_code, 401)

    def test_customer_is_403(self):
        res = client_for(make_user()).get('/api/admin/me/')
        self.assertEqual(res.status_code, 403)

    def test_inactive_staff_is_403(self):
        staff = make_staff()
        StaffProfile.objects.filter(user=staff).update(is_active=False)
        self.assertEqual(client_for(staff).get('/api/admin/me/').status_code, 403)

    def test_me_lists_role_permissions(self):
        staff = make_staff(roles=('Finance',))
        res = client_for(staff).get('/api/admin/me/')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['permissions'], sorted(SYSTEM_ROLES['Finance'][1]))
        self.assertEqual([r['name'] for r in res.data['roles']], ['Finance'])

    def test_super_admin_has_every_code(self):
        res = client_for(make_staff()).get('/api/admin/me/')
        self.assertEqual(set(res.data['permissions']), set(ALL_CODES))

    def test_permission_matrix(self):
        content = client_for(make_staff('content', roles=('Content',)))
        finance = client_for(make_staff('finance', roles=('Finance',)))
        self.assertEqual(content.get('/api/admin/itineraries/').status_code, 200)
        self.assertEqual(content.get('/api/admin/payments/').status_code, 403)
        self.assertEqual(content.get('/api/admin/stats/').status_code, 403)
        self.assertEqual(finance.get('/api/admin/payments/').status_code, 200)
        self.assertEqual(finance.get('/api/admin/stats/').status_code, 200)
        self.assertEqual(finance.get('/api/admin/itineraries/').status_code, 403)
        self.assertEqual(finance.get('/api/admin/staff/').status_code, 403)
        # Viewer can read but not write.
        viewer = client_for(make_staff('viewer', roles=('Viewer',)))
        self.assertEqual(viewer.get('/api/admin/operators/').status_code, 200)
        self.assertEqual(viewer.post('/api/admin/operators/', {'name': 'X'}, format='json').status_code, 403)

    def test_role_change_applies_immediately(self):
        staff = make_staff(roles=('Content',))
        client = client_for(staff)
        self.assertEqual(client.get('/api/admin/payments/').status_code, 403)
        StaffProfile.objects.get(user=staff).roles.add(Role.objects.get(name='Finance'))
        self.assertEqual(client.get('/api/admin/payments/').status_code, 200)


class RoleTests(TestCase):
    def setUp(self):
        self.admin = make_staff()
        self.client = client_for(self.admin)

    def test_create_update_delete_custom_role(self):
        res = self.client.post('/api/admin/roles/', {'name': 'Auditor', 'description': 'Reads logs',
                                                     'permissions': ['audit.view']}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        uuid = res.data['uuid']
        res = self.client.patch(f'/api/admin/roles/{uuid}/', {'permissions': ['audit.view', 'users.view']},
                                format='json')
        self.assertEqual(sorted(res.data['permissions']), ['audit.view', 'users.view'])
        self.assertEqual(self.client.delete(f'/api/admin/roles/{uuid}/').status_code, 204)
        actions = list(AuditLog.objects.order_by('created_at').values_list('action', flat=True))
        self.assertEqual(actions, ['role.create', 'role.update', 'role.delete'])
        update = AuditLog.objects.get(action='role.update')
        self.assertEqual(update.before['permissions'], ['audit.view'])

    def test_unknown_permission_is_400(self):
        res = self.client.post('/api/admin/roles/', {'name': 'X', 'permissions': ['nope']}, format='json')
        self.assertEqual(res.status_code, 400)

    def test_system_roles_are_protected(self):
        super_admin = Role.objects.get(name='Super Admin')
        res = self.client.patch(f'/api/admin/roles/{super_admin.uuid}/', {'permissions': []}, format='json')
        self.assertEqual(res.status_code, 409)
        finance = Role.objects.get(name='Finance')
        self.assertEqual(self.client.delete(f'/api/admin/roles/{finance.uuid}/').status_code, 409)
        res = self.client.patch(f'/api/admin/roles/{finance.uuid}/', {'name': 'Money'}, format='json')
        self.assertEqual(res.status_code, 409)
        res = self.client.patch(f'/api/admin/roles/{finance.uuid}/', {'permissions': ['payments.view']},
                                format='json')
        self.assertEqual(res.status_code, 200)


class StaffTests(TestCase):
    def setUp(self):
        self.admin = make_staff()
        self.client = client_for(self.admin)

    @mock.patch('apps.adminpanel.views.rbac.password_setup_link', return_value='https://reset/link')
    @mock.patch('apps.adminpanel.views.rbac.get_or_create_firebase_user', return_value='new-uid')
    def test_invite(self, _uid, _link):
        support = Role.objects.get(name='Support')
        res = self.client.post('/api/admin/staff/', {'email': 'Neema@SafariChap.co.tz', 'full_name': 'Neema',
                                                     'roles': [str(support.uuid)]}, format='json')
        self.assertEqual(res.status_code, 201, res.data)
        self.assertEqual(res.data['password_link'], 'https://reset/link')
        user = UserAccount.objects.get(username='new-uid')
        self.assertTrue(user.is_staff)
        self.assertEqual(user.email, 'neema@safarichap.co.tz')
        self.assertEqual(list(user.staff_profile.roles.values_list('name', flat=True)), ['Support'])
        self.assertTrue(AuditLog.objects.filter(action='staff.invite').exists())
        # Inviting again is a conflict.
        res = self.client.post('/api/admin/staff/', {'email': 'neema@safarichap.co.tz', 'full_name': 'Neema',
                                                     'roles': [str(support.uuid)]}, format='json')
        self.assertEqual(res.status_code, 409)

    def test_cannot_lock_out_last_super_admin(self):
        profile = StaffProfile.objects.get(user=self.admin)
        res = self.client.patch(f'/api/admin/staff/{profile.uuid}/', {'is_active': False}, format='json')
        self.assertEqual(res.status_code, 409)
        res = self.client.patch(f'/api/admin/staff/{profile.uuid}/', {'roles': []}, format='json')
        self.assertEqual(res.status_code, 409)
        self.assertTrue(StaffProfile.objects.get(pk=profile.pk).roles.exists())

    def test_deactivate_and_remove_other_staff(self):
        other = make_staff('ops', roles=('Operations',))
        profile = StaffProfile.objects.get(user=other)
        res = self.client.patch(f'/api/admin/staff/{profile.uuid}/', {'is_active': False}, format='json')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(client_for(other).get('/api/admin/me/').status_code, 403)
        self.assertEqual(self.client.delete(f'/api/admin/staff/{profile.uuid}/').status_code, 204)
        other.refresh_from_db()
        self.assertFalse(other.is_staff)

    def test_audit_log_list_and_filter(self):
        self.client.post('/api/admin/roles/', {'name': 'A', 'permissions': []}, format='json')
        res = self.client.get('/api/admin/audit-logs/?action__startswith=role.')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['count'], 1)
        self.assertEqual(res.data['results'][0]['actor']['uuid'], str(self.admin.uuid))
