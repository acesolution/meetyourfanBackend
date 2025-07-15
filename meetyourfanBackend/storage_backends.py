# storage_backends.py

from storages.backends.s3boto3 import S3Boto3Storage
#  └─ This is django‑storages’ S3 backend, subclass it to customize prefixes, ACLs, etc.

class MediaStorage(S3Boto3Storage):
    """
    Files uploaded by users (images, videos, etc).
    We want them publicly readable via CloudFront/bucket policy,
    but the bucket itself enforces that, so we disable ACL headers.
    """
    location = "media"     # all media go under s3://<bucket>/media/…
    default_acl = None     # <-- do NOT send any x-amz-acl header
    # file_overwrite = True by default (if you upload same name, it'll overwrite)
    # querystring_auth = False by default if you set AWS_QUERYSTRING_AUTH=False in settings

class StaticStorage(S3Boto3Storage):
    """
    Django’s collectstatic target. We place everything under /static/,
    let CloudFront or bucket policy make it public; don’t send ACLs.
    """
    location = "static"    # all static go under s3://<bucket>/static/…
    default_acl = None     # <-- disable ACL headers
    file_overwrite = False # when you re-collect, existing filenames are NOT overwritten

class PrivateMediaStorage(S3Boto3Storage):
    """
    For any files you want to keep private (e.g. paid-content).
    We still don’t send ACLs; bucket policy + signed URLs control access.
    """
    location = "media-private"
    default_acl = None
