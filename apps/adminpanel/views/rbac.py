from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from drf_yasg.utils import swagger_auto_schema
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.userauth.models import UserAccount
from utils.exceptions import BadRequest, Conflict
from ..access import HasAdminPermission, permission_codes, staff_profile
from ..models import AuditLog, Permission, Role, StaffProfile
from ..permissions import SUPER_ADMIN
from ..serializers.rbac import (
    AuditLogSerializer, MeSerializer, PermissionSerializer, RoleSerializer, StaffInviteSerializer,
    StaffSerializer, StaffUpdateSerializer,
)
from ..services import audit
from ..utils_firebase import get_or_create_firebase_user, password_setup_link
from .base import AdminAPIView, AdminViewMixin


class MeView(APIView):
    """GET /api/admin/me/ — the signed-in staff member, their roles and permission codes."""
    permission_classes = [HasAdminPermission]

    @swagger_auto_schema(operation_summary="My staff profile and permissions", responses={200: MeSerializer})
    def get(self, request):
        profile = staff_profile(request.user)
        StaffProfile.objects.filter(pk=profile.pk).update(last_seen_at=timezone.now())
        return Response(MeSerializer({
            'user': request.user,
            'roles': profile.roles.all(),
            'permissions': sorted(permission_codes(request.user)),
        }).data)


class PermissionListView(AdminAPIView):
    view_permission = 'roles.view'

    @swagger_auto_schema(operation_summary="All permission codes", responses={200: PermissionSerializer(many=True)})
    def get(self, request):
        return Response(PermissionSerializer(Permission.objects.all(), many=True).data)


def _role_state(role):
    return {'name': role.name, 'description': role.description,
            'permissions': sorted(role.permissions.values_list('code', flat=True))}


def _active_super_admins():
    return StaffProfile.objects.filter(is_active=True, roles__name=SUPER_ADMIN).distinct()


class RoleViewSet(AdminViewMixin, viewsets.ModelViewSet):
    serializer_class = RoleSerializer
    lookup_field = 'uuid'
    view_permission = 'roles.view'
    manage_permission = 'roles.manage'
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    pagination_class = None

    def get_queryset(self):
        return Role.objects.prefetch_related('permissions').annotate(staff_count=Count('staff', distinct=True))

    def perform_create(self, serializer):
        role = serializer.save()
        audit(self.request, 'role.create', role, after=_role_state(role))

    def perform_update(self, serializer):
        role = serializer.instance
        if role.name == SUPER_ADMIN:
            raise Conflict("The Super Admin role always has every permission.")
        if role.is_system and serializer.validated_data.get('name', role.name) != role.name:
            raise Conflict("Built-in roles can't be renamed.")
        before = _role_state(role)
        role = serializer.save()
        audit(self.request, 'role.update', role, before=before, after=_role_state(role))

    def perform_destroy(self, role):
        if role.is_system:
            raise Conflict("Built-in roles can't be deleted.")
        audit(self.request, 'role.delete', role, before=_role_state(role))
        role.delete()


def _staff_state(profile):
    return {'full_name': profile.user.full_name, 'email': profile.user.email, 'is_active': profile.is_active,
            'roles': sorted(profile.roles.values_list('name', flat=True))}


