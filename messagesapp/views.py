# messageapp/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from messagesapp.models import Conversation, Message, ConversationDeletion
from messagesapp.serializers import ConversationSerializer, MessageSerializer, UserSerializer
from django.contrib.auth import get_user_model
from campaign.models import Campaign, Participation
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
        conversations = Conversation.objects.filter(participants=request.user).order_by('-updated_at')
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
        participants_ids = request.data.get("participants")

        if not participants_ids:
            return Response({"error": "Participants are required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            participants = list(User.objects.filter(id__in=participants_ids))

            if not participants:
                return Response({"error": "Invalid participants."}, status=status.HTTP_400_BAD_REQUEST)

            # Prevent blocked users from being added
            for participant in participants:
                if BlockedUsers.objects.filter(blocker=user, blocked=participant).exists():
                    return Response({'error': f'You have blocked {participant.username}.'}, status=status.HTTP_403_FORBIDDEN)
                if BlockedUsers.objects.filter(blocker=participant, blocked=user).exists():
                    return Response({'error': f'{participant.username} has blocked you.'}, status=status.HTTP_403_FORBIDDEN)

            # Include requesting user in the participant list
            all_participants = participants + [user]

            # Check if a conversation already exists
            potential_conversations = Conversation.objects.annotate(
                participant_count=Count('participants')
            ).filter(
                participant_count=len(all_participants)
            )

            for conversation in potential_conversations:
                if set(conversation.participants.all()) == set(all_participants):
                    return Response({
                        "message": "Conversation already exists.",
                        "id": conversation.id,
                        "category": conversation.category
                    }, status=status.HTTP_200_OK)

            # Determine conversation category
            if len(all_participants) > 2:
                category = 'broadcast'  # More than two participants
            elif request.data.get("campaign_id"):  # Check for winner logic
                campaign_id = request.data.get("campaign_id")
                try:
                    campaign = Campaign.objects.get(id=campaign_id)
                    if any(Participation.objects.filter(campaign=campaign, fan=participant).exists() for participant in participants):
                        category = 'winner'  # If any participant is a campaign winner
                    else:
                        category = 'other'
                except Campaign.DoesNotExist:
                    category = 'other'
            else:
                category = 'other'  # Default to 'other'

            # Create a new conversation
            conversation = Conversation.objects.create(category=category)
            conversation.participants.set(all_participants)  # Set all participants

            # Send an automated winner message if category is 'winner'
            if category == 'winner':
                Message.objects.create(
                    conversation=conversation,
                    sender=user,  # Assuming the influencer is the sender
                    content="Congratulations on winning the campaign!"
                )

            serializer = ConversationSerializer(conversation, context={'request': request})
            return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

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