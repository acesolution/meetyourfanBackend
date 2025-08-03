from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from django.db import transaction as db_transaction
from celery import chain
import logging

from .tasks import register_user_on_chain, save_onchain_action_info
from blockchain.models import OnChainAction

User = get_user_model()
logger = logging.getLogger(__name__)


@receiver(post_save, sender=User)
def auto_register_user(sender, instance, created, **kwargs):
    if not created:
        return

    # determine the on-chain identifier (adjust if contract expects a different field)
    onchain_identifier = getattr(instance, "user_id", None) or instance.id

    # log separately — do not put this inside the chain
    logger.info(
        "[auto_register_user] new User created: django_pk=%s, user.user_id=%s => using on-chain id=%s",
        instance.pk,
        getattr(instance, "user_id", None),
        onchain_identifier,
    )

    def launch_chain():
        # chain: register user → then save the on-chain action with the returned tx_hash
        chain(
            register_user_on_chain.s(onchain_identifier),
            save_onchain_action_info.s(
                instance.id,                    # user_id for action record
                None,                          # campaign_id
                OnChainAction.USER_REGISTERED, # event_type
                {}                             # args
            ),
        ).apply_async()

    db_transaction.on_commit(launch_chain)
