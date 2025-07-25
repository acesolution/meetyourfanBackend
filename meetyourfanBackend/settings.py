"""
Django settings for meetyourfanBackend project.

Generated by 'django-admin startproject' using Django 5.0.4.
"""

from pathlib import Path
import os
from datetime import timedelta
import ssl
from dotenv import load_dotenv

# ─── AWS Secrets Manager helper ───────────────────────────────────────────────

import boto3
from botocore.exceptions import ClientError

def get_aws_secret(secret_name: str, region_name: str="us-east-1") -> str:
    """
    Fetches the value of a string secret from AWS Secrets Manager.
    Assumes your EC2 instance has an IAM role with SecretsManagerReadWrite (or at least GetSecretValue) permissions.
    """
    session = boto3.session.Session()
    client  = session.client(service_name="secretsmanager", region_name=region_name)
    try:
        resp = client.get_secret_value(SecretId=secret_name)
    except ClientError as e:
        # logger.warning("Could not retrieve secret %s: %s", secret_name, e)
        raise
    # if you stored a JSON blob, you'd do json.loads(...) here
    return resp.get("SecretString", "")

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# Load .env file into environment variables
load_dotenv(BASE_DIR / '.env')

# Quick-start development settings - unsuitable for production
# See https://docs.djangoproject.com/en/5.0/howto/deployment/checklist/

# SECURITY WARNING: keep the secret key used in production secret!
# SECURITY
SECRET_KEY = os.environ['SECRET_KEY']  
#     os.environ[]: builtin dict-like lookup, throws KeyError if missing

DEBUG = os.environ.get('DEBUG', 'False') == 'True'  
#     .get: returns 'False' if no DEBUG var, compare to 'True' string

ALLOWED_HOSTS = os.environ.get('ALLOWED_HOSTS', '').split(',')  

AUTH_USER_MODEL = 'api.CustomUser'

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(days=30),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=120),
    'ROTATE_REFRESH_TOKENS': False,
    'BLACKLIST_AFTER_ROTATION': True,
    'AUTH_TOKEN_CLASSES': ('rest_framework_simplejwt.tokens.AccessToken',),
    'TOKEN_TYPE_CLAIM': 'token_type',
    'ALGORITHM': 'HS256',
    'SIGNING_KEY': SECRET_KEY,  # Use Django's SECRET_KEY
}

# Allow all domains during development
CORS_ALLOW_ALL_ORIGINS = True

# Application definition
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'api',
    'rest_framework_simplejwt.token_blacklist',  # For JWT token management
    'drf_yasg',
    'profileapp',
    'corsheaders',
    'campaign',
    'messagesapp',
    'notificationsapp',
    'base',
    'blockchain.apps.BlockchainConfig',
    "storages"
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
    'DEFAULT_PERMISSION_CLASSES': (
        'rest_framework.permissions.IsAuthenticated',
    ),
    
}

# Allow your Next.js domain
CORS_ALLOWED_ORIGINS = [
    "https://meetyourfan.io",
    "http://localhost:3000",
]

ROOT_URLCONF = 'meetyourfanBackend.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [os.path.join(BASE_DIR, "templates")],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

ASGI_APPLICATION = "meetyourfanBackend.asgi.application"

REDIS_URL = os.environ.get("REDIS_URL")

CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [REDIS_URL],
        },
    },
}

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql_psycopg2',
        'NAME': os.environ['DB_NAME'],
        'USER': os.environ['DB_USER'],
        'PASSWORD': os.environ['DB_PASSWORD'],
        'HOST': os.environ.get('DB_HOST', 'localhost'),
        'PORT': os.environ.get('DB_PORT', ''),
        "OPTIONS": {
            "sslmode": "require",
            # optionally, if you download the AWS RDS CA bundle:
            # "sslrootcert": "/path/to/rds-combined-ca-bundle.pem",
        },
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

CELERY_BEAT_SCHEDULE = {
    'close-expired-campaigns-every-minute': {
         'task': 'campaign.tasks.close_expired_campaigns',
         'schedule': 60.0,  # Run every minute
    },
}

AUTHENTICATION_BACKENDS = [
    'api.custom_auth_backend.EmailOrUsernameBackend',  # Update the path if your file is elsewhere.
    'django.contrib.auth.backends.ModelBackend',  # Fallback backend.
]

EMAIL_BACKEND       = os.environ['EMAIL_BACKEND']
EMAIL_HOST          = os.environ['EMAIL_HOST']
EMAIL_PORT          = int(os.environ['EMAIL_PORT'])
EMAIL_USE_TLS       = os.environ.get('EMAIL_USE_TLS','False') == 'True'
EMAIL_HOST_USER     = os.environ['EMAIL_HOST_USER']
EMAIL_HOST_PASSWORD = os.environ['EMAIL_HOST_PASSWORD']
DEFAULT_FROM_EMAIL  = os.environ['DEFAULT_FROM_EMAIL']

