import uuid

from django.db import models

from utils.money import CURRENCY_CHOICES


class TimeStampedModel(models.Model):
    """Every API object exposes `uuid`; integer PKs never leave the server."""
    uuid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class FxRate(TimeStampedModel):
    """
    One major unit of `from_currency` = numerator / denominator major units of
    `to_currency`. Rates are stored as TZS-per-unit (to_currency = TZS); cross
    rates are derived from those.
    """
    from_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES)
    to_currency = models.CharField(max_length=3, choices=CURRENCY_CHOICES, default='TZS')
    numerator = models.BigIntegerField()
    denominator = models.BigIntegerField(default=1)
    source = models.CharField(max_length=100, blank=True, default='')
    fetched_at = models.DateTimeField()

    class Meta:
        ordering = ['-fetched_at']
        indexes = [models.Index(fields=['from_currency', 'to_currency', '-fetched_at'])]

    def __str__(self):
        return f"1 {self.from_currency} = {self.numerator}/{self.denominator} {self.to_currency}"


DEFAULT_PACKING_LIST = """Neutral-coloured clothing (khaki, olive, beige)
Warm fleece for early morning drives
Wide-brim hat & sunglasses
Sunscreen SPF 50 & insect repellent
Binoculars
Camera + spare batteries / power bank
Comfortable closed walking shoes
Reusable water bottle
Personal medication & malaria prophylaxis
Passport / NIDA ID and a copy of this voucher"""


class AppSetting(models.Model):
    """Singleton of configurable business rules, editable in the admin."""
    default_lead_time_days = models.PositiveIntegerField(default=14)
    missed_before_pause = models.PositiveIntegerField(default=3)
    min_payment_tzs = models.PositiveIntegerField(default=5000, help_text="Minimum payment in TZS (whole shillings).")
    min_payment_other_major = models.PositiveIntegerField(
        default=10, help_text="Minimum payment in major units for USD/EUR/GBP.",
    )
    reminder_days_before_due = models.PositiveIntegerField(default=3)
    pending_payment_timeout_minutes = models.PositiveIntegerField(default=15)
    packing_list = models.TextField(default=DEFAULT_PACKING_LIST, help_text="One item per line.")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'App settings'
        verbose_name_plural = 'App settings'

    def __str__(self):
        return 'App settings'

    def save(self, *args, **kwargs):
        self.pk = 1
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def get(cls) -> 'AppSetting':
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def minimum_payment(self, currency: str) -> int:
        """Minimum payment in minor units of `currency`."""
        from utils.money import minor_per_major
        if currency == 'TZS':
            return self.min_payment_tzs
        return self.min_payment_other_major * minor_per_major(currency)
