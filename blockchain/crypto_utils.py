# blockchain/crypto_utils.py
import base64                       # built-in: binary<->ascii codecs
import hmac                         # built-in: keyed hashing
import hashlib                      # built-in: SHA-256, etc.
import os                           # built-in: env vars
from django.conf import settings

def b64u(data: bytes) -> str:
    """
    URL-safe base64 without '=' padding.
    Built-ins used: .rstrip() removes trailing "=", .decode() bytes->str.
    """
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()

def b64u_dec(s: str) -> bytes:
    """
    Restore stripped padding so Python’s base64 can decode.
    Built-ins used: len() for length, string multiplication to make the padding.
    """
    pad = "=" * (-len(s) % 4)       # math trick: add 0..3 "=" so len%4==0
    return base64.urlsafe_b64decode(s + pad)

def sign(data: str) -> str:
    """
    HMAC-SHA256 of the string with a secret key.
    Built-ins used: .encode() str->bytes; .hexdigest() bytes->hex ascii.
    """
    secret = os.getenv("GUEST_CLAIM_SECRET", settings.SECRET_KEY)
    return hmac.new(secret.encode(), data.encode(), hashlib.sha256).hexdigest()
