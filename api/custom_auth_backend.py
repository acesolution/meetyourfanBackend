# api/custom_auth_backend.py

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend

class EmailOrUsernameBackend(ModelBackend):
    """
    Custom authentication backend that allows users to log in using either
    their email or username. It checks if the provided identifier contains an
    "@" character and queries accordingly.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        # Retrieve the active user model.
        UserModel = get_user_model()

        # If the identifier contains '@', treat it as an email.
        if username and "@" in username:
            try:
                # Case-insensitive lookup on the email field.
                user = UserModel.objects.get(email__iexact=username)
            except UserModel.DoesNotExist:
                return None
        else:
            try:
                # Otherwise, treat it as a username.
                user = UserModel.objects.get(username__iexact=username)
            except UserModel.DoesNotExist:
                return None

        # Verify the password using the built-in check_password method.
        if user.check_password(password):
            return user
        return None