from rest_framework import serializers

from apps.userauth.models import UserAccount
from ..models import AuditLog, Permission, Role, StaffProfile


class PermissionSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminPermission'
        model = Permission
        fields = ['code', 'label', 'group']


class RoleRefSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminRoleRef'
        model = Role
        fields = ['uuid', 'name']


class RoleSerializer(serializers.ModelSerializer):
    permissions = serializers.SlugRelatedField(slug_field='code', many=True, queryset=Permission.objects.all())
    staff_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        ref_name = 'AdminRole'
        model = Role
        fields = ['uuid', 'name', 'description', 'is_system', 'permissions', 'staff_count', 'created_at',
                  'updated_at']
        read_only_fields = ['uuid', 'is_system', 'created_at', 'updated_at']


class StaffUserSerializer(serializers.ModelSerializer):
    class Meta:
        ref_name = 'AdminStaffUser'
        model = UserAccount
        fields = ['uuid', 'full_name', 'email', 'phone_number']


class StaffSerializer(serializers.ModelSerializer):
    user = StaffUserSerializer(read_only=True)
    roles = RoleRefSerializer(many=True, read_only=True)
    invited_by = serializers.SerializerMethodField()

    class Meta:
        ref_name = 'AdminStaff'
        model = StaffProfile
        fields = ['uuid', 'user', 'roles', 'is_active', 'last_seen_at', 'invited_by', 'created_at']

    def get_invited_by(self, obj):
        return str(obj.invited_by) if obj.invited_by_id else None


class StaffInviteSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminStaffInvite'

    email = serializers.EmailField()
    full_name = serializers.CharField(max_length=150)
    roles = serializers.SlugRelatedField(slug_field='uuid', many=True, queryset=Role.objects.all())


class StaffUpdateSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminStaffUpdate'

    full_name = serializers.CharField(max_length=150, required=False)
    roles = serializers.SlugRelatedField(slug_field='uuid', many=True, queryset=Role.objects.all(), required=False)
    is_active = serializers.BooleanField(required=False)


class AuditLogSerializer(serializers.ModelSerializer):
    actor = serializers.SerializerMethodField()

    class Meta:
        ref_name = 'AdminAuditLog'
        model = AuditLog
        fields = ['uuid', 'actor', 'action', 'target_type', 'target_id', 'target_label', 'before', 'after',
                  'ip_address', 'created_at']

    def get_actor(self, obj):
        if not obj.actor_id:
            return None
        return {'uuid': str(obj.actor.uuid), 'full_name': obj.actor.full_name, 'email': obj.actor.email}


class MeSerializer(serializers.Serializer):
    class Meta:
        ref_name = 'AdminMe'

    user = StaffUserSerializer()
    roles = RoleRefSerializer(many=True)
    permissions = serializers.ListField(child=serializers.CharField())
