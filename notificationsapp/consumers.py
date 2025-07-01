# notificationsapp/consumers.py

import json
from channels.generic.websocket import AsyncWebsocketConsumer
import logging

logger = logging.getLogger(__name__)

class NotificationConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.user = self.scope["user"]
        if not self.user.is_authenticated:
            await self.close()
            return

        self.group_name = f"notifications_{self.user.id}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        logger.info(f"User {self.user} connected to notifications.")

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)
        logger.info(f"User {self.user} disconnected from notifications.")

    async def receive(self, text_data):
        # This consumer might not need to process incoming messages.
        data = json.loads(text_data)
        logger.debug(f"Received data in notifications consumer: {data}")

    async def send_notification(self, event):
        await self.send(json.dumps(event["notification"]))
