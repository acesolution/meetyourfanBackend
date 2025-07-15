# storage_backends.py

from storages.backends.s3boto3 import S3Boto3Storage

class MediaStorage(S3Boto3Storage):
    location = "media"          # all uploads will go under s3://your-bucket/media/…
    default_acl = "public-read" # so that objects (images/videos) are publicly GET-able


class StaticStorage(S3Boto3Storage):
    location = "static"         # all static files will go under s3://your-bucket/static/…
    default_acl = "public-read" # so that static files are publicly GET-able
    file_overwrite = False   # to prevent overwriting files with the same name
    
    
class PrivateMediaStorage(S3Boto3Storage):
    location = "media-private"
    default_acl = "private"