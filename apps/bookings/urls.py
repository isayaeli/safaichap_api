from django.urls import path
from . import views

urlpatterns = [
    path('api/bookings/', views.BookingListView.as_view(), name='booking-list'),
    path('api/bookings/<uuid:booking_uuid>/', views.BookingDetailView.as_view(), name='booking-detail'),
]
