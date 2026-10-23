from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from drf_yasg import openapi
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalogue.models import Itinerary
from apps.core.choices import GoalStatus
from apps.payments.models import Payment
from apps.payments.serializers import PaymentSerializer
from utils.api_docs import CONFLICT, NOT_FOUND, VALIDATION_ERROR, rate_limit_note
from utils.exceptions import BadRequest
from .models import Installment, SavingsGoal
from .serializers import (
    CancellationQuoteSerializer, CancelSerializer, PlanSerializer, QuoteSerializer, RescheduleSerializer,
    SavingsGoalSerializer,
)
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
    throttle_scope = 'goal_changes'

    @swagger_auto_schema(
        operation_summary="List goals",
        operation_description="The user's goals, newest first, each with its full installment schedule. Not paginated.",
        manual_parameters=[openapi.Parameter('status', openapi.IN_QUERY, type=openapi.TYPE_STRING,
                                             enum=GoalStatus.values, description="Only goals in this status.")],
        responses={200: SavingsGoalSerializer(many=True), 400: VALIDATION_ERROR},
    )
    def get(self, request):
        goals = goals_for(request.user)
        status_filter = request.query_params.get('status')
        if status_filter:
            if status_filter not in GoalStatus.values:
                raise BadRequest("Unknown goal status.")
            goals = goals.filter(status=status_filter)
        return Response(SavingsGoalSerializer(goals, many=True).data)

    @swagger_auto_schema(
        operation_summary="Create a draft goal",
        operation_description=(
            "Validates and prices the plan (same rules as the quote) and saves it as a `draft` with its "
            "travellers. Nothing is scheduled or locked until the goal is activated."
            + rate_limit_note("20/min (goal changes)")
        ),
        request_body=PlanSerializer,
        responses={201: SavingsGoalSerializer, 400: VALIDATION_ERROR},
    )
    def post(self, request):
        serializer = PlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        plan = _plan_from(serializer.validated_data)
        goal = goal_service.create_goal(request.user, plan, serializer.validated_data.get('title'))
        return Response(SavingsGoalSerializer(_fresh(request.user, goal.uuid)).data, status=status.HTTP_201_CREATED)


class GoalQuoteView(APIView):
    """POST /api/goals/quote/ — preview only, nothing is saved."""
    throttle_scope = 'quotes'

    @swagger_auto_schema(
        operation_summary="Quote a goal",
        operation_description=(
            "Prices a plan with today's prices and FX and returns the installment schedule it would get. "
            "Nothing is saved. Fails with 400 when the trip is inactive, the group size is out of range, "
            "there is no adult, the travel date is too close for the lead time, or the deposit is too big."
            + rate_limit_note("60/min (quotes)")
        ),
        request_body=PlanSerializer,
        responses={200: QuoteSerializer, 400: VALIDATION_ERROR},
    )
    def post(self, request):
        serializer = PlanSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(_plan_from(serializer.validated_data).quote_dict())


class GoalDetailView(APIView):
    """GET /api/goals/{uuid}/ · DELETE (drafts only)."""
    throttle_scope = 'goal_changes'

    @swagger_auto_schema(operation_summary="Get a goal", responses={200: SavingsGoalSerializer, 404: NOT_FOUND})
    def get(self, request, goal_uuid):
        goal = get_object_or_404(goals_for(request.user), uuid=goal_uuid)
        return Response(SavingsGoalSerializer(goal).data)

    @swagger_auto_schema(
        operation_summary="Delete a draft goal",
        operation_description="Only drafts can be deleted; cancel other goals instead."
                              + rate_limit_note("20/min (goal changes)"),
        responses={204: "Deleted.", 404: NOT_FOUND, 409: CONFLICT},
    )
    def delete(self, request, goal_uuid):
        goal_service.delete_draft(request.user, goal_uuid)
        return Response(status=status.HTTP_204_NO_CONTENT)


