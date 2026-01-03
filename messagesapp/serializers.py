# messagesapp/serializers.py

from rest_framework import serializers
from messagesapp.models import Conversation, Message, MeetupSchedule
from notificationsapp.models import ConversationMute
from django.contrib.auth import get_user_model
from api.models import Profile
from campaign.models import Campaign
from profileapp.models import BlockedUsers
from django.utils import timezone
from django.db.models import Q   # Q: built-in helper to build OR/AND conditions


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
    username = serializers.SerializerMethodField()   # overrides model field in output
    email = serializers.SerializerMethodField()      # same for email

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'user_type', 'profile']

    def get_username(self, obj):
        """
        If the account was soft-deleted (is_active=False), hide the original username.
        This matches the “name removed” behavior (show generic label instead of deleted_<uuid>).
        """
        if not obj.is_active:
            return "Deleted user"
        return obj.username

    def get_email(self, obj):
        """
        Never expose the anonymized deleted+UUID email to clients.
        """
        if not obj.is_active:
            return None
        return obj.email

        


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



class MeetupInlineSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeetupSchedule
        fields = ("id", "scheduled_datetime", "location", "status")


class ConversationSerializer(serializers.ModelSerializer):
    participants = serializers.SerializerMethodField()
    unread_message_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    unread_ids = serializers.SerializerMethodField() 
    campaign = CampaignBasicSerializer(read_only=True)
    is_blocked = serializers.SerializerMethodField()    
    active_meetup = serializers.SerializerMethodField() 
    blocked_by_id = serializers.SerializerMethodField()
    blocked_by_me = serializers.SerializerMethodField()
    
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
            'active_meetup',
            "blocked_by_id",   #  NEW
            "blocked_by_me",   #  NEW (this equals your old meaning)
        )
        
    def get_unread_message_count(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.messages.filter(status__in=['sent', 'delivered']).exclude(sender=request.user, sender__is_active=True,).count()
        return 0

    def get_unread_ids(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            unread_messages = obj.messages.filter(status__in=['sent', 'delivered']).exclude(sender=request.user, sender__is_active=True,)
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
        request = self.context.get("request")
        qs = obj.messages.all()

        if request and request.user.is_authenticated:
            # Only messages that are visible to this user:
            #   - from active senders
            #   - OR from the user themselves
            qs = qs.filter(
                Q(sender__is_active=True) | Q(sender=request.user)
            )
        last_msg = qs.order_by('-created_at').first()
        if last_msg:
            serializer = MessageSerializer(last_msg, context=self.context)
            data = serializer.data
            if request and request.user.is_authenticated:
                data['sent_by_me'] = (last_msg.sender_id == request.user.id)
            else:
                data['sent_by_me'] = False
            return data
        return None
    
    def to_representation(self, obj):
        data = super().to_representation(obj)
        request = self.context.get('request')

        if request and request.user.is_authenticated:
            m = (ConversationMute.objects
                 .filter(conversation=obj, user=request.user)
                 .only('mute_until')
                 .first())

            if m:
                # Always => null, Timed => ISO; Never => omit key entirely
                data['mute_until'] = (
                    None if m.mute_until is None
                    else timezone.localtime(m.mute_until).isoformat()
                )
            # else: Never → leave key absent

        return data
    
    def _block_ctx(self, obj):
        """
        Pull from context if available (fast path).
        built-in dict.get(): returns None if key missing
        """
        m = self.context.get("block_by_conv") or {}
        return m.get(obj.id)

    def get_is_blocked(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False

        ctx = self._block_ctx(obj)
        if ctx is not None:
            return bool(ctx["is_blocked"])

        # fallback (single-conversation endpoints etc.)
        ids = [u.id for u in obj.participants.all()]
        others = [uid for uid in ids if uid != request.user.id]
        if len(others) != 1:
            return False
        peer_id = others[0]

        return BlockedUsers.objects.filter(
            Q(blocker_id=request.user.id, blocked_id=peer_id) |
            Q(blocker_id=peer_id, blocked_id=request.user.id)
        ).exists()  # exists() is ORM built-in: SELECT 1 ... LIMIT 1

    def get_blocked_by_id(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return None

        ctx = self._block_ctx(obj)
        if ctx is not None:
            return ctx["blocked_by_id"]

        ids = [u.id for u in obj.participants.all()]
        others = [uid for uid in ids if uid != request.user.id]
        if len(others) != 1:
            return None
        peer_id = others[0]

        row = (BlockedUsers.objects.filter(
            Q(blocker_id=request.user.id, blocked_id=peer_id) |
            Q(blocker_id=peer_id, blocked_id=request.user.id)
        )
        .order_by("-created_at")  # latest action wins
        .values("blocker_id")
        .first())  # first() is ORM built-in: returns first row or None

        return row["blocker_id"] if row else None

    def get_blocked_by_me(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False

        ctx = self._block_ctx(obj)
        if ctx is not None:
            return bool(ctx["blocked_by_me"])

        blocked_by_id = self.get_blocked_by_id(obj)
        return bool(blocked_by_id and blocked_by_id == request.user.id)
    
    
    def get_active_meetup(self, obj):
        """
        Return the currently relevant meetup (pending or accepted) between the
        campaign influencer and the peer in this winner conversation.
        """
        try:
            if obj.category != "winner" or not obj.campaign:
                return None
            influencer = obj.campaign.user
            # peer = the non-influencer participant
            peer_qs = obj.participants.exclude(id=influencer.id)
            if not peer_qs.exists():
                return None
            winner = peer_qs.first()
            meetup = (
                MeetupSchedule.objects
                .filter(
                    campaign=obj.campaign,
                    influencer=influencer,
                    winner=winner,
                    status__in=["pending", "accepted"],
                )
                .order_by("-updated_at")
                .first()
            )
            if not meetup:
                return None
            return MeetupInlineSerializer(meetup, context=self.context).data
        except Exception:
            # Be defensive; never break the conversations list
            return None
    

class MessageSerializer(serializers.ModelSerializer):
    sender = UserSerializer(read_only=True)

    class Meta:
        model = Message
        fields = ['id', 'conversation', 'sender', 'content', 'status', 'created_at']




class MeetupScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeetupSchedule
        fields = '__all__'
        read_only_fields = ('influencer', 'status', 'created_at', 'updated_at')
