from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.choices import KycStatus
from .models import DeviceToken, KycDocument, UserAccount


@admin.register(UserAccount)
class CustomUserAdmin(UserAdmin):
    model = UserAccount
    list_display = ('username', 'full_name', 'phone_number', 'email', 'residency', 'preferred_currency', 'kyc_status')
    list_filter = UserAdmin.list_filter + ('residency', 'kyc_status')
    search_fields = ('username', 'full_name', 'phone_number', 'email')

    fieldsets = UserAdmin.fieldsets + (
        (_('SafariChap profile'), {'fields': ('full_name', 'phone_number', 'residency', 'preferred_currency',
                                               'country', 'kyc_status', 'notifications_enabled')}),
    )


@admin.register(DeviceToken)
class DeviceTokenAdmin(admin.ModelAdmin):
    list_display = ('user', 'platform', 'notifications_enabled', 'updated_at')
    list_filter = ('platform', 'notifications_enabled')
    search_fields = ('user__username', 'user__full_name')


@admin.register(KycDocument)
class KycDocumentAdmin(admin.ModelAdmin):
    """Document numbers are only visible to users with the change permission."""
    list_display = ('user', 'document_type', 'status', 'created_at', 'reviewed_at')
    list_filter = ('document_type', 'status')
    search_fields = ('user__username', 'user__full_name')
    readonly_fields = ('user', 'document_type', 'status', 'reviewed_at', 'created_at')
    actions = ['mark_verified', 'mark_rejected']

    def get_fields(self, request, obj=None):
        fields = ['user', 'document_type', 'status', 'reviewed_at', 'created_at']
        if self.has_change_permission(request, obj):
            fields.insert(2, 'document_number')
        return fields

    def get_readonly_fields(self, request, obj=None):
        return self.readonly_fields + (('document_number',) if obj else ())

    def has_add_permission(self, request):
        return False

    def _review(self, request, queryset, new_status):
        now = timezone.now()
        for doc in queryset.select_related('user'):
            doc.status = new_status
            doc.reviewed_at = now
            doc.save(update_fields=['status', 'reviewed_at', 'updated_at'])
            UserAccount.objects.filter(pk=doc.user_id).update(kyc_status=new_status)
        self.message_user(request, f"{queryset.count()} document(s) marked {new_status}.", messages.SUCCESS)

    @admin.action(description="Mark selected documents verified")
    def mark_verified(self, request, queryset):
        self._review(request, queryset, KycStatus.VERIFIED)

    @admin.action(description="Mark selected documents rejected")
    def mark_rejected(self, request, queryset):
        self._review(request, queryset, KycStatus.REJECTED)
