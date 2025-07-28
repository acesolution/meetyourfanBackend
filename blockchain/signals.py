# blockchain/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .tasks import register_user_on_chain
from django.db import transaction
from celery import chain
from .tasks import register_user_on_chain, save_onchain_action
from .models import OnChainAction

User = get_user_model()

@receiver(post_save, sender=User)
def auto_register_user(sender, instance, created, **kwargs):
    if created:
        # Run after the new User is committed to the DB:
        transaction.on_commit(lambda: 
            chain(
                # 1) send the on‑chain tx, returns tx_hash
                register_user_on_chain.s(instance.id),
                # 2) create our DB record & kick off polling,
                #    Celery will fill in the tx_hash for us as the last arg
                save_onchain_action.s(
                    instance.id,                   # user_id
                    None,                          # campaign_id (not relevant here)
                    OnChainAction.USER_REGISTERED  # event_type
                )
            ).apply_async()
        )