# api/serializers.py
from api.models import VerificationCode, Profile, SocialMediaLink
from rest_framework import serializers
from django.contrib.auth import get_user_model
from profileapp.models import Follower
from campaign.serializers import BaseCampaignSerializer
from campaign.models import  Campaign, Participation, CampaignWinner
from profileapp.models import FollowRequest
from django.db.models import Count

User = get_user_model()

class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        exclude = ['user']

class ProfileImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['profile_picture', 'cover_photo']
        # no exclude, we explicitly list just those two

class VerificationCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VerificationCode
        fields = ('email_verified', 'phone_verified')
        
        
class SocialMediaLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = SocialMediaLink
        fields = ['id', 'platform', 'url', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']


class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer()  # Include Profile data
    verification_code = VerificationCodeSerializer()  # Include VerificationCode data
    social_media = SocialMediaLinkSerializer(source="social_links", many=True)
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'phone_number', 'user_type', 'profile', 'verification_code', 'social_media')


class RegisterSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(required=False)  # Handle profile data
    # explicitly declare it as read-only
    user_id = serializers.CharField(read_only=True)
    class Meta:
        model = User
        fields = ('id', 'username', 'email','user_id', 'password', 'phone_number', 'user_type', 'profile')

    def create(self, validated_data):
        profile_data = validated_data.pop('profile', {})  # Extract profile data

        # Create user instance
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=validated_data['password'],
            phone_number=validated_data.get('phone_number'),
            user_type=validated_data.get('user_type', 'fan'),
        )

        # If you want to apply incoming profile fields:
        if profile_data:
            # will exist because signal ran; but be defensive
            profile, _ = Profile.objects.get_or_create(user=user)
            for k, v in profile_data.items():
                setattr(profile, k, v)
            profile.save()

        return user


    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value


import json  # built-in module to work with JSON

class UserProfileUpdateSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(required=False)  # Nested serializer for profile

    class Meta:
        model = User  # assuming your custom user model is named CustomUser
        fields = ('id', 'username', 'email', 'phone_number', 'user_type', 'profile')

    def update(self, instance, validated_data):
        # Pop the nested profile data, if any.
        profile_data = validated_data.pop('profile', {})

        # If profile_data is a JSON string, parse it to a dict.
        if isinstance(profile_data, str):
            try:
                profile_data = json.loads(profile_data)
            except json.JSONDecodeError:
                profile_data = {}

        # Update user fields.
        for attr, value in validated_data.items():
            # setattr(instance, attr, value) is a built-in function that assigns a value to an attribute on the object.
            setattr(instance, attr, value)
        instance.save()  # instance.save() is a Django ORM method that persists changes to the database.

        # Update profile fields.
        profile = instance.profile
        for attr, value in profile_data.items():
            setattr(profile, attr, value)

        # Check for file fields in the raw request data.
        request = self.context.get('request')
        if request:
            if 'cover_photo' in request.data:
                profile.cover_photo = request.data.get('cover_photo')
            if 'profile_picture' in request.data:
                profile.profile_picture = request.data.get('profile_picture')
        profile.save()

        return instance



class InfluencerSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer()
    verification_code = VerificationCodeSerializer()
    campaigns_created = BaseCampaignSerializer(many=True, source="base_campaigns")
    is_following = serializers.SerializerMethodField()
    is_followed = serializers.SerializerMethodField()
    has_pending_follow_request = serializers.SerializerMethodField()
    social_media = SocialMediaLinkSerializer(source="social_links", many=True)
    following_count = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()

    # New fields
    total_campaigns = serializers.SerializerMethodField()
    active_campaigns = serializers.SerializerMethodField()
    total_likes = serializers.SerializerMethodField()
    own_profile = serializers.SerializerMethodField()
    

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'phone_number', 'user_type', 
            'profile', 'verification_code', 'campaigns_created',
            'is_following', 'is_followed', 'has_pending_follow_request',
            'social_media', 'following_count', 'followers_count', 'own_profile',

            # Include new fields here
            'total_campaigns',
            'active_campaigns',
            'total_likes',
        )

    def get_following_count(self, obj):
        return Follower.objects.filter(follower=obj).count()

    def get_followers_count(self, obj):
        return Follower.objects.filter(user=obj).count()

    def get_is_following(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return Follower.objects.filter(follower=request.user, user=obj).exists()
        return False

    def get_is_followed(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return Follower.objects.filter(follower=obj, user=request.user).exists()
        return False

    def get_has_pending_follow_request(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return FollowRequest.objects.filter(
                sender=request.user, receiver=obj, status='pending'
            ).exists()
        return False

    # -------------------------
    # New methods for campaigns
    # -------------------------
    def get_total_campaigns(self, obj):
        """
        Return the total number of campaigns created by this user (influencer).
        Uses the reverse relationship 'base_campaigns' from the Campaign model.
        """
        return obj.base_campaigns.count()

    def get_active_campaigns(self, obj):
        """
        Return the total number of active (non-closed) campaigns.
        """
        return obj.base_campaigns.filter(is_closed=False).count()

    def get_total_likes(self, obj):
        """
        Return the sum of all likes across all campaigns created by this user.
        """
        # Use Django's aggregate to sum the likes on each campaign
        agg_result = obj.base_campaigns.aggregate(
            total_likes=Count('likes', distinct=True)
        )
        return agg_result['total_likes'] or 0
    
    def get_own_profile(self, obj):
        """
        True if this user object *is* the requester.
        """
        request = self.context.get("request", None)
        if request and request.user.is_authenticated:
            return obj.id == request.user.id
        return False

class FanSerializer(serializers.ModelSerializer):
    """Serializer for a fan including joined & won campaigns, follow counts, follow relationships, and new fields."""
    profile = ProfileSerializer()
    verification_code = VerificationCodeSerializer()
    campaigns_joined = serializers.SerializerMethodField()
    campaigns_won = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    followers_count = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()
    is_followed = serializers.SerializerMethodField()
    has_pending_follow_request = serializers.SerializerMethodField()
    social_media = SocialMediaLinkSerializer(source="social_links", many=True)

    # New fields
    total_campaigns_joined = serializers.SerializerMethodField()
    total_campaigns_won = serializers.SerializerMethodField()
    total_likes = serializers.SerializerMethodField()
    own_profile = serializers.SerializerMethodField()
    

    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'phone_number', 'user_type',
            'profile', 'verification_code', 'campaigns_joined', 'campaigns_won',
            'following_count', 'followers_count', 'is_following', 'is_followed',
            'has_pending_follow_request', 'social_media', 'own_profile',
            'total_campaigns_joined',
            'total_campaigns_won',
            'total_likes',
        )

    def get_campaigns_joined(self, obj):
        """
        Retrieves all unique campaigns the fan has joined via participations.
        We use distinct() on the campaign IDs to avoid duplicates if multiple participations exist.
        """
        participations = Participation.objects.filter(fan=obj)\
            .values_list('campaign', flat=True)\
            .distinct()
        campaigns = Campaign.objects.filter(id__in=participations)
        return BaseCampaignSerializer(campaigns, many=True, context=self.context).data

    def get_campaigns_won(self, obj):
        """
        Retrieves all campaigns the fan has won.
        """
        won_campaigns = CampaignWinner.objects.filter(fan=obj)\
            .values_list('campaign', flat=True)
        campaigns = Campaign.objects.filter(id__in=won_campaigns)
        return BaseCampaignSerializer(campaigns, many=True, context=self.context).data

    def get_total_campaigns_joined(self, obj):
        """
        Returns the total number of distinct campaigns joined by the fan.
        """
        participations = Participation.objects.filter(fan=obj)\
            .values_list('campaign', flat=True)\
            .distinct()
        return Campaign.objects.filter(id__in=participations).count()

    def get_total_campaigns_won(self, obj):
        """
        Returns the total number of distinct campaigns the fan has won.
        """
        won_campaigns = CampaignWinner.objects.filter(fan=obj)\
            .values_list('campaign', flat=True)\
            .distinct()
        return Campaign.objects.filter(id__in=won_campaigns).count()

    def get_total_likes(self, obj):
        """
        Returns 0 as requested (e.g., if you do not track likes for fans).
        """
        return 0

    def get_following_count(self, obj):
        """
        Counts how many users this fan is following.
        """
        return Follower.objects.filter(follower=obj).count()

    def get_followers_count(self, obj):
        """
        Counts how many users are following this fan.
        """
        return Follower.objects.filter(user=obj).count()

    def get_is_following(self, obj):
        """
        Checks if the currently authenticated user is following this fan.
        """
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return Follower.objects.filter(follower=request.user, user=obj).exists()
        return False

    def get_is_followed(self, obj):
        """
        Checks if this fan is following the currently authenticated user.
        """
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return Follower.objects.filter(follower=obj, user=request.user).exists()
        return False

    def get_has_pending_follow_request(self, obj):
        """
        Checks if the currently authenticated user has a pending follow request to this fan.
        """
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return FollowRequest.objects.filter(sender=request.user, receiver=obj, status='pending').exists()
        return False
    
    def get_own_profile(self, obj):
        """
        True if this user object *is* the requester.
        """
        request = self.context.get("request", None)
        if request and request.user.is_authenticated:
            return obj.id == request.user.id
        return False
    
class UserUserIdSerializer(serializers.ModelSerializer):
    """Serializer for a user including user_id only."""
    class Meta:
        model = User
        fields = ('user_id',)
        read_only_fields = ('user_id',)

class AllUserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer()
    is_following = serializers.SerializerMethodField()
    is_followed = serializers.SerializerMethodField()
    has_pending_follow_request = serializers.SerializerMethodField()
    own_profile = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = (
            'id', 'username', 'email', 'phone_number', 'user_type', 
            'profile', 'is_following', 'is_followed',
            'has_pending_follow_request', 'own_profile'
        )
    def get_is_following(self, obj):
        """
        Checks if the currently authenticated user is following this fan.
        """
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return Follower.objects.filter(follower=request.user, user=obj).exists()
        return False

    def get_is_followed(self, obj):
        """
        Checks if this fan is following the currently authenticated user.
        """
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return Follower.objects.filter(follower=obj, user=request.user).exists()
        return False

    def get_has_pending_follow_request(self, obj):
        """
        Checks if the currently authenticated user has a pending follow request to this fan.
        """
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return FollowRequest.objects.filter(sender=request.user, receiver=obj, status='pending').exists()
        return False
    
    def get_own_profile(self, obj):
        """
        True if this user object *is* the requester.
        """
        request = self.context.get("request", None)
        if request and request.user.is_authenticated:
            return obj.id == request.user.id
        return False
    
        
        
class ProfileStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['status']

    def validate_status(self, value):
        if value not in ['public', 'private']:
            raise serializers.ValidationError("Status must be 'public' or 'private'.")
        return value
    
    
from base.models import Email

class EmailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Email
        fields = ['email', 'created_at']
        read_only_fields = ['created_at']
        
        
        
