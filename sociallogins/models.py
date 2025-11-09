# sociallogins/models.py
from django.conf import settings
from django.db import models
from django.utils import timezone              # built-in: timezone-aware now()
from datetime import timedelta                 # built-in: represent "X seconds/minutes" time spans

class SocialProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="social_profile",
    )
    ig_user_id = models.CharField(max_length=64, blank=True, null=True)
    ig_username = models.CharField(max_length=150, blank=True, null=True)

    # store token + optional expiry
    ig_access_token = models.TextField(blank=True, null=True)
    ig_token_expires_at = models.DateTimeField(blank=True, null=True)

    def has_ig_token(self) -> bool:
        """
        Simple helper: tells you if we currently have an IG token on file.
        """
        return bool(self.ig_access_token)
    
    @property
    def is_instagram_verified(self) -> bool:
        """
        You consider someone verified if they have a valid IG connection.
        """
        return bool(self.ig_username and self.has_ig_token())

    def __str__(self):
        return f"{self.user} / @{self.ig_username or '—'}"
