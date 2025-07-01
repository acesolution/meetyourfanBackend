# api/utils.py

import random

def generate_user_id_int() -> int:
    """
    Returns a cryptographically‐random 256‐bit integer
    suitable for a Solidity uint256.
    """
    return random.getrandbits(256)
