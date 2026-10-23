from django.contrib import admin

from .models import WishlistItem


@admin.register(WishlistItem)
class WishlistItemAdmin(admin.ModelAdmin):
    list_display = ('user', 'itinerary', 'created_at')
    search_fields = ('user__username', 'itinerary__title')
