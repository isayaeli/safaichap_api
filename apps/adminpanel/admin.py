from django.contrib import admin

from .models import AuditLog, Broadcast, Permission, Role, StaffProfile


@admin.register(Permission)
class PermissionAdmin(admin.ModelAdmin):
    list_display = ('code', 'label', 'group')
    list_filter = ('group',)


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('name', 'is_system', 'description')
    filter_horizontal = ('permissions',)


@admin.register(StaffProfile)
class StaffProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_active', 'last_seen_at', 'created_at')
    list_filter = ('is_active', 'roles')
    filter_horizontal = ('roles',)
    raw_id_fields = ('user', 'invited_by')


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'actor', 'action', 'target_type', 'target_label')
    list_filter = ('action', 'target_type')
    search_fields = ('target_label', 'target_id', 'action')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(Broadcast)
class BroadcastAdmin(admin.ModelAdmin):
    list_display = ('title', 'recipients', 'sent', 'pushed', 'failed', 'sent_by', 'created_at')
