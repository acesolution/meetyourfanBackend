# notificationsapp/serializers.py

from rest_framework import serializers
from notificationsapp.models import Notification
from api.models import Profile
from django.contrib.auth import get_user_model

User = get_user_model()

# Serializer to include basic profile info.
class ProfileNotificationsSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ('id', 'name', 'profile_picture')

# Serializer for a user that includes the profile.
class ActorUserSerializer(serializers.ModelSerializer):
    profile = ProfileNotificationsSerializer(read_only=True)
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'profile')

class NotificationSerializer(serializers.ModelSerializer):
    # Use the nested ActorUserSerializer for the actor field.
    actor = ActorUserSerializer(read_only=True)
    # Optionally, you could do the same for the recipient if desired.
    recipient = serializers.StringRelatedField()
    target = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = ['id', 'actor', 'recipient', 'verb', 'target', 'created_at', 'read']

    def get_target(self, obj):
        if obj.target:
            return str(obj.target)
        return None