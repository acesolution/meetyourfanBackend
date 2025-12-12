# api/services/account_deletion.py
import uuid
from django.db import transaction
from django.db.models import Q                  # Q: built-in helper for OR/AND complex filters
from django.utils import timezone
from django.contrib.auth import get_user_model

from api.models import DeletedAccount, SocialMediaLink, VerificationCode
from profileapp.models import Follower, FollowRequest, BlockedUsers
from campaign.models import Campaign            # for likes cleanup (via related_name)
from messagesapp.models import Conversation, ConversationDeletion
from notificationsapp.models import Notification

User = get_user_model()

@transaction.atomic  # transaction.atomic: built-in decorator — all DB ops succeed or all roll back
def soft_delete_user(user, reason: str = ""):
    """
    Soft delete = anonymize + deactivate, keep row to preserve FK integrity.
    """

    profile = getattr(user, "profile", None)           # getattr: built-in — returns attribute or default
    profile_name = getattr(profile, "name", None)

    # 1) Store snapshot
    DeletedAccount.objects.create(
        user_pk=user.pk,
        user_id=getattr(user, "user_id", None),
        username=getattr(user, "username", None),
        email=getattr(user, "email", None),
        user_type=getattr(user, "user_type", None),
        name=profile_name,
        reason=reason,
    )

    # 2) Anonymize + deactivate
    unique = uuid.uuid4().hex                         # uuid4(): built-in — random UUID; .hex gives 32-char hex
    user.email = f"deleted+{unique}@meetyourfan.invalid"
    user.username = f"deleted_{unique}"
    user.phone_number = None
    user.wallet_address = None
    user.is_active = False                            # 🔑 drives all "active user" filters
    user.set_unusable_password()                      # built-in — marks password unusable
    user.first_name = ""
    user.last_name = ""
    user.save()

    # 3) Clear profile PII
    if profile:
        profile.name = None
        profile.bio = None
        profile.date_of_birth = None
        profile.instagram_verified = False
        profile.status = "private"
        profile.profile_picture = None
        profile.cover_photo = None
        profile.save()

    # 4) Remove auth-related rows
    VerificationCode.objects.filter(user=user).delete()    # delete(): built-in QuerySet delete — removes rows
    SocialMediaLink.objects.filter(user=user).delete()

    # 5) Clean social graph (followers / follow requests / blocks)
    Follower.objects.filter(
        Q(user=user) | Q(follower=user)                    # Q(...): OR — matches either side
    ).delete()

    FollowRequest.objects.filter(
        Q(sender=user) | Q(receiver=user)
    ).delete()

    BlockedUsers.objects.filter(
        Q(blocker=user) | Q(blocked=user)
    ).delete()

    # 6) Remove from campaign likes (ManyToMany)
    # user.liked_campaigns uses related_name="liked_campaigns" on Campaign.likes
    # clear(): built-in M2M method — removes all rows in the through table for this user
    try:
        user.liked_campaigns.clear()
    except Exception:
        # In case there are no related likes yet; ignore
        pass

    # 7) Optionally: mark this user’s conversations as “deleted for them”
    # so if you ever allow reactivation you can hide old chats from their view.
    conv_qs = Conversation.objects.filter(participants=user)
    ConversationDeletion.objects.bulk_create(
        [
            ConversationDeletion(conversation=c, user=user)
            for c in conv_qs
        ],
        ignore_conflicts=True,  # built-in: avoids IntegrityError on duplicates
    )

    # 8) Optionally: mark their notifications as read to avoid dangling “new activity” bubbles.
    Notification.objects.filter(recipient=user, read=False).update(read=True)

    return True
