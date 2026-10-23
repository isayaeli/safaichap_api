from rest_framework.pagination import PageNumberPagination


class ItineraryPagination(PageNumberPagination):
    """The app reads the standard `results` key; don't rename it."""
    page_size = 10
