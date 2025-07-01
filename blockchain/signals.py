# blockchain/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .tasks import register_user_on_chain
from django.db import transaction

User = get_user_model()

@receiver(post_save, sender=User)
def auto_register_user(sender, instance, created, **kwargs):
    if created:
        transaction.on_commit(
            lambda: register_user_on_chain.delay(instance.user_id)
        )