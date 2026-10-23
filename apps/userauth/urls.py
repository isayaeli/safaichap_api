from django.urls import path
from . import views

urlpatterns = [
    path('api/users/me/', views.CurrentUserAPIView.as_view(), name='current-user'),
    path('api/users/devices/', views.RegisterDeviceView.as_view(), name='register-device'),
    path('api/users/kyc/', views.SubmitKycView.as_view(), name='submit-kyc'),
]
