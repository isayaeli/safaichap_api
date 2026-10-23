from django.urls import path
from . import views

urlpatterns = [
    path('api/payments/', views.PaymentListView.as_view(), name='payment-list'),
    path('api/payments/initiate/', views.InitiatePaymentView.as_view(), name='payment-initiate'),
    path('api/payments/webhooks/clickpesa/', views.ClickPesaWebhookView.as_view(), name='clickpesa-webhook'),
    path('api/payments/webhooks/card/', views.CardWebhookView.as_view(), name='card-webhook'),
    path('api/payments/<uuid:payment_uuid>/', views.PaymentDetailView.as_view(), name='payment-detail'),
]
