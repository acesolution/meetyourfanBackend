# messageapp/views.py

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework import status
from messagesapp.models import Conversation, Message, ConversationDeletion, UserMessagesReport
from notificationsapp.models import ConversationMute
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
    


def _get_peer_or_400(conversation, me):
    """
    For 1:1 conversation, return the other user or raise 400 if not 1:1.
    """
    others = conversation.participants.exclude(id=me.id)
    if others.count() != 1:
        # built-in Response: simple error payload
        from rest_framework.response import Response
        from rest_framework import status
        return Response({'error': 'Operation only valid for 1:1 conversations.'}, status=status.HTTP_400_BAD_REQUEST)
    return others.first()

class MuteConversationView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        """
        Body: { "duration_seconds": number|null }
        - 0 => unmute (delete row)
        - null => indefinite mute (muted_until=None)
        - N => muted_until = now + N seconds
        """
        conv = get_object_or_404(Conversation, id=conversation_id, participants=request.user)
        seconds = request.data.get('duration_seconds', 0)

        if seconds == 0:
            ConversationMute.objects.filter(conversation=conv, user=request.user).delete()
            return Response({'mute_until': None, 'status': 'unmuted'})  # response can be ignored by FE if you prefer

        if seconds is None:
            m, _ = ConversationMute.objects.update_or_create(
                conversation=conv, user=request.user,
                defaults={'mute_until': None}
            )
            return Response({'mute_until': None, 'status': 'muted_indefinite'})

        # timed:
        until = timezone.now() + timezone.timedelta(seconds=seconds)
        m, _ = ConversationMute.objects.update_or_create(
            conversation=conv, user=request.user,
            defaults={'mute_until': until}
        )
        return Response({'mute_until': m.mute_until.isoformat(), 'status': 'muted'})

class BlockPeerView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        conv = get_object_or_404(Conversation, id=conversation_id, participants=request.user)
        peer = _get_peer_or_400(conv, request.user)
        if isinstance(peer, Response):
            return peer

        # Prevent duplicate rows; built-in get_or_create() returns (obj, created_bool)
        BlockedUsers.objects.get_or_create(blocker=request.user, blocked=peer)
        return Response({'ok': True})


class UnblockPeerView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id):
        conv = get_object_or_404(Conversation, id=conversation_id, participants=request.user)
        peer = _get_peer_or_400(conv, request.user)
        if isinstance(peer, Response):
            return peer

        BlockedUsers.objects.filter(blocker=request.user, blocked=peer).delete()
        return Response({'ok': True})


class ReportUserView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        """
        Body: { conversation_id, reason, text, block }
        """
        conv_id = request.data.get('conversation_id')
        reason = request.data.get('reason')
        text = request.data.get('text', '')
        block = bool(request.data.get('block', False))

        if not conv_id or not reason:
            return Response({'error': 'conversation_id and reason are required'}, status=400)

        conv = get_object_or_404(Conversation, id=conv_id, participants=request.user)
        peer = _get_peer_or_400(conv, request.user)
        if isinstance(peer, Response):
            return peer

        UserMessagesReport.objects.create(
            reporter=request.user,
            reported_user=peer,
            conversation=conv,
            reason=reason,
            text=text or '',
        )

        if block:
            BlockedUsers.objects.get_or_create(blocker=request.user, blocked=peer)

        return Response({'ok': True})
    
    
class SearchPagination(PageNumberPagination):
    page_size = 50

class MessageSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id):
        conv = get_object_or_404(Conversation, id=conversation_id, participants=request.user)
        q = (request.query_params.get('q') or '').strip()
        if not q:
            return Response({'results': [], 'count': 0, 'next': None, 'previous': None}, status=200)

        qs = conv.messages.filter(content__icontains=q).order_by('-created_at')
        paginator = SearchPagination()
        page = paginator.paginate_queryset(qs, request)
        ser = MessageSerializer(page, many=True, context={'request': request})
        return paginator.get_paginated_response(ser.data)

class MessagesAroundView(APIView):
    """
    Return a chronological slice of messages centered on `message_id`.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request, conversation_id, message_id):
        conv = get_object_or_404(Conversation, id=conversation_id, participants=request.user)
        anchor = get_object_or_404(Message, id=message_id, conversation=conv)

        try:
            window = int(request.query_params.get('window', 50))
        except ValueError:
            window = 50
        window = max(10, min(window, 200))

        before = list(
            conv.messages.filter(created_at__lt=anchor.created_at)
            .order_by('-created_at')[:window]
        )
        after = list(
            conv.messages.filter(created_at__gte=anchor.created_at)
            .order_by('created_at')[:window]
        )
        items = before[::-1] + after  # chronological asc
        ser = MessageSerializer(items, many=True, context={'request': request})
        return Response({'results': ser.data, 'anchor_id': anchor.id}, status=200)
    
    
    
class RemoveParticipantView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, conversation_id, user_id):
        conv = get_object_or_404(Conversation, id=conversation_id, participants=request.user)

        # Only for broadcast, and only creator can prune members (adjust to your rules)
        if conv.category != 'broadcast':
            return Response({'error': 'Only broadcast conversations support removing members.'}, status=400)
        if conv.created_by_id != request.user.id:
            return Response({'error': 'Only the broadcast creator can remove members.'}, status=403)

        victim = get_object_or_404(User, id=user_id)
        if victim.id == request.user.id:
            return Response({'error': 'Cannot remove yourself.'}, status=400)
        if not conv.participants.filter(id=victim.id).exists():
            return Response({'error': 'User is not a participant.'}, status=404)

        conv.participants.remove(victim)
        conv.save(update_fields=['updated_at'])

        # Optional: system message
        # Message.objects.create(conversation=conv, sender=request.user, content=f"{victim.username} was removed.")

        return Response({'ok': True}, status=200)