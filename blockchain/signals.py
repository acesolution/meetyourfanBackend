# blockchain/signals.py
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .tasks import register_user_on_chain,save_onchain_action_info
from django.db import transaction
from blockchain.models      import OnChainAction
from celery import chain

User = get_user_model()

@receiver(post_save, sender=User)
def auto_register_user(sender, instance, created, **kwargs):
    if created:
        # built‑in: wait until the DB transaction commits
        transaction.on_commit(lambda: chain(
            # 1) registerUser call → returns tx_hash
            register_user_on_chain.s(instance.id),

            # 2) save the OnChainAction once that hash is available:
            save_onchain_action_info.s(
                # the tx_hash comes in automatically as the *first* arg here
                instance.id,                    # user_id
                None,                           # campaign_id (none for user)
                OnChainAction.USER_REGISTERED,  # event_type
                {}                              # args payload
            )

        ).apply_async())