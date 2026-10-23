from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Notification
from .serializers import NotificationSerializer


class NotificationListView(APIView):
    """GET /api/notifications/ — newest first."""

    def get(self, request):
        notifications = Notification.objects.filter(user=request.user).select_related('goal')
        return Response(NotificationSerializer(notifications, many=True).data)


class NotificationDetailView(APIView):
    """DELETE /api/notifications/{uuid}/ — swipe-to-delete in the app."""

    def delete(self, request, notification_uuid):
        get_object_or_404(Notification, uuid=notification_uuid, user=request.user).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MarkNotificationReadView(APIView):
    def post(self, request, notification_uuid):
        notification = get_object_or_404(Notification, uuid=notification_uuid, user=request.user)
        if not notification.is_read:
            notification.is_read = True
            notification.save(update_fields=['is_read', 'updated_at'])
        return Response({'ok': True})


class MarkAllNotificationsReadView(APIView):
    def post(self, request):
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return Response({'ok': True})
