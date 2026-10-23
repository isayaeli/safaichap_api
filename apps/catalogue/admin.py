from django.contrib import admin
from django.urls import reverse
from django.utils.html import format_html

from .models import (
    Destination, Itinerary, ItineraryDay, ItineraryDestination, ItineraryPricing, Operator, RefundPolicy, SeasonalAdjustment,
)


@admin.register(RefundPolicy)
class RefundPolicyAdmin(admin.ModelAdmin):
    list_display = ('name', 'processing_fee_bps', 'is_default')


@admin.register(Operator)
class OperatorAdmin(admin.ModelAdmin):
    list_display = ('name', 'lead_time_days', 'phone_number', 'email', 'refund_policy')
    search_fields = ('name',)


@admin.register(Destination)
class DestinationAdmin(admin.ModelAdmin):
    list_display = ('name', 'region')
    search_fields = ('name',)


class ItineraryDestinationInline(admin.TabularInline):
    model = ItineraryDestination
    extra = 0


class ItineraryDayInline(admin.TabularInline):
    model = ItineraryDay
    extra = 0


class ItineraryPricingInline(admin.StackedInline):
    model = ItineraryPricing
    can_delete = False
    readonly_fields = ('seasons_link',)

    @admin.display(description="Seasons")
    def seasons_link(self, obj):
        if not obj.pk:
            return "Save first, then add seasonal adjustments."
        url = reverse('admin:catalogue_itinerarypricing_change', args=[obj.pk])
        return format_html('<a href="{}">Edit {} seasonal adjustment(s)</a>', url, obj.seasonal_adjustments.count())


@admin.register(Itinerary)
class ItineraryAdmin(admin.ModelAdmin):
    list_display = ('title', 'operator', 'duration_days', 'accommodation_level', 'is_active', 'is_featured',
                    'sort_order')
    list_filter = ('is_active', 'is_featured', 'accommodation_level', 'operator')
    list_editable = ('is_active', 'is_featured', 'sort_order')
    search_fields = ('title', 'slug')
    prepopulated_fields = {'slug': ('title',)}
    inlines = [ItineraryDestinationInline, ItineraryPricingInline, ItineraryDayInline]


class SeasonalAdjustmentInline(admin.TabularInline):
    model = SeasonalAdjustment
    extra = 0


@admin.register(ItineraryPricing)
class ItineraryPricingAdmin(admin.ModelAdmin):
    list_display = ('itinerary', 'base_currency', 'resident_adult', 'non_resident_adult')
    inlines = [SeasonalAdjustmentInline]
