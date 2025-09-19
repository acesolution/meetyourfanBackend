# profileapp/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from profileapp.models import BlockedUsers, Follower, FollowRequest, UserReport
from django.conf import settings
from django.contrib.auth import get_user_model
from rest_framework import status
from profileapp.serializers import FollowRequestSerializer, BlockedUsersSerializer, FollowerSerializer, UserReportSerializer,  MeetupScheduleSerializer, FollowerDetailSerializer, FollowingDetailSerializer, ReportIssueSerializer
from rest_framework.permissions import AllowAny
from rest_framework import status
from django.shortcuts import get_object_or_404
from rest_framework.parsers import MultiPartParser, FormParser

User = get_user_model()


class BlockUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, blocked_user_id):
        if not blocked_user_id:
            return Response({'error': 'Blocked user ID is required.'}, status=400)

        try:
            blocked_user = User.objects.get(id=blocked_user_id)
            if blocked_user == request.user:
                return Response({'error': "You cannot block yourself."}, status=400)

            # For Option 1: Using BlockedUsers Model
            BlockedUsers.objects.get_or_create(blocker=request.user, blocked=blocked_user)

            # For Option 2: Using Profile Model
            # request.user.profile.blocked_users.add(blocked_user)

            return Response({'message': f'User {blocked_user.username} has been blocked.'}, status=200)

        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=404)


class UnblockUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, blocked_user_id):
        if not blocked_user_id:
            return Response({'error': 'Blocked user ID is required.'}, status=400)

        try:
            blocked_user = User.objects.get(id=blocked_user_id)

            # For Option 1: Using BlockedUsers Model
            BlockedUsers.objects.filter(blocker=request.user, blocked=blocked_user).delete()

            # For Option 2: Using Profile Model
            # request.user.profile.blocked_users.remove(blocked_user)

            return Response({'message': f'User {blocked_user.username} has been unblocked.'}, status=200)

        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=404)
        
class UnfollowUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        
        if not user_id:
            return Response({'error': 'User ID is required.'}, status=400)

        try:
            user_to_unfollow = User.objects.get(id=user_id)

            # Delete the follower relationship
            Follower.objects.filter(user=user_to_unfollow, follower=request.user).delete()

            return Response({'message': f'You have unfollowed {user_to_unfollow.username}.'}, status=200)

        except User.DoesNotExist:
            return Response({'error': 'User not found.'}, status=404)
        
class FollowUserView(APIView):
    """
    Endpoint to either directly follow a user (if their profile is public)
    or send a follow request (if their profile is private).
    """
    permission_classes = [IsAuthenticated]

    def post(self, request, user_id):
        # Check if a user_id is provided
        if not user_id:
            return Response({'error': 'User ID is required.'}, status=400)

        try:
            # Attempt to retrieve the target user by ID.
            # User.objects.get() is a Django ORM method that retrieves a single object
            # matching the given parameters. If no object is found, it raises User.DoesNotExist.
            target_user = User.objects.get(id=user_id)

            # Prevent users from following themselves.
            if target_user == request.user:
                return Response({'error': "You cannot follow yourself."}, status=400)

            # Check the privacy status of the target user's profile.
            if target_user.profile.status == "public":
                # For public profiles, we perform a direct follow.
                # get_or_create is a Django ORM method that tries to fetch an object matching the query.
                # If it doesn't exist, it creates one. It returns a tuple (object, created),
                # where 'created' is a boolean indicating whether a new object was created.
                follower, created = Follower.objects.get_or_create(user=target_user, follower=request.user)
                
                if created:
                    return Response({'message': f'You are now following {target_user.username}.', 'accepted': True}, status=200)
                else:
                    # Optional: If already following, inform the user accordingly.
                    return Response({'message': f'You are already following {target_user.username}.', 'accepted': True}, status=200)
            else:
                # For private profiles, we send a follow request.
                follow_request, created = FollowRequest.objects.get_or_create(sender=request.user, receiver=target_user)
                
                if created:
                    return Response({'message': f'Follow request sent to {target_user.username}.', 'accepted': False}, status=200)
                else:
                    return Response({'message': f'Follow request already sent to {target_user.username}.', 'accepted': False}, status=400)

        except User.DoesNotExist:
            # This exception is raised by User.objects.get() if the user is not found.
            return Response({'error': 'User not found.'}, status=404)


class AcceptFollowRequestView(APIView):
    """Accept a follow request and establish a follow relationship."""
    permission_classes = [IsAuthenticated]

    def post(self, request, sender_id):

        if not sender_id:
            return Response({"error": "Sender ID is required."}, status=400)

        try:
            follow_request = FollowRequest.objects.get(sender_id=sender_id, receiver=request.user, status='pending')

            # Update request status to accepted
            follow_request.status = "accepted"
            follow_request.delete()  # Delete the request after accepting it

            # Create the Follower relationship
            Follower.objects.get_or_create(user=request.user, follower=follow_request.sender)

            return Response({"message": f"You have accepted {follow_request.sender.username}'s follow request."}, status=200)

        except FollowRequest.DoesNotExist:
            return Response({"error": "Follow request not found."}, status=404)


