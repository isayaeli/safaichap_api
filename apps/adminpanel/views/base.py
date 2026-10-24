from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters
from rest_framework.views import APIView

from ..access import HasAdminPermission
from ..pagination import AdminPagination


class AdminViewMixin:
    """Every /api/admin/ view: Firebase auth (default), staff role check, pagination, search and ordering."""
    permission_classes = [HasAdminPermission]
    pagination_class = AdminPagination
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    view_permission = None
    manage_permission = None
    action_permissions = {}


class AdminAPIView(APIView):
    """Plain (non-list) admin endpoint: staff role check only."""
    permission_classes = [HasAdminPermission]
    view_permission = None
    manage_permission = None
