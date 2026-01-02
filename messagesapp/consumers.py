# messagesapp/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from messagesapp.models import Conversation, Message
from profileapp.models import BlockedUsers  # Import BlockedUsers model
import logging
from django.utils import timezone
from django.db import models
from notificationsapp.models import ConversationMute

logger = logging.getLogger(__name__)

class ChatConsumer(AsyncWebsocketConsumer):
    def __init__(self, *args, **kwargs):
        # Call the parent constructor (built‑in __init__ wires up .scope, .channel_layer, etc.)
        super().__init__(*args, **kwargs)
        # Pre‑define these so they always exist, even if connect() never runs
        self.conversation_id = None
        self.conversation_group_name = None
        
        
    async def connect(self):
        """Accept or reject WebSocket connection based on user authentication."""
        self.user = self.scope['user']
        #logger.debug(f"User in connect: {self.user}")

        # If not authenticated OR soft-deleted, refuse the connection.
        if (not self.user.is_authenticated) or (not getattr(self.user, "is_active", True)):
            await self.close()
            return

        self.conversation_id = self.scope['url_route']['kwargs']['conversation_id']
        self.conversation_group_name = f"conversation_{self.conversation_id}"
        logger.debug(f"Connecting to conversation: {self.conversation_id}")

        # Ensure the user is part of the conversation
        if not await self.is_user_part_of_conversation():
            logger.error(f"User {self.user.username} is not part of conversation {self.conversation_id}.")
            await self.close()  # Reject unauthorized access
            return

        # Prevent connection if the user is blocked
        if await self.is_user_blocked():
            logger.error(f"User {self.user.username} is blocked and cannot join conversation {self.conversation_id}.")
            await self.close(code=4003)  # Reject connection for blocked users
            return

        # Join the conversation group
        await self.channel_layer.group_add(
            self.conversation_group_name,
            self.channel_name
        )
        logger.info(f"User {self.user.username} connected to conversation {self.conversation_id}.")
        await self.accept()
        
        # presence: online now
        await self.set_presence(is_online=True)
        
        # auto-mark other people's "sent" as delivered when I open the chat
        delivered_ids = await self.mark_all_unseen_as_delivered()
        if delivered_ids:
            await self.channel_layer.group_send(
                self.conversation_group_name,
                {
                    'type': 'delivered_receipt',
                    'message_ids': delivered_ids,
                    'user_id': self.user.id,
                }
            )


    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        # getattr is a built‑in that returns a default if the attribute is missing
        conv_id = getattr(self, 'conversation_id', '<unknown>')
        group = getattr(self, 'conversation_group_name', None)
        
        
        # Only discard if we actually joined
        if group:
            # group_discard is a built‑in Channels method that removes this channel from the group
            await self.channel_layer.group_discard(
                group,
                self.channel_name
            )
            
        # presence: offline + last_seen now
        await self.set_presence(is_online=False)
        
    @sync_to_async
    def set_presence(self, is_online: bool):
        if hasattr(self.user, 'profile') and self.user.profile:
            p = self.user.profile
            p.is_online = is_online
            p.last_seen = timezone.now()
            p.save(update_fields=['is_online', 'last_seen'])
        
    @sync_to_async
    def get_profile_data(self):
        # Access the profile data and return a complete URL for the profile picture.
        if hasattr(self.user, 'profile') and self.user.profile:
            profile = self.user.profile
            # Get the relative URL from the ImageField.
            profile_picture_url = profile.profile_picture.url if profile.profile_picture else None
            # If the URL exists and doesn't already start with 'http', prepend the SITE_URL.
            if profile_picture_url and not profile_picture_url.startswith("http"):
                # Ensure no duplicate slash by stripping the trailing slash from SITE_URL.
                profile_picture_url = profile_picture_url
            return {
                "id": profile.id,
                "name": profile.name,
                "profile_picture": profile_picture_url
            }
        return {}
    
    @sync_to_async
    def mark_all_unseen_as_delivered(self):
        qs = Message.objects.filter(
            conversation_id=self.conversation_id,
            status='sent'
        ).exclude(sender=self.user)
        ids = list(qs.values_list('id', flat=True))
        if ids:
            qs.update(status='delivered')
        return ids
    
    @sync_to_async
    def get_recipient_ids(self):
        conv = Conversation.objects.get(id=self.conversation_id)
        return list(conv.participants.exclude(id=self.user.id).values_list('id', flat=True))

    @sync_to_async
    def any_recipient_online(self, recipient_ids):
        from api.models import Profile
        return Profile.objects.filter(user_id__in=recipient_ids, is_online=True).exists()

    @sync_to_async
    def set_message_status_delivered(self, message_id: int):
        Message.objects.filter(id=message_id).update(status="delivered")

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            event_type = data.get('type')

            if not event_type:
                await self.send(json.dumps({"error": "Event type is required."}))
                return
            
            if await _is_blocked_either_way():
                # send(): WebSocket built-in to send a JSON message to client
                await self.send(json.dumps({"type": "blocked", "error": "Interaction blocked."}))
                return


            if event_type == 'typing':
                # Broadcast typing event
                await self.channel_layer.group_send(
                    self.conversation_group_name,
                    {
                        'type': 'user_typing',
                        'user_id': self.user.id,
                        'username': self.user.username,
                    }
                )
            elif event_type == 'stop_typing':
                # Broadcast stop typing event
                await self.channel_layer.group_send(
                    self.conversation_group_name,
                    {
                        'type': 'user_stopped_typing',
                        'user_id': self.user.id,
                        'username': self.user.username,
                    }
                )
            elif event_type == 'mark_read':
                # Mark messages as read: update their status in the database.
                message_ids = data.get('message_ids', [])
                if message_ids:
                    updated_message_ids = await self.mark_messages_as_read(message_ids)
                    if updated_message_ids:
                        # Broadcast the read receipt event to the conversation group.
                        await self.channel_layer.group_send(
                            self.conversation_group_name,
                            {
                                'type': 'read_receipt',
                                'message_ids': updated_message_ids,
                                'user_id': self.user.id,
                            }
                        )
            elif event_type == 'mark_delivered':
                # Mark messages as delivered: update their status in the database.
                message_ids = data.get('message_ids', [])
                if message_ids:
                    updated_message_ids = await self.mark_messages_as_delivered(message_ids)
                    if updated_message_ids:
                        # Broadcast the delivered receipt event to the conversation group.
                        await self.channel_layer.group_send(
                            self.conversation_group_name,
                            {
                                'type': 'delivered_receipt',
                                'message_ids': updated_message_ids,
                                'user_id': self.user.id,
                            }
                        )

            elif event_type == 'message':
                # deny if any party blocked the other
                @sync_to_async
                def _is_blocked_either_way():
                    from profileapp.models import BlockedUsers
                    conv = Conversation.objects.get(id=self.conversation_id)
                    # built-in values_list(): SELECT ... returns simple lists/tuples
                    others = list(conv.participants.exclude(id=self.user.id).values_list('id', flat=True))
                    if len(others) != 1:
                        return False
                    other_id = others[0]
                    return BlockedUsers.objects.filter(
                        models.Q(blocker_id=other_id, blocked=self.user) |
                        models.Q(blocker=self.user, blocked_id=other_id)
                    ).exists()

                if await _is_blocked_either_way():
                    await self.send(json.dumps({"error": "Interaction blocked."}))
                    return
                # Handle chat message
                content = data.get('content')
                if content:
                    message = await self.save_message(content)
                    
                    # who are the recipients (everyone in the conversation except me)?
                    recipient_ids = await self.get_recipient_ids()
                     # if any recipient is online, flip to delivered immediately
                    is_any_online = await self.any_recipient_online(recipient_ids)
                    status_to_emit = "sent"
                    if is_any_online:
                        await self.set_message_status_delivered(message.id)
                        status_to_emit = "delivered"

                    
                    # Use the helper function to get profile data
                    profile_data = await self.get_profile_data()
                    
                    # Broadcast the chat message event with its ID and status
                    await self.channel_layer.group_send(
                        self.conversation_group_name,
                        {
                            'type': 'chat_message',
                            'conversation_id': self.conversation_id,
                            'message': content,
                            'user_id': self.user.id,
                            'username': self.user.username,
                            'profile': profile_data,
                            'status': status_to_emit,
                            'message_id': message.id,
                            'created_at': message.created_at.isoformat(),
                        }
                    )

                    sender_name = getattr(getattr(self.user, "profile", None), "name", None) or self.user.username
                    sender_avatar = None
                    if getattr(getattr(self.user, "profile", None), "profile_picture", None):
                        # if you need absolute URL, resolve here
                        sender_avatar = self.user.profile.profile_picture.url

                    # send to each participant’s personal updates stream
                    participant_ids = await self._participant_ids()
                    for uid in participant_ids:
                        unread_ids_for_uid = await self._unread_ids_for_user(uid)
                        # Lookup mute state for that uid
                        @sync_to_async
                        def _is_muted_for(uid_):
                            m = ConversationMute.objects.filter(conversation_id=self.conversation_id, user_id=uid_).first()
                            return bool(m and m.is_active())
                        is_muted = await _is_muted_for(uid)
                        await self.channel_layer.group_send(
                            f"user_{uid}",
                            {
                                "type": "conversation_update",
                                "conversation_id": self.conversation_id,
                                "last_message": {
                                    "content": content,
                                    "created_at": str(message.created_at),
                                    "id": message.id,
                                    "status": status_to_emit,
                                    "user_id": self.user.id,
                                    "sender_name": sender_name,
                                    "sender_avatar": sender_avatar,
                                },
                                "updated_at": str(timezone.now()),
                                "unread_ids": unread_ids_for_uid,
                                "is_muted": is_muted,  # <— NEW hint
                                
                            },
                        )

            elif event_type == 'heartbeat':
                await self.set_presence(is_online=True)  # bumps last_seen
                return
                    
            else:
                await self.send(json.dumps({"error": f"Unknown event type: {event_type}"}))
        except Exception as e:
            logger.error(f"Error in receive: {e}")
            await self.send(json.dumps({"error": str(e)}))

    async def read_receipt(self, event):
        """Send read receipt to WebSocket clients."""
        await self.send(json.dumps({
            'type': 'read_receipt',
            'message_ids': event['message_ids'],
            'user_id': event['user_id'],
        }))

    async def delivered_receipt(self, event):
        """Send delivered receipt to WebSocket clients."""
        await self.send(json.dumps({
            'type': 'delivered_receipt',
            'message_ids': event['message_ids'],
            'user_id': event['user_id'],
        }))

    async def user_typing(self, event):
        """Handle user typing event."""
        await self.send(json.dumps({
            'type': 'typing',
            'user_id': event['user_id'],
            'username': event['username'],
        }))

    async def user_stopped_typing(self, event):
        """Handle user stop typing event."""
        await self.send(json.dumps({
            'type': 'stop_typing',
            'user_id': event['user_id'],
            'username': event['username'],
        }))

    async def chat_message(self, event):
        """Send messages to WebSocket clients, including the message id and status."""
        await self.send(json.dumps({
            'type': 'chat_message', 
            'message_id': event.get('message_id'),
            'conversation_id': self.conversation_id,
            'user_id': event['user_id'],
            'username': event['username'],
            'profile': event.get('profile'),
            'message': event['message'],
            'status': event.get('status', 'sent'),  # default to 'sent' if not provided
            'created_at': event.get('created_at'),
        }))


    @sync_to_async
    def is_user_part_of_conversation(self):
        """Check if the authenticated user is part of the conversation."""
        try:
            conversation = Conversation.objects.get(id=self.conversation_id)
            return self.user in conversation.participants.all()
        except Conversation.DoesNotExist:
            return False

    @sync_to_async
    def is_user_blocked(self):
        """Check if the user is blocked by any participant in the conversation."""
        try:
            conversation = Conversation.objects.get(id=self.conversation_id)
            participants = conversation.participants.all()
            for participant in participants:
                if BlockedUsers.objects.filter(blocker=participant, blocked=self.user).exists():
                    return True
            return False
        except Conversation.DoesNotExist:
            return False

    @sync_to_async
    def save_message(self, content):
        try:
            conversation = Conversation.objects.get(id=self.conversation_id)
            # Check if the user has a deletion record for this conversation.
            deletion = conversation.deletions.filter(user=self.user).first()
            if deletion:
                # Update the deletion record timestamp to the current time.
                # This means that only messages after this new timestamp will be loaded.
                deletion.deleted_at = timezone.now()
                deletion.save()
            message = Message.objects.create(
                conversation=conversation,
                sender=self.user,
                content=content
                # The status field will be set to its default ("sent")
            )
            conversation.updated_at = timezone.now()
            conversation.save(update_fields=['updated_at'])
            logger.info(f"Message saved: {content} by {self.user.username}")
            return message
        except Conversation.DoesNotExist:
            logger.error("Failed to save message: Conversation does not exist.")
            raise ValueError("Conversation does not exist.")


    @sync_to_async
    def mark_messages_as_read(self, message_ids):
        """Mark messages as read in the database by updating their status to 'read'."""
        try:
            messages = Message.objects.filter(id__in=message_ids, conversation_id=self.conversation_id)
            messages.update(status="read")
            logger.info(f"Marked messages {message_ids} as read.")
            return message_ids
        except Exception as e:
            logger.error(f"Failed to mark messages as read: {e}")
            return []

    @sync_to_async
    def mark_messages_as_delivered(self, message_ids):
        """Mark messages as delivered in the database by updating their status to 'delivered'."""
        try:
            messages = Message.objects.filter(id__in=message_ids, conversation_id=self.conversation_id)
            messages.update(status="delivered")
            logger.info(f"Marked messages {message_ids} as delivered.")
            return message_ids
        except Exception as e:
            logger.error(f"Failed to mark messages as delivered: {e}")
            return []
        
    
    @sync_to_async
    def get_unread_message_ids(self):
        # Query messages in the conversation that are not read.
        # (Assuming 'sent' and 'delivered' indicate an unread status)
        conversation = Conversation.objects.get(id=self.conversation_id)
        unread_messages = Message.objects.filter(
            conversation=conversation,
            status__in=['sent', 'delivered'],
            sender__is_active=True,
        ).exclude(sender=self.user)  # Optionally exclude messages from the sender
        # Return only the list of message IDs.
        return list(unread_messages.values_list('id', flat=True))

    
    async def conversation_update(self, event):
        # This method sends the conversation update event to the WebSocket client.
        await self.send(json.dumps({
            'type': 'conversation_update',
            'conversation_id': event['conversation_id'],
            'last_message': event['last_message'],
            'updated_at': event['updated_at'],
            'unread_ids': event.get('unread_ids', []),
            'is_muted': event.get('is_muted', False),          # NEW (you were sending it already)
            'active_meetup': event.get('active_meetup', None), # NEW (for meetup UI sync)
            'is_blocked': event.get('is_blocked', None),
            'blocked_by_id': event.get('blocked_by_id', None),
        }))
        
    @sync_to_async
    def _participant_ids(self):
        return list(Conversation.objects.get(id=self.conversation_id)
                    .participants.values_list('id', flat=True))

    @sync_to_async
    def _unread_ids_for_user(self, uid: int):
        return list(Message.objects
            .filter(
                conversation_id=self.conversation_id,
                status__in=["sent", "delivered"],
                sender__is_active=True,  # ignore deleted senders
            )
            .exclude(sender_id=uid).values_list("id", flat=True))


