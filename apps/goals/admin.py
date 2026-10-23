from django.contrib import admin

from apps.payments.models import Payment
from .models import Installment, SavingsGoal, Traveller


class TravellerInline(admin.TabularInline):
    model = Traveller
    extra = 0
    can_delete = False
    readonly_fields = ('name', 'age_category', 'residency', 'position')

    def has_add_permission(self, request, obj=None):
        return False


class InstallmentInline(admin.TabularInline):
    model = Installment
    extra = 0
    can_delete = False
    fields = ('due_date', 'amount', 'amount_paid', 'status', 'is_deposit')
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 0
    can_delete = False
    fields = ('order_reference', 'amount', 'currency', 'method', 'status', 'receipt_number', 'created_at')
    readonly_fields = fields
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(SavingsGoal)
class SavingsGoalAdmin(admin.ModelAdmin):
    """Read-mostly: money fields are only changed by the payment flow."""
    list_display = ('title', 'user', 'status', 'currency', 'total_amount', 'amount_paid', 'travel_date',
                    'pay_by_date', 'created_at')
    list_filter = ('status', 'currency', 'frequency')
    search_fields = ('title', 'user__username', 'user__full_name', 'uuid')
    readonly_fields = (
        'uuid', 'user', 'itinerary', 'travel_date', 'pay_by_date', 'currency', 'total_amount', 'deposit_amount',
        'amount_paid', 'frequency', 'custom_days', 'status', 'consecutive_missed', 'completed_at',
        'cancellation_reason', 'locked_fx_numerator', 'locked_fx_denominator', 'locked_pricing_snapshot',
        'activated_at', 'created_at', 'updated_at',
    )
    inlines = [TravellerInline, InstallmentInline, PaymentInline]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
