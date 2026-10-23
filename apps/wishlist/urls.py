from django.urls import path
from . import views

urlpatterns = [
    path('api/users/wishlist/', views.WishlistView.as_view(), name='wishlist'),
    path('api/users/wishlist/<uuid:itinerary_uuid>/', views.WishlistItemView.as_view(), name='wishlist-item'),
]
