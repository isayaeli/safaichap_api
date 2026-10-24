from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import catalogue, ops, rbac, system

router = DefaultRouter(trailing_slash=True)
router.include_root_view = False
router.register('roles', rbac.RoleViewSet, basename='admin-roles')
router.register('staff', rbac.StaffViewSet, basename='admin-staff')
router.register('audit-logs', rbac.AuditLogViewSet, basename='admin-audit-logs')
router.register('users', ops.UserViewSet, basename='admin-users')
router.register('kyc', ops.KycViewSet, basename='admin-kyc')
router.register('goals', ops.GoalViewSet, basename='admin-goals')
router.register('payments', ops.PaymentViewSet, basename='admin-payments')
router.register('refunds', ops.RefundViewSet, basename='admin-refunds')
router.register('bookings', ops.BookingViewSet, basename='admin-bookings')
router.register('trip-documents', ops.TripDocumentViewSet, basename='admin-trip-documents')
router.register('notifications', ops.NotificationViewSet, basename='admin-notifications')
router.register('broadcasts', ops.BroadcastViewSet, basename='admin-broadcasts')
router.register('refund-policies', catalogue.RefundPolicyViewSet, basename='admin-refund-policies')
router.register('operators', catalogue.OperatorViewSet, basename='admin-operators')
router.register('destinations', catalogue.DestinationViewSet, basename='admin-destinations')
router.register('itineraries', catalogue.ItineraryViewSet, basename='admin-itineraries')
router.register('fx-rates', system.FxRateViewSet, basename='admin-fx-rates')

urlpatterns = [
    path('api/admin/me/', rbac.MeView.as_view(), name='admin-me'),
    path('api/admin/permissions/', rbac.PermissionListView.as_view(), name='admin-permissions'),
    path('api/admin/stats/', system.StatsView.as_view(), name='admin-stats'),
    path('api/admin/settings/', system.AppSettingView.as_view(), name='admin-settings'),
    path('api/admin/uploads/', system.UploadView.as_view(), name='admin-uploads'),
    path('api/admin/', include(router.urls)),
]