class GoalActivateView(APIView):
    """POST /api/goals/{uuid}/activate/"""
    throttle_scope = 'goal_changes'

    @swagger_auto_schema(
        operation_summary="Activate a goal",
        operation_description=(
            "`draft` → `active`. Re-prices with today's prices and FX, builds the installment schedule, then "
            "locks the price and FX rate: later price or rate changes never affect this goal. Can fail with 400 "
            "if the plan is no longer valid (e.g. the travel date is now too close)."
            + rate_limit_note("20/min (goal changes)")
        ),
        responses={200: SavingsGoalSerializer, 400: VALIDATION_ERROR, 404: NOT_FOUND, 409: CONFLICT},
    )
    def post(self, request, goal_uuid):
        goal = goal_service.activate_goal(request.user, goal_uuid)
        return Response(SavingsGoalSerializer(_fresh(request.user, goal.uuid)).data)


class GoalRescheduleView(APIView):
    """POST /api/goals/{uuid}/reschedule/"""
    throttle_scope = 'goal_changes'

    @swagger_auto_schema(
        operation_summary="Reschedule a goal",
        operation_description=(
            "New travel date (and optionally frequency) for an active, paused or expired goal. The price stays "
            "locked; paid installments are kept and the remaining balance is spread from today. The goal "
            "becomes `active` and its missed count resets."
            + rate_limit_note("20/min (goal changes)")
        ),
        request_body=RescheduleSerializer,
        responses={200: SavingsGoalSerializer, 400: VALIDATION_ERROR, 404: NOT_FOUND, 409: CONFLICT},
    )
    def post(self, request, goal_uuid):
        serializer = RescheduleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        goal = goal_service.reschedule_goal(
            request.user, goal_uuid, serializer.validated_data['travel_date'],
            serializer.validated_data.get('frequency'),
        )
        return Response(SavingsGoalSerializer(_fresh(request.user, goal.uuid)).data)


class GoalCancellationQuoteView(APIView):
    """GET /api/goals/{uuid}/cancellation-quote/"""

    @swagger_auto_schema(
        operation_summary="Preview a cancellation",
        operation_description="What the user would get back if they cancelled today, under the operator's "
                              "refund policy. Show this before calling cancel.",
        responses={200: CancellationQuoteSerializer, 404: NOT_FOUND},
    )
    def get(self, request, goal_uuid):
        goal = get_object_or_404(
            SavingsGoal.objects.select_related('itinerary__operator__refund_policy'), uuid=goal_uuid,
            user=request.user,
        )
        return Response(goal_service.cancellation_quote(goal))


class GoalCancelView(APIView):
    """POST /api/goals/{uuid}/cancel/"""
    throttle_scope = 'goal_changes'

    @swagger_auto_schema(
        operation_summary="Cancel a goal",
        operation_description=(
            "Cancels a draft, active, paused or expired goal. If a refund is due it is created and paid out "
            "in the background (mobile money to the last number used, or back to the card). Returns the "
            "same breakdown as the cancellation preview."
            + rate_limit_note("20/min (goal changes)")
        ),
        request_body=CancelSerializer,
        responses={200: CancellationQuoteSerializer, 404: NOT_FOUND, 409: CONFLICT},
    )
    def post(self, request, goal_uuid):
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return Response(goal_service.cancel_goal(request.user, goal_uuid, serializer.validated_data.get('reason')))


class GoalPaymentsView(APIView):
    """GET /api/goals/{uuid}/payments/ — newest first."""

    @swagger_auto_schema(
        operation_summary="List a goal's payments",
        operation_description="Every payment attempt for the goal (pending, successful and failed), newest first.",
        responses={200: PaymentSerializer(many=True), 404: NOT_FOUND},
    )
    def get(self, request, goal_uuid):
        goal = get_object_or_404(SavingsGoal, uuid=goal_uuid, user=request.user)
        payments = Payment.objects.filter(goal=goal, user=request.user).select_related('goal')
        return Response(PaymentSerializer(payments, many=True).data)
