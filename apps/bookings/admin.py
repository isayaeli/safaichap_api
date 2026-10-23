from django.contrib import admin

from .models import Booking, TripDocument


class TripDocumentInline(admin.StackedInline):
    model = TripDocument
    extra = 0


@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ('confirmation_code', 'goal', 'status', 'travel_date', 'created_at')
    list_filter = ('status',)
    search_fields = ('confirmation_code', 'goal__title', 'goal__user__username')
    readonly_fields = ('uuid', 'goal', 'confirmation_code', 'created_at')
    inlines = [TripDocumentInline]
