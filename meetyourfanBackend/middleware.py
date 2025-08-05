from urllib.parse import parse_qs
from channels.auth import AuthMiddlewareStack
from channels.db import database_sync_to_async
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.db import close_old_connections
from jwt import InvalidSignatureError, ExpiredSignatureError, DecodeError
from jwt import decode as jwt_decode

User = get_user_model()


import logging

logger = logging.getLogger(__name__)

class JWTAuthMiddleware:
    """Middleware to authenticate user for channels"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        close_old_connections()
        try:
            # Decode the query string and extract the token
            token = parse_qs(scope["query_string"].decode("utf8")).get('token', None)
            if not token:
                raise ValueError("Token not found in query string")

            token = token[0]  # Extract the token from the list

            # Decode the token to extract user information
            data = jwt_decode(token, settings.SECRET_KEY, algorithms=["HS256"])

            # Retrieve the user from the database and attach to scope
            scope['user'] = await self.get_user(data['user_id'])
        except Exception as e:
            scope['user'] = AnonymousUser()
        return await self.app(scope, receive, send)

    @database_sync_to_async
    def get_user(self, user_id):
        try:
            return User.objects.get(id=user_id)
        except User.DoesNotExist:
            return AnonymousUser()


def JWTAuthMiddlewareStack(app):
    """Wrap channels authentication stack with JWTAuthMiddleware."""
    return JWTAuthMiddleware(AuthMiddlewareStack(app))
