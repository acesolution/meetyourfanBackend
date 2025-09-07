# messageapp/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from messagesapp.models import Conversation, Message, ConversationDeletion
from messagesapp.serializers import ConversationSerializer, MessageSerializer, UserSerializer
from django.contrib.auth import get_user_model
from campaign.models import Campaign, Participation, CampaignWinner
from rest_framework.generics import ListAPIView
from rest_framework.pagination import PageNumberPagination
from rest_framework import serializers
from django.db.models import Count
from profileapp.models import BlockedUsers  # Import BlockedUsers model
from django.shortcuts import get_object_or_404
from django.utils import timezone

User = get_user_model()


class ConversationListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        # Get all conversations that include the current user.
        conversations = (
            Conversation.objects
            .filter(participants=request.user)
            .select_related('campaign', 'campaign__user')
            .prefetch_related('participants__profile')
            .order_by('-updated_at')
        )
        restored_conversations = []
        for conv in conversations:
            deletion = conv.deletions.filter(user=request.user).first()
            if deletion:
                # If a deletion record exists, check for a message sent after the deletion time.
                last_message = conv.messages.order_by('-created_at').first()
                if last_message and last_message.created_at > deletion.deleted_at:
                    restored_conversations.append(conv)
                # Otherwise, the conversation remains hidden.
            else:
                # No deletion record means the conversation is visible.
                restored_conversations.append(conv)
        serializer = ConversationSerializer(restored_conversations, many=True, context={'request': request})
        return Response(serializer.data, status=status.HTTP_200_OK)

class CreateConversationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        participants_ids = request.data.get("participants") or []

        if not isinstance(participants_ids, list) or len(participants_ids) == 0:
            return Response({"error": "Participants are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Dedup & fetch
        participants = list(User.objects.filter(id__in=set(participants_ids)))

        if not participants:
            return Response({"error": "Invalid participants."}, status=status.HTTP_400_BAD_REQUEST)

        # Block checks
        for participant in participants:
            if BlockedUsers.objects.filter(blocker=user, blocked=participant).exists():
                return Response({'error': f'You have blocked {participant.username}.'}, status=status.HTTP_403_FORBIDDEN)
            if BlockedUsers.objects.filter(blocker=participant, blocked=user).exists():
                return Response({'error': f'{participant.username} has blocked you.'}, status=status.HTTP_403_FORBIDDEN)

        all_participants = participants + [user]

        # Optional campaign attach
        campaign = None
        campaign_id = request.data.get("campaign_id")
        if campaign_id:
            campaign = Campaign.objects.filter(id=campaign_id).first()

        # Decide category
        if len(all_participants) > 2:
            category = 'broadcast'
        else:
            # winner if any participant is in winners for this campaign
            if campaign and CampaignWinner.objects.filter(
                campaign=campaign, fan__in=participants
            ).exists():
                category = 'winner'
            else:
                category = 'other'

        # Try to find an existing conversation
        qs = Conversation.objects.annotate(participant_count=Count('participants')).filter(
            participant_count=len(all_participants)
        )

        # For broadcasts: identity should include campaign so campaigns don't collide.
        if category == 'broadcast':
            qs = qs.filter(category='broadcast')
            if campaign:
                qs = qs.filter(campaign=campaign)
            else:
                qs = qs.filter(campaign__isnull=True)
        else:
            # For non-broadcast, allow either with or without campaign; if you prefer
            # stricter behavior, also filter by category and campaign here.
            qs = qs.filter(category=category)
            if campaign:
                qs = qs.filter(campaign=campaign)
            else:
                qs = qs.filter(campaign__isnull=True)

        for existing in qs:
            if set(existing.participants.all()) == set(all_participants):
                # Found the same conversation; return it.
                ser = ConversationSerializer(existing, context={'request': request})
                return Response(ser.data, status=status.HTTP_200_OK)

        # Create new conversation
        conversation = Conversation.objects.create(category=category, campaign=campaign)
        conversation.participants.set(all_participants)

        if category == 'winner':
            Message.objects.create(
                conversation=conversation,
                sender=user,
                content="Congratulations on winning the campaign!"
            )

        serializer = ConversationSerializer(conversation, context={'request': request})
        return Response(serializer.data, status=status.HTTP_201_CREATED)
    
    
class MessagePagination(PageNumberPagination):
    page_size = 30

class MessageListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id):
        # Retrieve the conversation; ensure the user is a participant.
        try:
            conversation = Conversation.objects.get(id=conversation_id, participants=request.user)
        except Conversation.DoesNotExist:
            return Response({'error': 'Conversation not found.'}, status=404)
        
        # If the user has deleted this conversation, only include messages after deletion.
        deletion = conversation.deletions.filter(user=request.user).first()
        if deletion:
            messages_qs = conversation.messages.filter(created_at__gt=deletion.deleted_at).order_by('-created_at')
        else:
            messages_qs = conversation.messages.all().order_by('-created_at')
        
        # Paginate the messages queryset.
        paginator = MessagePagination()
        result_page = paginator.paginate_queryset(messages_qs, request)
        serializer = MessageSerializer(result_page, many=True, context={'request': request})
        # Reverse the serialized data so that the oldest messages come first.
        reversed_data = serializer.data[::-1]

        # Compute a list of unread message IDs for the conversation.
        # A message is considered unread if its status is either "sent" or "delivered"
        # and it was not sent by the current user.
        unread_messages = conversation.messages.filter(status__in=['sent', 'delivered']).exclude(sender=request.user)
        unread_ids = list(unread_messages.values_list('id', flat=True))

        # Get the default paginated response and add the "unread_ids" field.
        response = paginator.get_paginated_response(reversed_data)
        response.data['unread_ids'] = unread_ids  # Top-level field containing all unread message IDs.
        return response



class ConversationParticipantsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id):
        # Retrieve the conversation and ensure the requesting user is a participant.
        conversation = get_object_or_404(Conversation, id=conversation_id, participants=request.user)
        
        # Option 1: Exclude the current user from the returned participants:
        participants = conversation.participants.exclude(id=request.user.id)
        
        # Option 2: If you want to return all participants (including the current user),
        # simply use: participants = conversation.participants.all()
        
        serializer = UserSerializer(participants, many=True, context={'request': request})
        return Response(serializer.data, status=200)
    
class DeleteConversationView(APIView):
    """
    Marks a conversation as deleted (hidden) for the logged-in user.
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, conversation_id):
        conversation = get_object_or_404(Conversation, id=conversation_id)
        
        # Create or update the deletion record for this user.
        deletion, created = ConversationDeletion.objects.update_or_create(
            conversation=conversation,
            user=request.user,
            defaults={'deleted_at': timezone.now()}
        )
        return Response({'message': 'Conversation deleted for user.'}, status=200)