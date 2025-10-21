# api/utils.py

import random
from django.contrib.auth import get_user_model

def generate_user_id_int() -> int:
    """
    Returns a cryptographically‐random 256‐bit integer
    suitable for a Solidity uint256.
    """
    return random.getrandbits(256)


def generate_unique_user_id() -> int:
    User = get_user_model()
    for _ in range(10):
        uid = generate_user_id_int()
        if not User.objects.filter(user_id=uid).exists():
            return uid
    raise RuntimeError("Could not generate a unique user_id")