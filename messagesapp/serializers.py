# messagesapp/serializers.py

from rest_framework import serializers
from messagesapp.models import Conversation, Message
from django.contrib.auth import get_user_model
from api.models import Profile

User = get_user_model()

class ProfileMessagesSerializer(serializers.ModelSerializer):
    """
    This serializer returns the essential user data.
    Built-in function `get_user_model()` returns the active user model.
    """
    class Meta:
        # Adjust the fields below according to your custom user model.
        model = Profile
        fields = ('id', 'name', 'profile_picture')  # add or remove fields as needed

class UserSerializer(serializers.ModelSerializer):
    profile = ProfileMessagesSerializer(read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'profile']
        



class ConversationSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()
    unread_message_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_ids = serializers.SerializerMethodField() 

    class Meta:
        model = Conversation
        fields = (
            'id', 
            'participants', 
            'category', 
            'created_at', 
            'updated_at',
            'unread_message_count', 
            'last_message', 
            'unread_ids'  
        )
        
    def get_unread_message_count(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.messages.filter(status__in=['sent', 'delivered']).exclude(sender=request.user).count()
        return 0

    def get_unread_ids(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            unread_messages = obj.messages.filter(status__in=['sent', 'delivered']).exclude(sender=request.user)
            return list(unread_messages.values_list('id', flat=True))
        return []

    def get_participants(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            others = obj.participants.exclude(id=request.user.id)
        else:
            others = obj.participants.all()
        return UserSerializer(others, many=True, context=self.context).data

    def get_last_message(self, obj):
        last_msg = obj.messages.order_by('-created_at').first()
        if last_msg:
            serializer = MessageSerializer(last_msg, context=self.context)
            data = serializer.data
            request = self.context.get("request")
            if request and request.user.is_authenticated:
                data['sent_by_me'] = (last_msg.sender.id == request.user.id)
            else:
                data['sent_by_me'] = False
            return data
        return None


class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'content', 'status', 'created_at']
