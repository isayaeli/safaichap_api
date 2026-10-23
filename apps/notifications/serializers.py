from rest_framework import serializers

from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    goal_uuid = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['uuid', 'title', 'message', 'type', 'goal_uuid', 'is_read', 'created_at']

    def get_goal_uuid(self, obj):
        return str(obj.goal.uuid) if obj.goal_id else None
