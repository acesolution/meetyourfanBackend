# notificationsapp/views.py

from django.shortcuts import render
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from notificationsapp.models import Notification, ConversationMute
from rest_framework import status
from notificationsapp.serializers import NotificationSerializer
from messagesapp.models import Conversation
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import timedelta


class NotificationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # List notifications for the authenticated user, optionally filter unread.
        notifications = Notification.objects.filter(recipient=request.user)
        serializer = NotificationSerializer(notifications, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class MarkNotificationReadView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, notification_id):
        try:
            notification = Notification.objects.get(id=notification_id, recipient=request.user)
            notification.read = True
            notification.save()
            return Response({'message': 'Notification marked as read.'}, status=status.HTTP_200_OK)
        except Notification.DoesNotExist:
            return Response({'error': 'Notification not found.'}, status=status.HTTP_404_NOT_FOUND)


class MuteConversationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        mute_duration = request.data.get('mute_duration')  # Duration in hours, for example.
        if not mute_duration:
            return Response({"error": "mute_duration (in hours) is required."}, status=400)
        try:
            mute_duration = float(mute_duration)
        except ValueError:
            return Response({"error": "Invalid mute_duration value."}, status=400)
        
        conversation = get_object_or_404(Conversation, id=conversation_id)
        mute_until = timezone.now() + timedelta(hours=mute_duration)
        mute_record, created = ConversationMute.objects.update_or_create(
            conversation=conversation,
            user=request.user,
            defaults={'mute_until': mute_until}
        )
        return Response({
            "message": f"Conversation muted until {mute_until}.",
            "mute_until": mute_until
        }, status=200)