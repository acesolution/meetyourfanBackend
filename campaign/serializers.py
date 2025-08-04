# compaign/serializers.py

from rest_framework import serializers
from .models import Campaign, TicketCampaign, MediaSellingCampaign, MediaAccess, MeetAndGreetCampaign, Participation, CampaignWinner, MediaFile
from django.utils import timezone 
from django.contrib.auth import get_user_model
from django.utils.timezone import now
from decimal import Decimal
import logging
from api.models import Profile
from profileapp.models import FollowRequest, Follower

logger = logging.getLogger(__name__)

User = get_user_model()

class UserCampaignSerializer(serializers.ModelSerializer):
    """
    This serializer returns the essential user data.
    Built-in function `get_user_model()` returns the active user model.
    """
    class Meta:
        # Adjust the fields below according to your custom user model.
        model = User
        fields = ('id', 'username', 'email')  # add or remove fields as needed
        
class ProfileCampaignSerializer(serializers.ModelSerializer):
    """
    This serializer returns the essential user data.
    Built-in function `get_user_model()` returns the active user model.
    """
    class Meta:
        # Adjust the fields below according to your custom user model.
        model = Profile
        fields = ('id', 'name', 'profile_picture')  # add or remove fields as needed

class BaseCampaignSerializer(serializers.ModelSerializer):
    user = UserCampaignSerializer(read_only=True)
    profile = ProfileCampaignSerializer(source='user.profile', read_only=True)
    likes_count = serializers.SerializerMethodField()
    liked_by_user = serializers.SerializerMethodField()
    participated = serializers.SerializerMethodField()
    participants_count = serializers.SerializerMethodField()
    own_campaign = serializers.SerializerMethodField()  # New field
    
    class Meta:
        model = Campaign
        fields = [
            'id', 
            'title', 
            'banner_image', 
            'campaign_type', 
            'deadline', 
            'ticket_limit_per_fan', 
            'details',
            'winner_slots', 
            'winners_selected', 
            'is_public_announcement', 
            'auto_close_on_goal_met', 
            'is_closed',
            'exclude_previous_winners', 
            'closed_at',
            'created_at', 
            'updated_at', 
            'user',
            'profile', 
            'likes_count',
            'liked_by_user',
            'participated',
            'participants_count',
            'own_campaign'
        ]
        
    def get_own_campaign(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.user.id == request.user.id
        return False
        
    def to_representation(self, instance):
        # Start with the base representation
        representation = super().to_representation(instance)
        
        # Add type-specific fields if the campaign is of a subclass type.
        specific_instance = instance.specific_campaign()
        if instance.campaign_type == 'ticket':
            representation['ticket_cost'] = specific_instance.ticket_cost
            representation['total_tickets'] = specific_instance.total_tickets
        elif instance.campaign_type == 'media_selling':
            representation['media_cost'] = specific_instance.media_cost
            representation['total_media'] = specific_instance.total_media
            # Include media_file if needed:
            media_files_qs = specific_instance.media_files.all()
            representation['media_files'] = MediaFileSerializer(media_files_qs, many=True, context=self.context).data
        elif instance.campaign_type == 'meet_greet':
            representation['ticket_cost'] = specific_instance.ticket_cost
            representation['total_tickets'] = specific_instance.total_tickets

        return representation
    
    def get_likes_count(self, obj):
        return obj.likes.count()
    
    def get_liked_by_user(self, obj):
        request = self.context.get("request", None)
        if request and request.user.is_authenticated:
            # Checks if the current user is in the campaign's likes
            return obj.likes.filter(id=request.user.id).exists()
        return False
    
    def get_participated(self, obj):
        """
        Checks if the currently logged-in user has a Participation record for this campaign.
        """
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            # Assumes the reverse relation is named 'participations'
            return obj.participations.filter(fan=request.user).exists()
        return False
    
    def get_participants_count(self, obj):
        # Simply count the number of Participation records for this campaign.
        return obj.participations.count()

# Update TicketCampaignSerializer to include nested user data
class TicketCampaignSerializer(serializers.ModelSerializer):
    user = UserCampaignSerializer(read_only=True)  # override the user field
    profile = ProfileCampaignSerializer(source='user.profile', read_only=True)
    class Meta:
        model = TicketCampaign
        fields = '__all__'
        
class MediaFileSerializer(serializers.ModelSerializer):
    file_url = serializers.SerializerMethodField()
    has_access = serializers.SerializerMethodField()
    
    class Meta:
        model = MediaFile
        fields = ['file_url', 'uploaded_at', 'has_access']
        
    def get_file_url(self, obj):
        request = self.context.get("request")
        # Optionally, if you want to serve a placeholder when access is not granted,
        # you can check has_access() here and return a locked URL.
        if request and not self.get_has_access(obj):
            # Return a locked placeholder URL. Adjust the URL as needed.
            return request.build_absolute_uri(obj.file.url)
        if request:
            return request.build_absolute_uri(obj.file.url)
        return obj.file.url

    def get_has_access(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        user = request.user
        # If the requesting user is the campaign creator, they have access.
        if obj.campaign.user == user:
            return True
        # Otherwise, check if there's a PurchasedMedia record for this user and file.
        return obj.purchases.filter(user=user).exists()

# Update MediaSellingCampaignSerializer similarly
class MediaSellingCampaignSerializer(serializers.ModelSerializer):
    user = UserCampaignSerializer(read_only=True)  # override the user field
    profile = ProfileCampaignSerializer(source='user.profile', read_only=True)
    media_files = MediaFileSerializer(many=True, read_only=True)  # Nested field
    class Meta:
        model = MediaSellingCampaign
        fields = '__all__'

# Update MeetAndGreetCampaignSerializer similarly
class MeetAndGreetCampaignSerializer(serializers.ModelSerializer):
    user = UserCampaignSerializer(read_only=True)  # override the user field
    profile = ProfileCampaignSerializer(source='user.profile', read_only=True)
    class Meta:
        model = MeetAndGreetCampaign
        fields = '__all__'

class PolymorphicCampaignSerializer(serializers.Serializer):
    campaign_type = serializers.CharField()

    def to_internal_value(self, data):
        campaign_type = data.get('campaign_type')
        # Ensure correct serializer is used
        if campaign_type == 'ticket':
            return TicketCampaignSerializer(data=data).to_internal_value(data)
        elif campaign_type == 'media_selling':
            return MediaSellingCampaignSerializer(data=data).to_internal_value(data)
        elif campaign_type == 'meet_greet':
            return MeetAndGreetCampaignSerializer(data=data).to_internal_value(data)
        else:
            raise serializers.ValidationError({"campaign_type": "Invalid campaign type."})

    def create(self, validated_data):
        # Remove the many-to-many field "likes" from validated_data if it exists.
        likes = validated_data.pop('likes', None)
        campaign_type = validated_data.get('campaign_type')

        if campaign_type == 'ticket':
            campaign = TicketCampaign.objects.create(**validated_data)
        elif campaign_type == 'media_selling':
            campaign = MediaSellingCampaign.objects.create(**validated_data)
        elif campaign_type == 'meet_greet':
            campaign = MeetAndGreetCampaign.objects.create(**validated_data)
        else:
            raise serializers.ValidationError({"campaign_type": "Invalid campaign type."})

        # If likes were provided, assign them properly using set()
        if likes is not None:
            campaign.likes.set(likes)
        return campaign

    def validate(self, data):
        campaign_type = data.get('campaign_type')
        # For ticket or meet & greet campaigns, ensure ticket_limit_per_fan is set.
        if campaign_type in ['ticket', 'meet_greet']:
            # If ticket_limit_per_fan is missing or explicitly set to None:
            if 'ticket_limit_per_fan' not in data or data.get('ticket_limit_per_fan') is None:
                # Use the total_tickets value provided in the request as default.
                total_tickets = data.get('total_tickets')
                if total_tickets is not None:
                    data['ticket_limit_per_fan'] = total_tickets
                else:
                    # If total_tickets is also missing, raise an error.
                    raise serializers.ValidationError({
                        "ticket_limit_per_fan": "This field is required for ticket-based campaigns."
                    })
        else:
            # Remove ticket_limit_per_fan from the data for media-selling campaigns.
            data.pop('ticket_limit_per_fan', None)
        return data

class ParticipationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Participation
        fields = ['fan', 'campaign', 'tickets_purchased', 'media_purchased', 'payment_method']
        read_only_fields = ['fan', 'amount']  # `amount` is calculated dynamically

    def validate(self, data):
        campaign = data['campaign']
        fan = self.context['fan']  # `fan` represents the current user, whether a fan or an influencer

        # Retrieve the correct subclass for the campaign (ensures we have the specific campaign type)
        campaign = campaign.specific_campaign()

        if campaign.deadline < timezone.now():
            raise serializers.ValidationError("This campaign has ended.")

        # Check if the user is a campaign creator (not allowed to participate)
        if fan.user_type == 'influencer' and campaign.user == fan:
            raise serializers.ValidationError("Campaign creators cannot participate in their own campaigns.")

        # Handle Ticket & Meet-and-Greet Campaigns
        if isinstance(campaign, TicketCampaign) or isinstance(campaign, MeetAndGreetCampaign):
            tickets_requested = data.get('tickets_purchased', None)
            if tickets_requested is None or tickets_requested <= 0:
                raise serializers.ValidationError("You must purchase at least one ticket.")

            # Check overall ticket availability
            total_tickets_sold = sum(p.tickets_purchased for p in campaign.participations.all())
            tickets_remaining = campaign.total_tickets - total_tickets_sold
            if tickets_requested > tickets_remaining:
                raise serializers.ValidationError(f"Only {tickets_remaining} tickets are available.")

            # Ensure per-fan ticket limit is respected.
            fan_tickets_purchased = sum(
                p.tickets_purchased for p in campaign.participations.filter(fan=fan)
            )
            max_tickets_allowed = campaign.ticket_limit_per_fan
            if max_tickets_allowed and fan_tickets_purchased + tickets_requested > max_tickets_allowed:
                remaining_tickets = max_tickets_allowed - fan_tickets_purchased
                raise serializers.ValidationError(
                    f"You can only purchase {remaining_tickets} more tickets for this campaign."
                )

            # Automatically calculate the total amount based on the ticket cost.
            data['amount'] = Decimal(str(tickets_requested)) * Decimal(str(campaign.ticket_cost))

        # Handle Media Selling Campaigns
        elif isinstance(campaign, MediaSellingCampaign):
            media_requested = data.get('media_purchased', None)
            if media_requested is None or media_requested <= 0:
                raise serializers.ValidationError("You must purchase at least one media file.")

            # Check overall media availability.
            total_media_sold = sum(p.media_purchased for p in campaign.participations.all() if p.media_purchased)
            media_remaining = campaign.total_media - total_media_sold
            if media_requested > media_remaining:
                raise serializers.ValidationError(f"Only {media_remaining} media files are available.")

            # If a per-fan limit is set (using ticket_limit_per_fan for media selling), enforce it.
            if campaign.ticket_limit_per_fan:
                fan_media_purchased = sum(
                    p.media_purchased for p in campaign.participations.filter(fan=fan) if p.media_purchased
                )
                if fan_media_purchased + media_requested > campaign.ticket_limit_per_fan:
                    remaining_media = campaign.ticket_limit_per_fan - fan_media_purchased
                    raise serializers.ValidationError(
                        f"You can only purchase {remaining_media} more media files for this campaign."
                    )

            # Calculate the total amount based on the media cost.
            data['amount'] = Decimal(str(media_requested)) * Decimal(str(campaign.media_cost))

        return data

    def create(self, validated_data):
        """Ensure `amount` is explicitly set before saving."""
        if 'amount' not in validated_data or validated_data['amount'] is None:
            raise serializers.ValidationError({"amount": "Amount must be calculated before saving."})
        return super().create(validated_data)

class WinnerSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']

class ExploreCampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = Campaign
        fields = ['id', 'title', 'banner_image', 'campaign_type', 'deadline', 'details']

class InfluencerCampaignSerializer(serializers.ModelSerializer):
    is_active = serializers.SerializerMethodField()
    profile = ProfileCampaignSerializer(source='user.profile', read_only=True)
    likes_count = serializers.SerializerMethodField()
    liked_by_user = serializers.SerializerMethodField()
    participated = serializers.SerializerMethodField()
    participants_count = serializers.SerializerMethodField()
    own_campaign = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = [
            'id', 'title', 'banner_image', 'campaign_type', 'deadline', 'winner_slots',
            'winners_selected', 'details', 'created_at', 'updated_at', 'is_closed', 'is_active',
            'profile', 'likes_count', 'liked_by_user', 'participated', 'participants_count', 'own_campaign',
        ]
    
    def get_own_campaign(self, obj):
        # In InfluencerCampaignSerializer, every campaign is owned by the influencer.
        return True

    def get_is_active(self, obj):
        return not obj.is_closed and obj.deadline >= now()

    def get_likes_count(self, obj):
        return obj.likes.count()

    def get_liked_by_user(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.likes.filter(id=request.user.id).exists()
        return False

    def get_participated(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return obj.participations.filter(fan=request.user).exists()
        return False

    def get_participants_count(self, obj):
        return obj.participations.count()

    def to_representation(self, instance):
        representation = super().to_representation(instance)
        if instance.campaign_type == 'ticket':
            ticket_instance = instance.specific_campaign()  # Returns the TicketCampaign object
            representation['ticket_cost'] = ticket_instance.ticket_cost
            representation['total_tickets'] = ticket_instance.total_tickets
        elif instance.campaign_type == 'media_selling':
            media_instance = instance.specific_campaign()  # Returns the MediaSellingCampaign object
            representation['media_cost'] = media_instance.media_cost
            representation['total_media'] = media_instance.total_media
        return representation

class CampaignWinnerSerializer(serializers.ModelSerializer):
    fan = UserCampaignSerializer(read_only=True)
    profile = ProfileCampaignSerializer(source='fan.profile', read_only=True)
    total_purchased = serializers.SerializerMethodField()
    total_credits_spent = serializers.SerializerMethodField()

    class Meta:
        model = CampaignWinner
        # Explicitly list the fields to include the new ones.
        fields = ('id', 'fan', 'profile', 'campaign', 'selected_at', 'total_purchased', 'total_credits_spent')

    def get_total_purchased(self, obj):
        """
        Calculates the total number of items purchased by the fan for this campaign.
        For 'ticket' or 'meet_greet' campaigns, it sums the tickets_purchased.
        For 'media_selling' campaigns, it sums the media_purchased.
        """
        participations = obj.campaign.participations.filter(fan=obj.fan)
        if obj.campaign.campaign_type in ['ticket', 'meet_greet']:
            return sum(p.tickets_purchased or 0 for p in participations)
        elif obj.campaign.campaign_type == 'media_selling':
            return sum(p.media_purchased or 0 for p in participations)
        return 0

    def get_total_credits_spent(self, obj):
        """
        Sums up the amount spent by the fan for this campaign based on all Participation records.
        """
        participations = obj.campaign.participations.filter(fan=obj.fan)
        return sum(p.amount or 0 for p in participations)

class UpdateTicketCampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = TicketCampaign
        fields = '__all__'
    
    def update(self, instance, validated_data):
        # Loop through all validated fields and set them on the instance.
        # This explicitly updates both parent and child fields.
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()  # Save the instance, which updates the child table as well.
        return instance
       
class UpdateMeetAndGreetCampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeetAndGreetCampaign
        fields = '__all__'
        
class UpdateMediaSellingCampaignSerializer(serializers.ModelSerializer):
    class Meta:
        model = MediaSellingCampaign
        fields = '__all__'

class PolymorphicCampaignDetailSerializer(serializers.Serializer):
    winners_count = serializers.SerializerMethodField()
    
    # Checks if the requesting user is following the influencer (campaign owner).
    def get_is_following(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return Follower.objects.filter(follower=request.user, user=obj.user).exists()
        return False

    # Checks if the influencer (campaign owner) is following the requesting user.
    def get_is_followed(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return Follower.objects.filter(follower=obj.user, user=request.user).exists()
        return False

    # Checks if the requesting user has a pending follow request to the influencer.
    def get_has_pending_follow_request(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return FollowRequest.objects.filter(sender=request.user, receiver=obj.user, status='pending').exists()
        return False

    # Calculate total tickets sold for ticket or meet & greet campaigns.
    def get_total_tickets_sold(self, obj):
        if obj.campaign_type in ['ticket', 'meet_greet']:
            return sum(p.tickets_purchased or 0 for p in obj.participations.all())
        return None

    # Calculate total media sold for media selling campaigns.
    def get_total_media_sold(self, obj):
        if obj.campaign_type == 'media_selling':
            return sum(p.media_purchased or 0 for p in obj.participations.all())
        return 
    
    def get_winners_count(self, obj):
        # if campaign isn’t closed yet, show 0
        if not obj.is_closed:
            return 0
        # once closed, count how many winners have been picked
        return obj.winners.count()

    # Overrides the default representation to include extra data.
    def to_representation(self, instance):
        # base_data is generated using the BaseCampaignSerializer.
        base_data = BaseCampaignSerializer(instance, context=self.context).data
        extra_data = {
            'is_following': self.get_is_following(instance),
            'is_followed': self.get_is_followed(instance),
            'has_pending_follow_request': self.get_has_pending_follow_request(instance),
            'winners_count': self.get_winners_count(instance),
        }
        
        # Include total tickets sold for ticket-based or meet & greet campaigns.
        total_tickets_sold = self.get_total_tickets_sold(instance)
        if total_tickets_sold is not None:
            extra_data['total_tickets_sold'] = total_tickets_sold
            
         # Include total media sold for media selling campaigns.
        if instance.campaign_type == 'media_selling':
            extra_data['total_media_sold'] = self.get_total_media_sold(instance)

        # Merge the extra data into the base representation.
        base_data.update(extra_data)
        return base_data
    
    

class MediaAccessSerializer(serializers.ModelSerializer):
    media_file_id = serializers.IntegerField(source='media_file.id', read_only=True)
    preview_url = serializers.SerializerMethodField()

    class Meta:
        model = MediaAccess
        fields = ['id', 'media_file_id', 'preview_url', 'created_at']

    def get_preview_url(self, obj):
        request = self.context.get("request")
        if obj.media_file.preview_image:
            return request.build_absolute_uri(obj.media_file.preview_image.url)
        return None
