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
from django.db import transaction, IntegrityError 

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

def _make_signature(user_ids):
    """
    Create a stable signature for a set of user IDs.
    - built-in sorted(): returns a new sorted list
    - map/str/join: build a deterministic string "1|5|41"
    """
    return "|".join(str(uid) for uid in sorted(set(user_ids)))

class CreateConversationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        participants_ids = request.data.get("participants") or []
        campaign_id = request.data.get("campaign_id")  # optional

        # Validate participant list
        if not isinstance(participants_ids, list) or len(participants_ids) == 0:
            return Response({"error": "Participants are required."}, status=status.HTTP_400_BAD_REQUEST)

        # Deduplicate and fetch users in one query (built-in ORM filter + __in)
        participants = list(User.objects.filter(id__in=set(participants_ids)))
        if not participants:
            return Response({"error": "Invalid participants."}, status=status.HTTP_400_BAD_REQUEST)

        # Block checks (exists() -> built-in optimized EXISTS query)
        for participant in participants:
            if BlockedUsers.objects.filter(blocker=user, blocked=participant).exists():
                return Response({'error': f'You have blocked {participant.username}.'}, status=status.HTTP_403_FORBIDDEN)
            if BlockedUsers.objects.filter(blocker=participant, blocked=user).exists():
                return Response({'error': f'{participant.username} has blocked you.'}, status=status.HTTP_403_FORBIDDEN)

        # Full participant set always includes the initiator
        all_participants = participants + [user]
        signature = _make_signature([u.id for u in all_participants])

        # Optional campaign
        campaign = Campaign.objects.filter(id=campaign_id).first() if campaign_id else None  # built-in first(): returns first or None

        # Decide category
        if len(all_participants) > 2:
            category = 'broadcast'
        else:
            # If any target is a winner for this campaign, tag as 'winner'; otherwise 'other'
            if campaign and CampaignWinner.objects.filter(campaign=campaign, fan__in=participants).exists():
                category = 'winner'
            else:
                category = 'other'

        # === DEDUPE LOOKUP ===
        if category == 'broadcast':
            # Rule: dedupe by (signature, created_by=user) for broadcast
            existing = (
                Conversation.objects
                .filter(category='broadcast', created_by=user, participant_signature=signature)
                .select_related('campaign', 'created_by')
                .prefetch_related('participants__profile')
                .first()
            )
        else:
            # Rule: 1-to-1 is category-agnostic: any existing 'winner' or 'other' with same signature must be reused
            existing = (
                Conversation.objects
                .filter(category__in=['winner', 'other'], participant_signature=signature)
                .select_related('campaign', 'created_by')
                .prefetch_related('participants__profile')
                .first()
            )

        if existing:
            # NOTE: If the user had "deleted" the conversation earlier, it will reappear once a new message arrives.
            # You can also choose to clear the deletion record here for this user if you want an instant restore.
            ser = ConversationSerializer(existing, context={'request': request})
            return Response(ser.data, status=status.HTTP_200_OK)

        # === CREATE (race-safe) ===
        try:
            with transaction.atomic():  # built-in: ensures all ops succeed or none
                conversation = Conversation.objects.create(
                    category=category,
                    campaign=campaign,
                    created_by=user,
                    participant_signature=signature,
                )  # built-in create(): inserts row and returns instance

                # M2M set(): built-in that replaces relation with given iterable (bulk insert through table)
                conversation.participants.set(all_participants)

                # Optional auto-message for winners
                if category == 'winner':
                    Message.objects.create(
                        conversation=conversation,
                        sender=user,
                        content="Congratulations on winning the campaign!"
                    )

        except IntegrityError:
            # If two requests race to create the same conversation, unique constraints will raise.
            # We then fetch the one that "won" the race and return it.
            if category == 'broadcast':
                conversation = (
                    Conversation.objects
                    .filter(category='broadcast', created_by=user, participant_signature=signature)
                    .first()
                )
            else:
                conversation = (
                    Conversation.objects
                    .filter(category__in=['winner', 'other'], participant_signature=signature)
                    .first()
                )
            if conversation is None:
                return Response({"error": "Failed to create or fetch conversation."}, status=500)

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