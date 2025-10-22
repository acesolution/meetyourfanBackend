# api/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from api.models import Profile

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def ensure_user_profile(sender, instance, created, **kwargs):
    # idempotent – safe if called multiple times
    Profile.objects.get_or_create(user=instance)
