from django.urls import path
from . import views

urlpatterns = [
    path('api/goals/', views.GoalListCreateView.as_view(), name='goal-list'),
    path('api/goals/quote/', views.GoalQuoteView.as_view(), name='goal-quote'),
    path('api/goals/<uuid:goal_uuid>/', views.GoalDetailView.as_view(), name='goal-detail'),
    path('api/goals/<uuid:goal_uuid>/activate/', views.GoalActivateView.as_view(), name='goal-activate'),
    path('api/goals/<uuid:goal_uuid>/reschedule/', views.GoalRescheduleView.as_view(), name='goal-reschedule'),
    path('api/goals/<uuid:goal_uuid>/cancellation-quote/', views.GoalCancellationQuoteView.as_view(),
         name='goal-cancellation-quote'),
    path('api/goals/<uuid:goal_uuid>/cancel/', views.GoalCancelView.as_view(), name='goal-cancel'),
    path('api/goals/<uuid:goal_uuid>/payments/', views.GoalPaymentsView.as_view(), name='goal-payments'),
]
