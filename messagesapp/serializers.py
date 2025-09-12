# messagesapp/serializers.py

from rest_framework import serializers
from messagesapp.models import Conversation, Message, ConversationMute
from django.contrib.auth import get_user_model
from api.models import Profile
from campaign.models import Campaign
from profileapp.models import BlockedUsers

User = get_user_model()




class ProfileMessagesSerializer(serializers.ModelSerializer):
    """
    This serializer returns the essential user data.
    Built-in function `get_user_model()` returns the active user model.
    """
    class Meta:
        # Adjust the fields below according to your custom user model.
        model = Profile
        fields = ('id', 'name', 'profile_picture', 'last_seen', 'is_online')  # add or remove fields as needed

class UserSerializer(serializers.ModelSerializer):
    profile = ProfileMessagesSerializer(read_only=True)
    
    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'profile']
        


class CampaignBasicSerializer(serializers.ModelSerializer):
    banner_image = serializers.SerializerMethodField()
    user = UserSerializer(read_only=True)

    class Meta:
        model = Campaign
        fields = (
            'id',
            'title',
            'banner_image',
            'campaign_type',
            'deadline',
            'is_closed',
            'user',
        )

    def get_banner_image(self, obj):
        request = self.context.get("request")
        url = obj.banner_image.url if getattr(obj.banner_image, "url", None) else None
        return request.build_absolute_uri(url) if (request and url) else url




class ConversationSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()
    unread_message_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_ids = serializers.SerializerMethodField() 
    campaign = CampaignBasicSerializer(read_only=True)
    is_blocked = serializers.SerializerMethodField()     
    muted_until = serializers.SerializerMethodField()     

    class Meta:
        model = Conversation
        fields = (
            'id', 
            'participants', 
            'category', 
            'campaign',
            'created_at', 
            'updated_at',
            'unread_message_count', 
            'last_message', 
            'unread_ids',
            'is_blocked',
            'muted_until',
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
    
    
    def get_is_blocked(self, obj):
        """
        True if *request.user* has blocked the peer (only meaningful for 1:1).
        built-in queryset .exists(): SELECT 1 WHERE ... LIMIT 1
        """
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return False
        # For 1:1, peer = the "other" participant
        others = obj.participants.exclude(id=request.user.id)
        if others.count() != 1:
            return False
        peer = others.first()
        return BlockedUsers.objects.filter(blocker=request.user, blocked=peer).exists()

    def get_muted_until(self, obj):
        """Return ISO string or null if not muted for this user."""
        request = self.context.get('request')
        if not request or not request.user.is_authenticated:
            return None
        m = ConversationMute.objects.filter(conversation=obj, user=request.user).first()  # built-in: first()
        if not m:
            return None
        return None if m.muted_until is None else m.muted_until.isoformat()


class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'content', 'status', 'created_at']


