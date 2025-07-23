# messagesapp/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer
from asgiref.sync import sync_to_async
from messagesapp.models import Conversation, Message
from profileapp.models import BlockedUsers  # Import BlockedUsers model
import logging
from django.utils import timezone
from django.conf import settings

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
        logger.debug(f"User in connect: {self.user}")

        if not self.user.is_authenticated:
            logger.error("Unauthenticated user attempted to connect.")
            await self.close()  # Reject unauthenticated connections
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
            await self.close()  # Reject connection for blocked users
            return

        # Join the conversation group
        await self.channel_layer.group_add(
            self.conversation_group_name,
            self.channel_name
        )
        logger.info(f"User {self.user.username} connected to conversation {self.conversation_id}.")
        await self.accept()

    async def disconnect(self, close_code):
        """Handle WebSocket disconnection."""
        # getattr is a built‑in that returns a default if the attribute is missing
        conv_id = getattr(self, 'conversation_id', '<unknown>')
        group = getattr(self, 'conversation_group_name', None)
        
        logger.info(f"User {self.user.username} disconnected from conversation {conv_id}.")
        
        # Only discard if we actually joined
        if group:
            # group_discard is a built‑in Channels method that removes this channel from the group
            await self.channel_layer.group_discard(
                group,
                self.channel_name
            )
        
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
                profile_picture_url = "https://meetyourfan.io" + profile_picture_url
            return {
                "id": profile.id,
                "name": profile.name,
                "profile_picture": profile_picture_url
            }
        return {}

    async def receive(self, text_data):
        """Handle incoming WebSocket messages."""
        try:
            data = json.loads(text_data)
            event_type = data.get('type')

            if not event_type:
                await self.send(json.dumps({"error": "Event type is required."}))
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
                # Handle chat message
                content = data.get('content')
                if content:
                    message = await self.save_message(content)
                    
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
                            'status': message.status,
                            'message_id': message.id,
                        }
                    )

                    # Get unread message IDs for the conversation
                    unread_ids = await self.get_unread_message_ids()

                    # Broadcast a conversation update that includes unread message IDs.
                    await self.channel_layer.group_send(
                        "conversation_updates",  # Global group for conversation list updates
                        {
                            'type': 'conversation_update',
                            'conversation_id': self.conversation_id,
                            'last_message': {
                                'content': content,
                                'created_at': str(message.created_at),  # Send the created_at timestamp
                                'id': message.id,
                                'status': message.status,
                                'user_id': self.user.id,
                                
                            },
                            'updated_at': str(timezone.now()),  # or use message.created_at
                            'unread_ids': unread_ids,
                        }
                    )

                    
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
            status__in=['sent', 'delivered']
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
        }))


class ConversationUpdatesConsumer(AsyncWebsocketConsumer):
    
    async def connect(self):
        """Accept connection for global conversation updates if user is authenticated."""
        self.user = self.scope['user']
        if not self.user.is_authenticated:
            await self.close()
            return
        
        # Join the global updates group.
        await self.channel_layer.group_add("conversation_updates", self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        """Remove the connection from the global updates group."""
        await self.channel_layer.group_discard("conversation_updates", self.channel_name)

    async def conversation_update(self, event):
        """Send the conversation update to the client."""
        await self.send(json.dumps({
            'type': 'conversation_update',
            'conversation_id': event['conversation_id'],
            'last_message': event['last_message'],
            'updated_at': event['updated_at'],
            'unread_ids': event.get('unread_ids', []),
        }))