class StaffViewSet(AdminViewMixin, viewsets.ModelViewSet):
    lookup_field = 'uuid'
    view_permission = 'staff.view'
    manage_permission = 'staff.manage'
    search_fields = ['user__full_name', 'user__email', 'user__phone_number']
    filterset_fields = ['is_active', 'roles__uuid']
    ordering_fields = ['created_at', 'last_seen_at', 'user__full_name']
    http_method_names = ['get', 'post', 'patch', 'delete']

    def get_queryset(self):
        return StaffProfile.objects.select_related('user', 'invited_by').prefetch_related('roles').distinct()

    def get_serializer_class(self):
        if self.action == 'create':
            return StaffInviteSerializer
        if self.action == 'partial_update':
            return StaffUpdateSerializer
        return StaffSerializer

    @swagger_auto_schema(operation_summary="Invite a staff member",
                         operation_description="Creates (or reuses) the Firebase user for the email and returns "
                                               "`password_link`, which is also emailed to them.",
                         request_body=StaffInviteSerializer, responses={201: StaffSerializer})
    def create(self, request, *args, **kwargs):
        data = StaffInviteSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        email = data.validated_data['email'].lower()
        full_name = data.validated_data['full_name'].strip()

        uid = get_or_create_firebase_user(email, full_name)
        with transaction.atomic():
            user, _ = UserAccount.objects.get_or_create(username=uid, defaults={'email': email})
            if StaffProfile.objects.filter(user=user).exists():
                raise Conflict("This person is already on the staff list.")
            user.email = user.email or email
            user.full_name = user.full_name or full_name
            user.is_staff = True
            user.save(update_fields=['email', 'full_name', 'is_staff', 'updated_at'])
            profile = StaffProfile.objects.create(user=user, invited_by=request.user)
            profile.roles.set(data.validated_data['roles'])
            audit(request, 'staff.invite', profile, after=_staff_state(profile), label=email)

        link = password_setup_link(email)
        if link:
            send_mail(
                "You've been invited to the SafariChap dashboard",
                f"Hi {full_name},\n\nSet your password here, then sign in to the dashboard:\n{link}\n",
                None, [email], fail_silently=True,
            )
        body = StaffSerializer(profile).data
        body['password_link'] = link
        return Response(body, status=status.HTTP_201_CREATED)

    @swagger_auto_schema(operation_summary="Change a staff member's roles, name or access",
                         request_body=StaffUpdateSerializer, responses={200: StaffSerializer})
    def partial_update(self, request, *args, **kwargs):
        profile = self.get_object()
        data = StaffUpdateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        values = data.validated_data
        before = _staff_state(profile)

        with transaction.atomic():
            if 'full_name' in values:
                profile.user.full_name = values['full_name'].strip()
                profile.user.save(update_fields=['full_name', 'updated_at'])
            if 'is_active' in values:
                if profile.user_id == request.user.pk and not values['is_active']:
                    raise Conflict("You can't deactivate yourself.")
                profile.is_active = values['is_active']
                profile.save(update_fields=['is_active', 'updated_at'])
            if 'roles' in values:
                profile.roles.set(values['roles'])
            if not _active_super_admins().exists():
                raise Conflict("At least one active Super Admin must remain.")
            audit(request, 'staff.update', profile, before=before, after=_staff_state(profile))
        return Response(StaffSerializer(profile).data)

    def destroy(self, request, *args, **kwargs):
        """Removes dashboard access. The person's customer account (if any) stays."""
        profile = self.get_object()
        if profile.user_id == request.user.pk:
            raise Conflict("You can't remove yourself.")
        with transaction.atomic():
            before = _staff_state(profile)
            user = profile.user
            profile.delete()
            user.is_staff = False
            user.save(update_fields=['is_staff', 'updated_at'])
            if not _active_super_admins().exists():
                raise Conflict("At least one active Super Admin must remain.")
            audit(request, 'staff.remove', target_type='staffprofile', target_id=str(profile.uuid),
                  label=user.email or str(user), before=before)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AuditLogViewSet(AdminViewMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = AuditLogSerializer
    lookup_field = 'uuid'
    view_permission = 'audit.view'
    search_fields = ['action', 'target_label', 'target_id', 'actor__full_name', 'actor__email']
    filterset_fields = {
        'action': ['exact', 'startswith'],
        'target_type': ['exact'],
        'target_id': ['exact'],
        'actor__uuid': ['exact'],
        'created_at': ['gte', 'lte'],
    }
    ordering_fields = ['created_at']

    def get_queryset(self):
        return AuditLog.objects.select_related('actor')
