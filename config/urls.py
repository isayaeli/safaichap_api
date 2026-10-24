from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.http import HttpResponse
from django.urls import path, include
from rest_framework import permissions
from rest_framework.authentication import SessionAuthentication
from drf_yasg.views import get_schema_view
from drf_yasg import openapi

from apps.userauth.authentication import FirebaseAuthentication
from utils.api_docs import API_DESCRIPTION, ApiSchemaGenerator


def health_check(request):
    return HttpResponse("OK")


# Public in development; staff-only (admin session) in production.
schema_view = get_schema_view(
    openapi.Info(
        title="SafariChap API",
        default_version='v1',
        description=API_DESCRIPTION,
    ),
    generator_class=ApiSchemaGenerator,
    public=settings.DEBUG,
    permission_classes=(permissions.AllowAny,) if settings.DEBUG else (permissions.IsAdminUser,),
    authentication_classes=(SessionAuthentication, FirebaseAuthentication),
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include("apps.userauth.urls")),
    path('', include("apps.wishlist.urls")),
    path('', include("apps.catalogue.urls")),
    path('', include("apps.goals.urls")),
    path('', include("apps.payments.urls")),
    path('', include("apps.bookings.urls")),
    path('', include("apps.notifications.urls")),
    path('', include("apps.adminpanel.urls")),
    path('swagger/', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

    path('health/', health_check),
    path('health', health_check),

    path('', include('django_prometheus.urls')),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
