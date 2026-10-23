from django.contrib import admin

from .models import Payment, Refund


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ('order_reference', 'user', 'goal', 'amount', 'currency', 'method', 'status', 'receipt_number',
                    'created_at')
    list_filter = ('status', 'method', 'currency', 'provider')
    search_fields = ('order_reference', 'receipt_number', 'provider_reference', 'phone_number', 'user__username')
    readonly_fields = [f.name for f in Payment._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Refund)
class RefundAdmin(admin.ModelAdmin):
    list_display = ('order_reference', 'user', 'goal', 'amount', 'currency', 'status', 'attempts', 'processed_at')
    list_filter = ('status', 'currency')
    search_fields = ('order_reference', 'user__username')
    readonly_fields = ('goal', 'user', 'amount', 'currency', 'order_reference', 'provider_reference', 'attempts',
                       'processed_at', 'created_at')
    actions = ['retry']

    def has_add_permission(self, request):
        return False

    @admin.action(description="Retry selected refunds now")
    def retry(self, request, queryset):
        from .tasks import process_refunds
        queryset.filter(status='failed').update(status='pending')
        process_refunds.delay()
        self.message_user(request, "Refunds queued.")
