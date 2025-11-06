# api/utils.py

import random
from django.utils.text import slugify
from django.contrib.auth import get_user_model
import re

User = get_user_model()

def generate_user_id_int() -> int:
    """
    Returns a cryptographically‐random 256‐bit integer
    suitable for a Solidity uint256.
    """
    return random.getrandbits(256)


USERNAME_REGEX = "^[a-zA-Z0-9_.-]+$"


def generate_unique_username_for_user(base: str, skip_user_id: int | None = None) -> str:
    """
    Generate a username from `base` that is unique across all users.
    We optionally skip a specific user id (not needed for the displaced user).
    """
    base = base.strip().lower()
    # clean: only keep allowed chars
    base = re.sub(r"[^a-zA-Z0-9_.-]", "", base) or "user"

    candidate = base
    suffix = 1

    qs = User.objects.all()
    if skip_user_id is not None:
        qs = qs.exclude(pk=skip_user_id)

    while qs.filter(username__iexact=candidate).exists():
        suffix += 1
        candidate = f"{base}{suffix}"

    return candidate
