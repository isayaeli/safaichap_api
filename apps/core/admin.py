from django.contrib import admin

from .models import AppSetting, FxRate


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'default_lead_time_days', 'missed_before_pause', 'min_payment_tzs',
                    'min_payment_other_major', 'reminder_days_before_due', 'pending_payment_timeout_minutes')

    def has_add_permission(self, request):
        return not AppSetting.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FxRate)
class FxRateAdmin(admin.ModelAdmin):
    list_display = ('from_currency', 'to_currency', 'numerator', 'denominator', 'source', 'fetched_at')
    list_filter = ('from_currency', 'to_currency')
    ordering = ('-fetched_at',)