class ConversationUpdatesConsumer(AsyncWebsocketConsumer):
    
    async def connect(self):
        """Accept connection for global conversation updates if user is authenticated."""
        self.user = self.scope['user']
        # If not authenticated OR soft-deleted, refuse the connection.
        if (not self.user.is_authenticated) or (not getattr(self.user, "is_active", True)):
            await self.close()
            return
        
        self.group = f"user_{self.user.id}"
        await self.channel_layer.group_add(self.group, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group, self.channel_name)

    async def conversation_update(self, event):
        """Send the conversation update to the client."""
        await self.send(json.dumps({
            'type': 'conversation_update',
            'conversation_id': event['conversation_id'],
            'last_message': event['last_message'],
            'updated_at': event['updated_at'],
            'unread_ids': event.get('unread_ids', []),
            'is_muted': event.get('is_muted', False),          # NEW (you were sending it already)
            'active_meetup': event.get('active_meetup', None), # NEW (for meetup UI sync)
            'is_blocked': event.get('is_blocked', None),
            'blocked_by_id': event.get('blocked_by_id', None),
        }))




# messagesapp/consumers.py  (add this class)
class PresenceConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        # If not authenticated OR soft-deleted, refuse the connection.
        if (not self.user.is_authenticated) or (not getattr(self.user, "is_active", True)):
            await self.close()
            return
        await self.accept()
        await self._set_presence(True)

    async def disconnect(self, code):
        await self._set_presence(False)

    async def receive(self, text_data=None, bytes_data=None):
        try:
            data = json.loads(text_data or "{}")
        except Exception:
            data = {}

        t = data.get("type")
        if t == "heartbeat" or t == "online":
            await self._set_presence(True)
        elif t == "mark_delivered_all":
            # Flip all "sent" messages to "delivered" for this user
            conv_to_ids = await self._mark_all_unseen_as_delivered_for_user()
            
            
            # Optionally notify live conversation groups so senders see ✓✓
            for conv_id, ids in conv_to_ids.items():
                if not ids:
                    continue
                
                # delivered ticks for any open chat tabs
                await self.channel_layer.group_send(
                    f"conversation_{conv_id}",
                    {
                        "type": "delivered_receipt",
                        "message_ids": ids,
                        "user_id": self.user.id,
                    },
                )
                
                # compute unread_ids for this user in that conversation
                unread_ids = await self._unread_ids_for_self(conv_id)
                await self.channel_layer.group_send(
                    f"conversation_{conv_id}",
                    {
                        "type": "delivered_receipt",
                        "message_ids": ids,
                        "user_id": self.user.id,
                        "unread_ids": unread_ids,
                    },
                )
                
    @sync_to_async
    def _unread_ids_for_self(self, conv_id: int):
        return list(Message.objects
            .filter(
                conversation_id=conv_id,
                status__in=["sent","delivered"],
                sender__is_active=True,   # keep consistent
            )
            .exclude(sender_id=self.user.id)
            .values_list("id", flat=True))

    @sync_to_async
    def _set_presence(self, is_online: bool):
        if hasattr(self.user, "profile") and self.user.profile:
            p = self.user.profile
            p.is_online = is_online
            p.last_seen = timezone.now()
            p.save(update_fields=["is_online", "last_seen"])

    @sync_to_async
    def _mark_all_unseen_as_delivered_for_user(self):
        """
        Find all messages with status='sent' in conversations that include this user,
        but not sent BY this user → set to 'delivered'.
        Returns {conversation_id: [message_ids...]} for broadcasting receipts.
        """
        from messagesapp.models import Message, Conversation
        # Messages in any conversation where user participates, not authored by user, still 'sent'
        qs = Message.objects.filter(
            conversation__participants=self.user,
            status="sent"
        ).exclude(sender=self.user)

        ids = list(qs.values_list("id", flat=True))
        if not ids:
            return {}

        # Group ids by conversation for fine-grained receipts
        rows = qs.values_list("conversation_id", "id")
        by_conv = {}
        for cid, mid in rows:
            by_conv.setdefault(cid, []).append(mid)

        qs.update(status="delivered")
        return by_conv
