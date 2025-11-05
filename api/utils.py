# api/utils.py

import random
from django.utils.text import slugify
from django.contrib.auth import get_user_model

def generate_user_id_int() -> int:
    """
    Returns a cryptographically‐random 256‐bit integer
    suitable for a Solidity uint256.
    """
    return random.getrandbits(256)


def generate_unique_username(base: str, exclude_user_id=None) -> str:
    """
    Generate a unique username from the base string.

    - Slugifies + cleans the base.
    - Enforces max length of the username field.
    - Appends _1, _2, ... until we find a free username.
    - exclude_user_id: user ID to ignore in collision checks (the "old owner").
    """
    User = get_user_model()
    max_len = User._meta.get_field("username").max_length

    # slugify, then remove dashes to get a compact handle
    slug = slugify(base)          # "John Doe" -> "john-doe"
    slug = slug.replace("-", "")  # "john-doe" -> "johndoe"

    if not slug:
        slug = "user"

    slug = slug.lower()
    slug = slug[:max_len]         # enforce max length

    qs = User.objects.all()
    if exclude_user_id is not None:
        qs = qs.exclude(pk=exclude_user_id)

    candidate = slug
    i = 1
    while qs.filter(username__iexact=candidate).exists():
        suffix = str(i)
        # leave room for "_" + suffix
        base_part = slug[: max_len - len(suffix) - 1]
        candidate = f"{base_part}_{suffix}"
        i += 1

    return candidate
