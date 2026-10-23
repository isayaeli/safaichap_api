from django.urls import path
from . import views

urlpatterns = [
    path('api/notifications/', views.NotificationListView.as_view(), name='notification-list'),
    path('api/notifications/read-all/', views.MarkAllNotificationsReadView.as_view(), name='notification-read-all'),
    path('api/notifications/<uuid:notification_uuid>/', views.NotificationDetailView.as_view(),
         name='notification-detail'),
    path('api/notifications/<uuid:notification_uuid>/read/', views.MarkNotificationReadView.as_view(),
         name='notification-read'),
]
