# storage_backends.py

from django.conf import settings
from storages.backends.s3boto3 import S3Boto3Storage
from botocore.signers import CloudFrontSigner
import rsa

class PublicMediaStorage(S3Boto3Storage):
    """Serve public media through CloudFront (no auth required)."""
    # Override the domain so .url() returns your CloudFront host, not raw S3
    custom_domain = settings.CLOUDFRONT_DOMAIN  
    default_acl = None    # objects are uploaded as public
    querystring_auth = False       # no AWS auth params in URL

    # inherits .url(name) from parent, which simply does: 
    # return f"https://{self.custom_domain}/{name}"

class PrivateMediaStorage(S3Boto3Storage):
    """Generate CloudFront‑signed URLs for private media."""
    custom_domain = settings.CLOUDFRONT_DOMAIN
    default_acl = None        # objects uploaded are private
    querystring_auth = False       # we’ll use CloudFront signatures instead

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # CloudFrontSigner takes your key‑pair ID and a signer function
        self.signer = CloudFrontSigner(
            settings.CLOUDFRONT_KEY_PAIR_ID,
            self._rsa_signer
        )

    def _rsa_signer(self, message: bytes) -> bytes:
        """
        Called by CloudFrontSigner to sign a policy blob.
        Uses your RSA private key to produce a signature.
        """
        private_key = rsa.PrivateKey.load_pkcs1(settings.CLOUDFRONT_PRIVATE_KEY)
        # rsa.sign does SHA1 by default; CloudFront requires SHA1 for its policy signing
        return rsa.sign(message, private_key, 'SHA-1')

    def url(self, name: str) -> str:
        """
        Overrides S3Boto3Storage.url(). Instead of a plain S3 link,
        generate a signed CloudFront URL that expires in 1 hour.
        """
        path = f"https://{self.custom_domain}/{name}"
        # .generate_presigned_url on CloudFrontSigner attaches 
        # ?Expires=…&Signature=…&Key-Pair-Id=…
        return self.signer.generate_presigned_url(
            path,
            date_less_than=self._expiration_time()
        )

    def _expiration_time(self):
        """Return a datetime 1 hour from now for URL expiry."""
        from datetime import datetime, timedelta
        return datetime.utcnow() + timedelta(hours=1)
