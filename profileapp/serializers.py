# profileapp/serializers.py

from rest_framework import serializers
from profileapp.models import Follower, BlockedUsers, FollowRequest, UserReport, MeetupSchedule
from django.contrib.auth import get_user_model
from api.models import Profile, ReportGenericIssue  # Adjust the import if your Profile model is located elsewhere

User = get_user_model()



class FollowerSerializer(serializers.ModelSerializer):
    
    class Meta:
        model = Follower
        fields = '__all__'



class FollowRequestSerializer(serializers.ModelSerializer):
    class Meta:
        model = FollowRequest
        fields = '__all__'
        
# Serializer for Profile data
class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ('id', 'name', 'profile_picture')

# Serializer for a User that includes their profile information
class UserWithProfileSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'user_type', 'profile')

# Updated UserReport serializer that nests reporter and reported with profile data
class UserReportSerializer(serializers.ModelSerializer):
    reporter = UserWithProfileSerializer(read_only=True)
    reported = UserWithProfileSerializer(read_only=True)
    
    class Meta:
        model = UserReport
        fields = ('id', 'reporter', 'reported', 'category', 'additional_information', 'created_at')
        
       
class BlockedUsersSerializer(serializers.ModelSerializer):
    # Use the 'blocked' FK to provide user details.
    blocked_user = UserWithProfileSerializer(source='blocked', read_only=True)
    
    class Meta:
        model = BlockedUsers
        # Exclude the blocker field and include the blocked user's details.
        fields = ('id', 'created_at', 'blocked_user')
        
        
class MeetupScheduleSerializer(serializers.ModelSerializer):
    class Meta:
        model = MeetupSchedule
        fields = '__all__'
        read_only_fields = ('influencer', 'status', 'created_at', 'updated_at')


class FollowerDetailSerializer(serializers.ModelSerializer):
    # For accepted follower records, "follower" holds the user who follows you.
    follower = UserWithProfileSerializer(read_only=True)
    follow_status = serializers.SerializerMethodField()  # "following", "pending", or "none"
    is_follow_request = serializers.SerializerMethodField()
    sender = serializers.SerializerMethodField()  # True if the authenticated user initiated the follow request

    class Meta:
        model = Follower
        fields = ('id', 'follower', 'follow_status', 'is_follow_request', 'sender', 'created_at')

    def to_representation(self, instance):
        request = self.context.get("request")
        # If instance is a FollowRequest (incoming request)
        if isinstance(instance, FollowRequest):
            # Use the sender's data as the follower.
            user_data = UserWithProfileSerializer(instance.sender, context=self.context).data
            user_data["status"] = instance.status  # Inject status inside the user data
            ret = {
                "id": instance.id,
                "follower": user_data,
                "created_at": instance.created_at,
                "is_follow_request": True,
                "follow_status": "pending",
                # For incoming requests, sender is false because the authenticated user is the receiver.
                "sender": False,
            }
            return ret

        # Otherwise, it's a regular Follower instance.
        ret = super().to_representation(instance)
        ret["is_follow_request"] = False  # default for accepted relationships
        ret["sender"] = False             # default for accepted relationships

        request_user = request.user if request and request.user.is_authenticated else None
        if request_user:
            # Check if the authenticated user is following user2 (i.e. reciprocal accepted relationship)
            if Follower.objects.filter(follower=request_user, user=instance.follower).exists():
                ret["follow_status"] = "following"
            # Otherwise, check if there's a pending follow request from the authenticated user to user2.
            elif FollowRequest.objects.filter(sender=request_user, receiver=instance.follower, status="pending").exists():
                ret["follow_status"] = "pending"
                ret["is_follow_request"] = True
                ret["sender"] = True  # Authenticated user initiated this request.
            else:
                ret["follow_status"] = "none"
        else:
            ret["follow_status"] = "none"
        return ret

    def get_is_follow_request(self, obj):
        # Not used because we set it directly in to_representation.
        return False

    def get_follow_status(self, obj):
        # Not used because we set it directly in to_representation.
        return None

    def get_sender(self, obj):
        # Not used because we set it directly in to_representation.
        return None



class FollowingDetailSerializer(serializers.ModelSerializer):
    # The "user" field represents the user you are following,
    # or for a follow request, the target receiver.
    user = UserWithProfileSerializer(read_only=True)
    is_followed = serializers.SerializerMethodField()
    is_follow_request = serializers.SerializerMethodField()
    
    class Meta:
        model = Follower  # Base model for accepted followings.
        fields = ('id', 'user', 'is_followed', 'is_follow_request', 'created_at')
    
    def to_representation(self, instance):
        request = self.context.get("request")
        # If instance is a pending follow request (i.e. a FollowRequest instance)
        if isinstance(instance, FollowRequest):
            # Serialize the receiver's data
            user_data = UserWithProfileSerializer(instance.receiver, context=self.context).data
            # Inject the status field only for follow requests
            user_data["status"] = instance.status
            ret = {
                "id": instance.id,
                "user": user_data,
                "created_at": instance.created_at,
                "is_follow_request": True,
                "is_followed": (
                    Follower.objects.filter(follower=instance.receiver, user=request.user).exists()
                    if request and request.user.is_authenticated else False
                ),
            }
            return ret
        # For a normal Follower instance, use the default representation.
        ret = super().to_representation(instance)
        ret["is_follow_request"] = False
        return ret

    def get_is_followed(self, obj):
        request = self.context.get("request")
        if request and request.user.is_authenticated:
            return Follower.objects.filter(follower=obj.user, user=request.user).exists()
        return False

    def get_is_follow_request(self, obj):
        # Not used because we set this field in to_representation.
        return False


class ReportIssueSerializer(serializers.ModelSerializer):
    class Meta:
        model = ReportGenericIssue
        # Include all fields except for read-only ones.
        fields = ('id', 'user', 'issue_category', 'details', 'attachment', 'created_at')
        read_only_fields = ('id', 'created_at')