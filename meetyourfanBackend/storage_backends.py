# meetyourfanBackend/storage_backends.py
from storages.backends.s3boto3 import S3Boto3Storage

class StaticStorage(S3Boto3Storage):
    location = "static"
    default_acl = None        # don’t send any ACL headers
    file_overwrite = False    # keep old names

class PublicMediaStorage(S3Boto3Storage):
    location = "media"
    default_acl = None        # access controlled by bucket policy

class PrivateMediaStorage(S3Boto3Storage):
    location = "media-private"
    default_acl = None        # bucket policy does *not* expose this
    querystring_auth = True   # generate signed URLs
