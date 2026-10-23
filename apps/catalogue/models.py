from django.db import models

from apps.core.choices import AccommodationLevel, AgeCategory, Residency
from apps.core.models import TimeStampedModel
from utils.money import CURRENCY_CHOICES


def default_refund_tiers():
    return [
        {"min_days": 61, "percentage": 90},
        {"min_days": 31, "percentage": 50},
        {"min_days": 0, "percentage": 0},
    ]


class RefundPolicy(TimeStampedModel):
    """
    Refund tiers by days left before travel. `tiers` is a list of
    {"min_days": N, "percentage": P}; the first tier with days_to_travel >= min_days wins.
    """
    name = models.CharField(max_length=100)
    tiers = models.JSONField(default=default_refund_tiers)
    processing_fee_bps = models.PositiveIntegerField(default=250, help_text="250 = 2.5% of the amount paid.")
    description = models.TextField(
        default="More than 60 days before travel: 90% refund. 31–60 days: 50%. "
                "30 days or less: no refund. A 2.5% processing fee applies.",
        help_text="Shown to users verbatim in the cancellation quote.",
    )
    is_default = models.BooleanField(default=False, help_text="Used for operators without their own policy.")

    class Meta:
        verbose_name_plural = 'Refund policies'

    def __str__(self):
        return self.name

    def percentage_for(self, days_to_travel: int) -> int:
        for tier in sorted(self.tiers, key=lambda t: t['min_days'], reverse=True):
            if days_to_travel >= tier['min_days']:
                return int(tier['percentage'])
        return 0


class Operator(TimeStampedModel):
    name = models.CharField(max_length=150)
    lead_time_days = models.PositiveIntegerField(null=True, blank=True, help_text="Empty = default (14).")
    phone_number = models.CharField(max_length=20, blank=True, default='')
    whatsapp = models.CharField(max_length=20, blank=True, default='')
    email = models.EmailField(blank=True, default='')
    refund_policy = models.ForeignKey(RefundPolicy, on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        return self.name


class Destination(TimeStampedModel):
    name = models.CharField(max_length=100, unique=True)
    region = models.CharField(max_length=100, blank=True, default='')
    image = models.URLField(max_length=500, blank=True, default='')

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Itinerary(TimeStampedModel):
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=200, unique=True)
    summary = models.TextField(blank=True, default='')
    destinations = models.ManyToManyField(Destination, related_name='itineraries', blank=True,
                                          through='ItineraryDestination')
    duration_days = models.PositiveIntegerField()
    accommodation_level = models.CharField(max_length=20, choices=AccommodationLevel.choices)
    inclusions = models.JSONField(default=list, blank=True)
    exclusions = models.JSONField(default=list, blank=True)
    images = models.JSONField(default=list, blank=True, help_text="List of image URLs; the first is the cover.")
    operator = models.ForeignKey(Operator, on_delete=models.PROTECT, related_name='itineraries')
    lead_time_days = models.PositiveIntegerField(
        null=True, blank=True, help_text="Overrides the operator's lead time for this trip.",
    )
    min_group_size = models.PositiveIntegerField(default=1)
    max_group_size = models.PositiveIntegerField(default=10)
    is_active = models.BooleanField(default=True)
    is_featured = models.BooleanField(default=False)
    sort_order = models.IntegerField(default=0, help_text="Lower comes first among featured/non-featured.")
    kyc_required = models.BooleanField(default=False, help_text="Ask travellers for NIDA/passport after booking.")

    class Meta:
        ordering = ['-is_featured', 'sort_order', '-created_at']
        verbose_name_plural = 'Itineraries'

    def __str__(self):
        return self.title

    def ordered_destination_names(self) -> list[str]:
        return [link.destination.name for link in self.destination_links.all()]

    def set_destinations(self, destinations) -> None:
        self.destination_links.all().delete()
        ItineraryDestination.objects.bulk_create([
            ItineraryDestination(itinerary=self, destination=d, position=i) for i, d in enumerate(destinations)
        ])

    @property
    def cover_image(self):
        return self.images[0] if self.images else None

    def effective_lead_time_days(self, default: int) -> int:
        if self.lead_time_days is not None:
            return self.lead_time_days
        if self.operator.lead_time_days is not None:
            return self.operator.lead_time_days
        return default


class ItineraryDestination(models.Model):
    """Keeps destinations in itinerary order (the first is the main one)."""
    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name='destination_links')
    destination = models.ForeignKey(Destination, on_delete=models.CASCADE)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['position', 'id']
        constraints = [
            models.UniqueConstraint(fields=['itinerary', 'destination'], name='unique_itinerary_destination'),
        ]

    def __str__(self):
        return f"{self.itinerary} → {self.destination}"


class ItineraryDay(models.Model):
    itinerary = models.ForeignKey(Itinerary, on_delete=models.CASCADE, related_name='days')
    day_number = models.PositiveIntegerField()
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    location = models.CharField(max_length=100, blank=True, default='')
    meals = models.JSONField(default=list, blank=True)
    accommodation = models.CharField(max_length=200, blank=True, default='')

    class Meta:
        ordering = ['day_number']
        constraints = [
            models.UniqueConstraint(fields=['itinerary', 'day_number'], name='unique_itinerary_day'),
        ]

    def __str__(self):
        return f"Day {self.day_number}: {self.title}"


class ItineraryPricing(TimeStampedModel):
    """Per-person prices in minor units of `base_currency`."""
    itinerary = models.OneToOneField(Itinerary, on_delete=models.CASCADE, related_name='pricing')
    base_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    resident_adult = models.BigIntegerField()
    resident_child = models.BigIntegerField()
    non_resident_adult = models.BigIntegerField()
    non_resident_child = models.BigIntegerField()

    def __str__(self):
        return f"Pricing for {self.itinerary}"

    def price_for(self, residency: str, age_category: str) -> int:
        return getattr(self, f"{residency}_{age_category}")

    def to_dict(self) -> dict:
        """Same shape as the API `pricing` object; also used as the price-lock snapshot."""
        return {
            'base_currency': self.base_currency,
            'resident_adult': self.resident_adult,
            'resident_child': self.resident_child,
            'non_resident_adult': self.non_resident_adult,
            'non_resident_child': self.non_resident_child,
            'seasonal_adjustments': [
                {
                    'start_date': a.start_date.isoformat(),
                    'end_date': a.end_date.isoformat(),
                    'multiplier_bps': a.multiplier_bps,
                    'label': a.label,
                }
                for a in self.seasonal_adjustments.all()
            ],
        }


class SeasonalAdjustment(models.Model):
    """Inclusive date range. If ranges overlap, the first by start_date wins."""
    pricing = models.ForeignKey(ItineraryPricing, on_delete=models.CASCADE, related_name='seasonal_adjustments')
    start_date = models.DateField()
    end_date = models.DateField()
    multiplier_bps = models.PositiveIntegerField(help_text="10000 = 1.0×, 12000 = +20%.")
    label = models.CharField(max_length=100)

    class Meta:
        ordering = ['start_date', 'id']

    def __str__(self):
        return f"{self.label} ({self.start_date} – {self.end_date})"


RESIDENCY_ORDER = [Residency.RESIDENT, Residency.NON_RESIDENT]
AGE_ORDER = [AgeCategory.ADULT, AgeCategory.CHILD]
