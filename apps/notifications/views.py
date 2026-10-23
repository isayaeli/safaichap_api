from django.shortcuts import get_object_or_404
from drf_yasg.utils import swagger_auto_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from utils.api_docs import NOT_FOUND, OkSerializer
from .models import Notification
from .serializers import NotificationSerializer


class NotificationListView(APIView):
    """GET /api/notifications/ — newest first."""

    @swagger_auto_schema(
        operation_summary="List notifications",
        operation_description="All of the user's notifications, newest first. Not paginated.",
        responses={200: NotificationSerializer(many=True)},
    )
    def get(self, request):
        notifications = Notification.objects.filter(user=request.user).select_related('goal')
        return Response(NotificationSerializer(notifications, many=True).data)


class NotificationDetailView(APIView):
    """DELETE /api/notifications/{uuid}/ — swipe-to-delete in the app."""

    @swagger_auto_schema(operation_summary="Delete a notification",
                         responses={204: "Deleted.", 404: NOT_FOUND})
    def delete(self, request, notification_uuid):
        get_object_or_404(Notification, uuid=notification_uuid, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MarkNotificationReadView(APIView):
    """POST /api/notifications/{uuid}/read/"""

    @swagger_auto_schema(operation_summary="Mark a notification read", operation_description="Idempotent.",
                         responses={200: OkSerializer, 404: NOT_FOUND})
    def post(self, request, notification_uuid):
        notification = get_object_or_404(Notification, uuid=notification_uuid, user=request.user)
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read', 'updated_at'])
        return Response({'ok': True})


class MarkAllNotificationsReadView(APIView):
    """POST /api/notifications/read-all/"""

    @swagger_auto_schema(operation_summary="Mark all notifications read",
                         responses={200: OkSerializer})
    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'ok': True})
