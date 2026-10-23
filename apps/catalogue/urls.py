from django.urls import path
from . import views

urlpatterns = [
    path('api/itineraries/', views.ItineraryListView.as_view(), name='itinerary-list'),
    path('api/itineraries/destinations/', views.DestinationListView.as_view(), name='destination-list'),
    path('api/itineraries/<uuid:itinerary_uuid>/', views.ItineraryDetailView.as_view(), name='itinerary-detail'),
]
