from rest_framework.pagination import PageNumberPagination


class AdminPagination(PageNumberPagination):
    """`?page=` and `?page_size=` (max 200). The dashboard reads `count` and `results`."""
    page_size = 25
    page_size_query_param = 'page_size'
    max_page_size = 200
