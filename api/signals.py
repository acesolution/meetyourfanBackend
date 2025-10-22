# api/signals.py

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.conf import settings
from api.models import Profile  # Import the Profile model from the same app
from django.contrib.auth import get_user_model

User = get_user_model()  # safe to call in AppConfig.ready()

@receiver(post_save, sender=User)
def ensure_profile(sender, instance, created, **kwargs):
    # create if missing; harmless on updates
    Profile.objects.get_or_create(user=instance)

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        Profile.objects.create(user=instance)

@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def save_user_profile(sender, instance, **kwargs):
    instance.profile.save()
