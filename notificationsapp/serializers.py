# notificationsapp/serializers.py
from rest_framework import serializers
from notificationsapp.models import Notification
from api.models import Profile
from django.contrib.auth import get_user_model
from messagesapp.models import Message, Conversation
from campaign.models import Campaign

User = get_user_model()

class ProfileNotificationsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ('id', 'name', 'profile_picture')

class ActorUserSerializer(serializers.ModelSerializer):
    profile = ProfileNotificationsSerializer(read_only=True)
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'user_type', 'profile')  # ← include user_type

class NotificationSerializer(serializers.ModelSerializer):
    actor = ActorUserSerializer(read_only=True)
    recipient = serializers.StringRelatedField()
    target = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'actor', 'recipient', 'verb', 'target', 'created_at', 'read']

    def get_target(self, obj):
        t = obj.target
        if isinstance(t, Message):
            return {
                "type": "message",
                "message_id": t.id,
                "conversation_id": t.conversation_id,
                "preview": str(t)[:140],  # optional
            }
        if isinstance(t, Conversation):
            return {
                "type": "conversation",
                "conversation_id": t.id,
            }
        if isinstance(t, Campaign):
            return {
                "type": "campaign",
                "campaign_id": t.id,
                "title": t.title,
            }
        # If you add follow notifications with a user as target:
        if isinstance(t, User):
            return {
                "type": "user",
                "user_id": t.id,
                "user_type": t.user_type,
            }
        # fallback
        return {"type": "text", "text": str(t) if t else None}