DEFAULT_FILE_STORAGE = "meetyourfanBackend.storage_backends.PublicMediaStorage"

# pull your keys from env
AWS_ACCESS_KEY_ID = os.environ["AWS_ACCESS_KEY_ID"]
AWS_SECRET_ACCESS_KEY = os.environ["AWS_SECRET_ACCESS_KEY"]
AWS_STORAGE_BUCKET_NAME = os.environ["AWS_STORAGE_BUCKET_NAME"]
AWS_S3_REGION_NAME = os.environ.get("AWS_S3_REGION_NAME", None)
AWS_QUERYSTRING_AUTH = False    # so URLs are public


CELERY_BROKER_URL = os.environ["CELERY_BROKER_URL"]

# tell kombu/Celery to use TLS but skip cert validation (ElastiCache uses Amazon’s cert)
CELERY_BROKER_USE_SSL = {"ssl_cert_reqs": ssl.CERT_NONE}



LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

CLOUDFRONT_DOMAIN = os.environ["CLOUDFRONT_DOMAIN"]


# build a public URL for S3 objects
AWS_S3_CUSTOM_DOMAIN = f"{AWS_STORAGE_BUCKET_NAME}.s3.amazonaws.com"

# this is what {{ obj.file.url }} will become
MEDIA_URL = f"https://{CLOUDFRONT_DOMAIN}/"


# ——— Static ———
STATICFILES_STORAGE = "meetyourfanBackend.storage_backends.StaticStorage"
STATIC_URL = f"https://{AWS_S3_CUSTOM_DOMAIN}/static/"
AWS_DEFAULT_ACL = None


# no query-string auth (makes URLs cleaner/public)
AWS_QUERYSTRING_AUTH = False

# add cache headers by default
AWS_S3_OBJECT_PARAMETERS = {
    "CacheControl": "max-age=86400",  # cache for 1 day
}

# ensure unique names instead of overwriting
AWS_S3_FILE_OVERWRITE = False

ADMIN_MEDIA_PREFIX = '/static/admin/'

# use the latest signature v4
AWS_S3_SIGNATURE_VERSION = "s3v4"



DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'file': {
            'level': 'DEBUG',
            'class': 'logging.FileHandler',
            'filename': os.path.join(BASE_DIR, 'debug.log'),
        },
    },
    'loggers': {
        'django': {
            'handlers': ['file'],
            'level': 'DEBUG',
            'propagate': True,
        },
    },
}


# INSTAGRAM
INSTAGRAM_CLIENT_ID = os.environ['INSTAGRAM_CLIENT_ID']
INSTAGRAM_CLIENT_SECRET = os.environ['INSTAGRAM_CLIENT_SECRET']
INSTAGRAM_REDIRECT_URI = os.environ['INSTAGRAM_REDIRECT_URI']



# (1) read the secret _name_ from your env or hard‐code:
AWS_PRIVATE_KEY_SECRET = os.environ.get(
    "AWS_PRIVATE_KEY_SECRET", 
    "/meetyourfan/prod/owner/PRIVATE_KEY"
)

import json

raw = get_aws_secret(AWS_PRIVATE_KEY_SECRET)
# parse the JSON you stored
blob = json.loads(raw)
hexkey = blob.get("PRIVATE_KEY")
if not hexkey:
    raise ValueError(f"No PRIVATE_KEY field in secret {AWS_PRIVATE_KEY_SECRET!r}")
# strip whitespace, leading 0x, validate length
hexkey = hexkey.strip()
if hexkey.startswith("0x"):
    hexkey = hexkey[2:]
if len(hexkey) != 64 or any(c not in "0123456789abcdefABCDEF" for c in hexkey):
    raise ValueError(f"Bad private‐key format: {hexkey!r}")
# put it back into 0x form for web3
PRIVATE_KEY = "0x" + hexkey

# BLOCKCHAIN
WEB3_PROVIDER_URL = os.environ['WEB3_PROVIDER_URL']
CONTRACT_ADDRESS = os.environ['CONTRACT_ADDRESS']
CONTRACT_ABI_PATH = BASE_DIR / "blockchain" / "contract_abi.json"
WERT_SC_SIGNER_KEY = os.environ.get('WERT_SC_SIGNER_KEY', '')
OWNER_ADDRESS = os.environ.get('OWNER_ADDRESS', '')
CONVERSION_RATE = int(os.environ.get('CONVERSION_RATE', 10))



