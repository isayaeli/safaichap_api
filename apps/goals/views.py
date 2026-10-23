from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalogue.models import Itinerary
from apps.core.choices import GoalStatus
from apps.payments.models import Payment
from apps.payments.serializers import PaymentSerializer
from utils.exceptions import BadRequest
from .models import Installment, SavingsGoal
from .serializers import CancelSerializer, PlanSerializer, RescheduleSerializer, SavingsGoalSerializer
from .services import goals as goal_service


def goals_for(user):
    return (
        SavingsGoal.objects.filter(user=user)
        .select_related('itinerary', 'booking')
        .prefetch_related('travellers', Prefetch('installments', queryset=Installment.objects.order_by('due_date')))
    )


def _fresh(user, goal_uuid):
    return goals_for(user).get(uuid=goal_uuid)


def _plan_from(data):
    itinerary = Itinerary.objects.select_related('operator', 'pricing').filter(uuid=data['itinerary_uuid']).first()
    if itinerary is None or not hasattr(itinerary, 'pricing'):
        raise BadRequest("This trip isn't available any more.")
    return goal_service.build_plan(
        itinerary=itinerary,
        travellers=[dict(t) for t in data['travellers']],
        travel_date=data['travel_date'],
        currency=data['currency'],
        frequency=data['frequency'],
        custom_days=data['custom_days'],
        deposit=data['deposit_amount'],
    )


class GoalListCreateView(APIView):
    """GET /api/goals/ (newest first, optional ?status=) · POST /api/goals/ (creates a draft)."""

    def get(self, request):
        goals = goals_for(request.user)
        status_filter = request.query_params.get('status')
        if status_filter:
            if status_filter not in GoalStatus.values:
                raise BadRequest("Unknown goal status.")
            goals = goals.filter(status=status_filter)
        return Response(SavingsGoalSerializer(goals, many=True).data)

    def post(self, request):
        serializer = PlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = _plan_from(serializer.validated_data)
        goal = goal_service.create_goal(request.user, plan, serializer.validated_data.get('title'))
        return Response(SavingsGoalSerializer(_fresh(request.user, goal.uuid)).data, status=status.HTTP_201_CREATED)


class GoalQuoteView(APIView):
    """POST /api/goals/quote/ — preview only, nothing is saved."""

    def post(self, request):
        serializer = PlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_plan_from(serializer.validated_data).quote_dict())


class GoalDetailView(APIView):
    """GET /api/goals/{uuid}/ · DELETE (drafts only)."""

    def get(self, request, goal_uuid):
        goal = get_object_or_404(goals_for(request.user), uuid=goal_uuid)
        return Response(SavingsGoalSerializer(goal).data)

    def delete(self, request, goal_uuid):
        goal_service.delete_draft(request.user, goal_uuid)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GoalActivateView(APIView):
    def post(self, request, goal_uuid):
        goal = goal_service.activate_goal(request.user, goal_uuid)
        return Response(SavingsGoalSerializer(_fresh(request.user, goal.uuid)).data)


class GoalRescheduleView(APIView):
    def post(self, request, goal_uuid):
        serializer = RescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        goal = goal_service.reschedule_goal(
            request.user, goal_uuid, serializer.validated_data['travel_date'],
            serializer.validated_data.get('frequency'),
        )
        return Response(SavingsGoalSerializer(_fresh(request.user, goal.uuid)).data)


class GoalCancellationQuoteView(APIView):
    def get(self, request, goal_uuid):
        goal = get_object_or_404(
            SavingsGoal.objects.select_related('itinerary__operator__refund_policy'), uuid=goal_uuid,
            user=request.user,
        )
        return Response(goal_service.cancellation_quote(goal))


class GoalCancelView(APIView):
    def post(self, request, goal_uuid):
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(goal_service.cancel_goal(request.user, goal_uuid, serializer.validated_data.get('reason')))


class GoalPaymentsView(APIView):
    """GET /api/goals/{uuid}/payments/ — newest first."""

    def get(self, request, goal_uuid):
        goal = get_object_or_404(SavingsGoal, uuid=goal_uuid, user=request.user)
        payments = Payment.objects.filter(goal=goal, user=request.user).select_related('goal')
        return Response(PaymentSerializer(payments, many=True).data)
