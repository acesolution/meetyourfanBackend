# sociallogins/models.py
from django.conf import settings                   # built-in: access AUTH_USER_MODEL
from django.db import models                       # built-in: ORM base

class SocialProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,                  # built-in: FK to your User model
        on_delete=models.CASCADE,                  # built-in: cascade on delete
        related_name="social_profile",
    )
    ig_user_id = models.CharField(max_length=64, blank=True, null=True)
    ig_username = models.CharField(max_length=150, blank=True, null=True)

    def __str__(self):                             # built-in: string shown in admin/shell
        return f"{self.user} / @{self.ig_username or '—'}"
