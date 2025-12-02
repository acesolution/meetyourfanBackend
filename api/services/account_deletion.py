import uuid
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from api.models import DeletedAccount, SocialMediaLink, VerificationCode

User = get_user_model()

@transaction.atomic
def soft_delete_user(user, reason: str = ""):
    """
    Soft delete = anonymize + deactivate, keep row to preserve FK integrity.

    transaction.atomic (built-in decorator/context): ensures all DB changes are all-or-nothing.
    """

    # Safely get profile name (getattr built-in reads attribute or default)
    profile = getattr(user, "profile", None)
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

    # 2) Anonymize user fields (must keep uniqueness constraints happy)
    unique = uuid.uuid4().hex  # uuid: generates a unique token
    user.email = f"deleted+{unique}@meetyourfan.invalid"
    user.username = f"deleted_{unique}"  # username is unique in AbstractUser
    user.phone_number = None
    user.wallet_address = None
    user.is_active = False               # disables login in Django auth
    user.set_unusable_password()         # built-in Django method: prevents password login
    user.first_name = ""
    user.last_name = ""
    user.save()

    # 3) Clear profile PII (optional but recommended)
    if profile:
        profile.name = None
        profile.bio = None
        profile.date_of_birth = None
        profile.instagram_verified = False
        profile.status = "private"
        profile.profile_picture = None
        profile.cover_photo = None
        profile.save()

    # 4) Remove sensitive/ephemeral auth data (optional)
    VerificationCode.objects.filter(user=user).delete()
    SocialMediaLink.objects.filter(user=user).delete()

    return True