class DeclineFollowRequestView(APIView):
    """Decline a follow request."""
    permission_classes = [IsAuthenticated]

    def post(self, request, sender_id):
        if not sender_id:
            return Response({"error": "Sender ID is required."}, status=400)
        try:
            follow_request = FollowRequest.objects.get(
                sender_id=sender_id, receiver=request.user, status='pending'
            )
            follow_request.delete()  # Delete the request instead of marking it as declined.
            return Response(
                {"message": f"You have declined {follow_request.sender.username}'s follow request."},
                status=200,
            )
        except FollowRequest.DoesNotExist:
            return Response({"error": "Follow request not found."}, status=404)


class CancelFollowRequestView(APIView):
    """Cancel a sent follow request before it's accepted."""
    permission_classes = [IsAuthenticated]

    def post(self, request, receiver_id):

        if not receiver_id:
            return Response({"error": "Receiver ID is required."}, status=400)

        try:
            follow_request = FollowRequest.objects.get(sender=request.user, receiver_id=receiver_id, status='pending')
            follow_request.delete()
            return Response({"message": "Follow request canceled."}, status=200)

        except FollowRequest.DoesNotExist:
            return Response({"error": "Follow request not found."}, status=404)


    
class BlockedUsersListView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user  # Get the current authenticated user
        blocked_users = BlockedUsers.objects.filter(blocker=user)
        serializer = BlockedUsersSerializer(blocked_users, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)
    
    
class FollowRequestsListView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        user = request.user  # Get the current authenticated user
        follow_requests = FollowRequest.objects.filter(receiver=user)
        serializer = FollowRequestSerializer(follow_requests, many=True, context={'request': request})

    
class FollowersListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Accepted followers where you are the target.
        followers_qs = Follower.objects.filter(user=request.user)
        # Pending follow requests where you are the receiver.
        pending_qs = FollowRequest.objects.filter(receiver=request.user, status='pending')
        
        # Optional: filter by username if a search query is provided.
        search_query = request.query_params.get('search')
        if search_query:
            followers_qs = followers_qs.filter(follower__username__icontains=search_query)
            pending_qs = pending_qs.filter(sender__username__icontains=search_query)
        
        accepted_serializer = FollowerDetailSerializer(followers_qs, many=True, context={'request': request})
        pending_serializer = FollowerDetailSerializer(pending_qs, many=True, context={'request': request})
        
        # Combine the two lists.
        data = accepted_serializer.data + pending_serializer.data
        return Response(data, status=status.HTTP_200_OK)




class FollowingListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Accepted followings: users you are following.
        accepted_qs = Follower.objects.filter(follower=request.user)
        # Pending follow requests: requests you have sent.
        pending_qs = FollowRequest.objects.filter(sender=request.user, status='pending')
        
        search_query = request.query_params.get('search')
        if search_query:
            accepted_qs = accepted_qs.filter(user__username__icontains=search_query)
            pending_qs = pending_qs.filter(receiver__username__icontains=search_query)
        
        accepted_serializer = FollowingDetailSerializer(accepted_qs, many=True, context={'request': request})
        pending_serializer = FollowingDetailSerializer(pending_qs, many=True, context={'request': request})
        
        # Combine the two lists.
        data = accepted_serializer.data + pending_serializer.data
        return Response(data, status=status.HTTP_200_OK)

    
    
    
class ReportUserView(APIView):
    """
    API endpoint for an authenticated user to report another user.
    Expects the following in the POST request body:
      - reported_id: ID of the user being reported
      - category: One of the defined categories (e.g., "inappropriate", "harassment", etc.)
      - additional_information: (optional) further details about the report
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        reported_id = request.data.get('reported_id')
        category = request.data.get('category')
        additional_information = request.data.get('additional_information', '')

        if not reported_id or not category:
            return Response({"error": "reported_id and category are required."},
                            status=status.HTTP_400_BAD_REQUEST)
        
        try:
            reported = User.objects.get(id=reported_id)
        except User.DoesNotExist:
            return Response({"error": "Reported user not found."},
                            status=status.HTTP_404_NOT_FOUND)
        
        # Prevent users from reporting themselves.
        if request.user.id == reported.id:
            return Response({"error": "You cannot report yourself."},
                            status=status.HTTP_400_BAD_REQUEST)
        
        # Create the UserReport record.
        report = UserReport.objects.create(
            reporter=request.user,
            reported=reported,
            category=category,
            additional_information=additional_information
        )
        serializer = UserReportSerializer(report, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    


class ReportIssueView(APIView):
    permission_classes = [IsAuthenticated]  # Adjust as needed for your use-case
    parser_classes = [MultiPartParser, FormParser]  # To handle file uploads

    def post(self, request, *args, **kwargs):
        # Pass in the request data to the serializer for validation.
        serializer = ReportIssueSerializer(data=request.data)
        if serializer.is_valid():
            # Save the report with the current user as the reporter.
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        # If data is invalid, return errors.
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)