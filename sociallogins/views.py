import os, secrets, requests
from urllib.parse import urlencode                           # built-in: turns dict → querystring safely
from django.http import HttpResponseRedirect, JsonResponse
from django.core.exceptions import PermissionDenied
from django.contrib.auth import get_user_model     # built-in: returns the active User model
from django.utils import timezone                  # built-in: timezone-aware "now"
from datetime import timedelta                     # built-in: to add seconds to a datetime
from .models import SocialProfile
import logging

logger = logging.getLogger(__name__)

IG_APP_ID       = os.environ["IG_APP_ID"]
IG_APP_SECRET   = os.environ["IG_APP_SECRET"]
IG_REDIRECT_URI = os.environ["IG_REDIRECT_URI"]

def save_token(user_id: int, payload: dict):
    """
    Persist the long-lived IG access token for this user.

    - get_user_model(): built-in — returns your AUTH_USER_MODEL.
    - get_or_create(): built-in ORM helper, fetch existing row or create if missing.
    """
    User = get_user_model()
    user = User.objects.get(pk=user_id)               # raises DoesNotExist if user missing
    profile, created = SocialProfile.objects.get_or_create(user=user)

    access = payload.get("access_token")
    expires_in = payload.get("expires_in")            # number of seconds until expiry

    profile.ig_access_token = access
    if expires_in:
        # timezone.now(): built-in — current aware datetime in your project timezone
        # timedelta(seconds=...): built-in — represents "expires_in" seconds from now
        profile.ig_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
    profile.save()

    # optional: also store basic id/username right away if you want
    # (you can call /me here once and update ig_user_id / ig_username.)

def get_token(user_id: int) -> dict | None:
    """
    Fetch token for this user, if it exists.
    Returns a simple dict so the rest of the code doesn't care about the DB.
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
        # total_seconds(): built-in — convert time delta → float seconds
        remaining = (profile.ig_token_expires_at - timezone.now()).total_seconds()

    return {
        "access_token": profile.ig_access_token,
        "expires_in": remaining,
    }

def ig_login_start(request):
    """
    Step 1: send user to Instagram's OAuth authorize screen.
    """
    logger.error("IG login start for user=%s IG_APP_ID=%s redirect=%s",
                 getattr(request.user, "id", None), IG_APP_ID, IG_REDIRECT_URI)
    state = secrets.token_urlsafe(24)                         # built-in: random CSRF token
    request.session["ig_oauth_state"] = state                 # built-in: Django session store

    params = {
        "client_id": IG_APP_ID,
        "redirect_uri": IG_REDIRECT_URI,
        "scope": "user_profile,user_media",                   # minimal read scopes for profile/media
        "response_type": "code",                              # tells IG we want an auth code back
        "state": state,
    }
    return HttpResponseRedirect(
        "https://www.instagram.com/oauth/authorize/?" + urlencode(params)
        # Instagram Login authorize endpoint. urlencode escapes safely. 
    )  # :contentReference[oaicite:3]{index=3}

def _check_state(session, incoming: str):
    """
    Compare state param from callback with stored value.
    secrets.compare_digest → constant-time compare to avoid timing leaks.
    """
    expected = session.pop("ig_oauth_state", "")
    if not secrets.compare_digest(expected, incoming or ""):
        raise PermissionDenied("Bad state")

def ig_login_callback(request):
    """
    Step 2: exchange 'code' → short-lived token, then → long-lived token.
    """
    code  = request.GET.get("code")
    state = request.GET.get("state")
    logger.error("IG callback hit code=%s state=%s", code, state)
    _check_state(request.session, state)

    # 2a) code → short-lived Instagram User access token (expires ~1h)
    # requests.post: built-in HTTP client; .json() parses JSON → dict
    short = requests.post(
        "https://api.instagram.com/oauth/access_token",
        data={
            "client_id": IG_APP_ID,
            "client_secret": IG_APP_SECRET,
            "grant_type": "authorization_code",
            "redirect_uri": IG_REDIRECT_URI,
            "code": code,
        },
        timeout=20,                                           # built-in: abort if server stalls >20s
    ).json()                                                  # expected: { access_token, user_id, ... }
    # :contentReference[oaicite:4]{index=4}

    # 2b) short-lived → long-lived (≈60 days)
    longlived = requests.get(
        "https://graph.instagram.com/access_token",
        params={
            "grant_type": "ig_exchange_token",
            "client_secret": IG_APP_SECRET,
            "access_token": short["access_token"],
        },
        timeout=20,
    ).json()                                                  # expected: { access_token, token_type, expires_in }
    # :contentReference[oaicite:5]{index=5}

    save_token(request.user.id, {
        "access_token": longlived["access_token"],
        "expires_in": longlived.get("expires_in"),
    })
    return HttpResponseRedirect("/settings/social/instagram")

def verify_claimed_handle(request):
    """
    Step 3: prove ownership — fetch username from IG and compare to user claim.
    Frontend posts `claimed_username`.
    """
    token = get_token(request.user.id)
    if not token:
        raise PermissionDenied("No IG token; connect first.")

    claimed = (request.GET.get("claimed_username") or "").strip().lower()
    me = requests.get(
        "https://graph.instagram.com/me",
        params={
            "fields": "id,username,account_type",
            "access_token": token["access_token"],
        },
        timeout=15,
    ).json()                                                  # built-in: parse JSON
    # If the logged-in IG account's username == claimed → verified
    verified = (me.get("username", "").lower() == claimed)
    return JsonResponse({
        "verified": verified,
        "ig_user_id": me.get("id"),
        "username": me.get("username"),
        "account_type": me.get("account_type"),
    })
    # /me and fields usage for profile: id,username,… via Instagram Graph. :contentReference[oaicite:6]{index=6}
