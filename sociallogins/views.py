# sociallogins/views.py
import os
import secrets                                   # built-in: cryptographically strong tokens
import requests                                  # 3rd-party HTTP client for API calls
from urllib.parse import urlencode               # built-in: dict -> querystring
from datetime import timedelta                   # built-in: to represent "X seconds" spans

from django.http import HttpResponseRedirect, JsonResponse
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model   # built-in: returns the active User model
from django.utils import timezone                # built-in: timezone-aware "now"
from django.conf import settings                 # built-in: access Django settings
from .models import SocialProfile
import logging
from django.contrib.auth import login

from django.shortcuts import redirect, render

logger = logging.getLogger("sociallogins")       # use the named logger we wired in settings

IG_APP_ID       = os.environ["IG_APP_ID"]
IG_APP_SECRET   = os.environ["IG_APP_SECRET"]
IG_REDIRECT_URI = os.environ["IG_REDIRECT_URI"]

# ---- SESSION-BASED STORAGE (NO MYF AUTH) ------------------------------------

SESSION_TOKEN_KEY = "ig_long_lived_token"        # key under which we keep the IG token in session


def save_token_session(request, payload: dict) -> None:
    """
    Store the IG long-lived token in the current Django session.

    - request.session: built-in dict-like per-browser store; persisted via cookie.
    """
    access = payload.get("access_token")
    expires_in = payload.get("expires_in")       # seconds (optional)

    data = {"access_token": access, "expires_in": expires_in}
    # You could also store an absolute expires_at, but for now we keep it simple.
    request.session[SESSION_TOKEN_KEY] = data    # built-in: behaves like dict assignment
    request.session.modified = True              # built-in: mark session dirty so Django saves it
    logger.info("Saved IG token into session; expires_in=%s", expires_in)


def get_token_session(request) -> dict | None:
    """
    Fetch IG token from the session. Returns None if not present.
    """
    data = request.session.get(SESSION_TOKEN_KEY)  # built-in: dict-like .get()
    if not data or not data.get("access_token"):
        return None
    return data


# ---- DB-BASED STORAGE (FOR LATER WHEN YOU TIE IT TO MYF USERS) --------------

def save_token(user_id: int, payload: dict):
    """
    Persist the long-lived IG access token for a specific MYF user.

    Currently UNUSED while you test without MYF auth, but kept here for later.
    """
    User = get_user_model()
    user = User.objects.get(pk=user_id)               # raises DoesNotExist if user missing
    profile, created = SocialProfile.objects.get_or_create(user=user)

    access = payload.get("access_token")
    expires_in = payload.get("expires_in")            # number of seconds until expiry

    profile.ig_access_token = access
    if expires_in:
        profile.ig_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
    profile.save()
    logger.info("Saved IG token in DB for user_id=%s", user_id)


def get_token(user_id: int) -> dict | None:
    """
    Fetch token from DB for a specific user. Currently UNUSED in this guest flow.
    """
    User = get_user_model()
    user = User.objects.get(pk=user_id)
    try:
        profile = user.social_profile                 # reverse OneToOne accessor
    except SocialProfile.DoesNotExist:
        return None

    if not profile.ig_access_token:
        return None

    remaining = None
    if profile.ig_token_expires_at:
        remaining = (profile.ig_token_expires_at - timezone.now()).total_seconds()

    return {
        "access_token": profile.ig_access_token,
        "expires_in": remaining,
    }


# ---- OAUTH VIEWS ------------------------------------------------------------

# sociallogins/views.py

def ig_login_start(request):
    """
    Redirects the user to the Instagram authorization URL.
    """
    auth_url = (
        f"https://api.instagram.com/oauth/authorize?"
        f"client_id={settings.IG_APP_ID}&"
        f"redirect_uri={settings.IG_REDIRECT_URI}&"
        f"scope=user_profile,user_media&" # Request necessary permissions (scopes)
        f"response_type=code"
    )
    logger.info("Redirecting to IG auth URL: %s", auth_url)
    return redirect(auth_url)



def _check_state(session, incoming: str):
    """
    Compare state param from callback with the one we stored.
    secrets.compare_digest -> constant-time compare to avoid timing attacks.
    """
    expected = session.pop("ig_oauth_state", "")
    if not secrets.compare_digest(expected, incoming or ""):
        logger.warning("IG OAuth state mismatch: expected=%s got=%s", expected, incoming)
        raise PermissionDenied("Bad state")


def ig_login_callback(request):
    """
    Handles the redirect from Instagram, exchanges the code for an access token,
    and logs the user into Django.
    """
    code = request.GET.get('code')
    if not code:
        # Handle error or denial of permissions
        return render(request, 'login_failed.html', {'error': 'User denied access'})

    # Exchange the code for a short-lived access token
    token_url = 'https://api.instagram.com/oauth/access_token'
    data = {
        'client_id': settings.IG_APP_ID,
        'client_secret': settings.IG_APP_SECRET,
        'grant_type': 'authorization_code',
        'redirect_uri': settings.IG_REDIRECT_URI,
        'code': code,
    }
    logger.info("Exchanging code for IG access token", data)
    response = requests.post(token_url, data=data)
    token_data = response.json()
    logger.info("Received IG token data: %s", token_data)

    if 'access_token' not in token_data:
        # Handle error in token exchange
        return render(request, 'login_failed.html', {'error': 'Failed to obtain access token'})

    access_token = token_data['access_token']
    user_id = token_data['user_id'] # Use this ID to uniquely identify the user

    # Here you would typically exchange the short-lived token for a long-lived one (60 days)
    # and store it in your database, linked to your Django User model.

    

    logger.info("User %s logged in via IG", user_id, access_token)
    return redirect('home') # Redirect to your desired post-login page


def verify_claimed_handle(request):
    """
    Step 3: prove ownership — fetch username from IG and compare to user claim.

    Uses the IG token from the SESSION, not from any MYF user record.
    Frontend should pass ?claimed_username=<handle>.
    """
    token = get_token_session(request)
    if not token:
        raise PermissionDenied("No IG token in session; connect first.")

    claimed = (request.GET.get("claimed_username") or "").strip().lower()
    logger.info("Verifying claimed IG handle '%s' using session token", claimed)

    me = requests.get(
        "https://graph.instagram.com/me",
        params={
            "fields": "id,username,account_type",
            "access_token": token["access_token"],
        },
        timeout=15,
    ).json()

    if "id" not in me:
        logger.error("Failed to fetch IG profile with session token: %s", me)
        return JsonResponse({"ok": False, "error": "profile_failed", "raw": me}, status=400)

    username = (me.get("username") or "").lower()
    verified = (username == claimed)

    return JsonResponse({
        "ok": True,
        "verified": verified,
        "ig_user_id": me.get("id"),
        "username": me.get("username"),
        "account_type": me.get("account_type"),
    })
