from django.conf import settings
from django.db import models

from apps.catalogue.models import Itinerary
from apps.core.models import TimeStampedModel


class WishlistItem(TimeStampedModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlist_items')
    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name='wishlisted_by')

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['user', 'itinerary'], name='unique_wishlist_item'),
        ]

    def __str__(self):
        return f"{self.user} ♥ {self.itinerary}"
