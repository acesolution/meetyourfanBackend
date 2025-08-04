# campaign/cloudfront_signer.py
import time
from botocore.signers import CloudFrontSigner
from django.conf import settings
import rsa  # you already have this
from functools import lru_cache

def _normalize_pem(key_str: str) -> bytes:
    """
    Normalize whatever is in the env var into a PEM bytes blob.
    Accepts:
      - full PEM with headers/footers (possibly with escaped newlines)
      - raw base64 body (no headers) → will be wrapped in RSA PRIVATE KEY PEM
    """
    if not key_str:
        raise ValueError("CLOUDFRONT_PRIVATE_KEY is empty")

    # If someone stored "\n" as literal backslash-n, convert to real newlines
    key_str = key_str.replace("\\n", "\n").strip()

    if "BEGIN" not in key_str:
        # assume it's base64 without headers; wrap it
        b64 = key_str.replace("\n", "").strip()
        # break into 64-char lines per PEM formatting
        lines = [b64[i : i + 64] for i in range(0, len(b64), 64)]
        pem = "-----BEGIN RSA PRIVATE KEY-----\n" + "\n".join(lines) + "\n-----END RSA PRIVATE KEY-----\n"
    else:
        pem = key_str
    return pem.encode("utf-8")


@lru_cache(maxsize=1)
def _load_private_key():
    """
    Lazily load & cache the RSA private key from settings.
    """
    raw = getattr(settings, "CLOUDFRONT_PRIVATE_KEY", None)
    if raw is None:
        raise RuntimeError("CLOUDFRONT_PRIVATE_KEY not configured in settings")

    pem_bytes = _normalize_pem(raw)
    try:
        # Try loading as PKCS#1/PEM
        return rsa.PrivateKey.load_pkcs1(pem_bytes)
    except Exception as e:
        # If it fails, rethrow with context
        raise RuntimeError(f"Failed to load CloudFront private key: {e}") from e


def rsa_signer(message):
    """
    CloudFrontSigner expects a signer function that takes the policy/message bytes
    and returns the signature.
    """
    private_key = _load_private_key()
    return rsa.sign(message, private_key, "SHA-1")


def generate_cloudfront_signed_url(resource_url: str, expire_seconds: int = 300):
    """
    Build a signed CloudFront URL for a private asset.
    """
    key_id = settings.CLOUDFRONT_KEY_PAIR_ID
    if not key_id:
        raise RuntimeError("CLOUDFRONT_KEY_PAIR_ID not configured in settings")
    cloudfront_signer = CloudFrontSigner(key_id, rsa_signer)
    expire_time = int(time.time()) + expire_seconds
    signed_url = cloudfront_signer.generate_presigned_url(resource_url, date_less_than=expire_time)
    return signed_url
