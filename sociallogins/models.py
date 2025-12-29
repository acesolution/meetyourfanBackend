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
    ig_user_id = models.CharField(max_length=64, blank=True, null=True, unique=True)
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
        Verified = has username + has token + token not expired (if expiry stored).
        """
        if not (self.ig_username and self.has_ig_token()):
            return False

        # timezone.now(): Django built-in helper returns timezone-aware datetime
        if self.ig_token_expires_at and self.ig_token_expires_at <= timezone.now():
            return False

        return True

    def __str__(self):
        return f"{self.user} / @{self.ig_username or '—'}"
    
    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["ig_user_id"],
                condition=Q(ig_user_id__isnull=False),
                name="uniq_socialprofile_ig_user_id_not_null",
            ),
        ]
