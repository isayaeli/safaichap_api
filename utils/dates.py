from django.utils import timezone


def today():
    """Today's date in Africa/Dar_es_Salaam (settings.TIME_ZONE)."""
    return timezone.localdate()
