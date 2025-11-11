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
from django.shortcuts import redirect, render
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from api.models import Profile as UserProfile
from rest_framework.response import Response

User = get_user_model()

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
    
    
def is_ios(request) -> bool:
    """
    Best-effort detection of iOS Safari / iOS browsers via User-Agent.
    We use this to decide whether to use a JS-based redirect instead of a
    plain HTTP 302, which tends to trigger the Instagram app on iOS.
    """
    ua = (request.META.get("HTTP_USER_AGENT") or "").lower()
    return "iphone" in ua or "ipad" in ua or "ipod" in ua



# ---- OAUTH VIEWS ------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ig_login_start(request):
    """
    Authenticated start of IG OAuth:
    - uses JWT (request.user) to know the user
    - stores user.id + state + flow in the session
    - returns the Instagram auth_url as JSON
    """
    user = request.user

    state = secrets.token_urlsafe(24)
    request.session["ig_oauth_state"] = state
    request.session["ig_link_user_id"] = user.id

    flow = request.GET.get("flow") or "settings"
    request.session["ig_flow"] = flow

    params = {
        "force_reauth": "true",
        "client_id": IG_APP_ID,
        "redirect_uri": IG_REDIRECT_URI,
        "scope": "instagram_business_basic",
        "response_type": "code",
        "state": state,
    }

    auth_url = "https://www.instagram.com/oauth/authorize?" + urlencode(params)
    logger.info("IG auth URL: %s", auth_url)

    # IMPORTANT: now we just return JSON, no redirect
    return Response({"auth_url": auth_url})

# sociallogins/views.py

def ig_login_callback(request):
    code  = request.GET.get("code")
    state = request.GET.get("state")

    # We'll read flow for redirects (default to settings view)
    flow = request.session.get("ig_flow", "settings")

    # --- CSRF protection using state --------------------------------------
    expected = request.session.get("ig_oauth_state")
    if not code or not state or state != expected:
        logger.warning("Bad IG OAuth state: expected=%s got=%s", expected, state)

        # send the user back to FE with an error flag
        redirect_url = (
            f"{settings.FRONTEND_BASE_URL}/instagram-connection-sucess"
            f"?error=invalid_state&from={flow}"
        )
        return HttpResponseRedirect(redirect_url)

    # once checked, remove it from session so it can't be reused
    request.session.pop("ig_oauth_state", None)

    # recover the user id we stored in ig_login_start
    user_id = request.session.pop("ig_link_user_id", None)

    # --- 2a) code -> short-lived access token -----------------------------
    token_url = "https://api.instagram.com/oauth/access_token"
    data = {
        "client_id": settings.IG_APP_ID,
        "client_secret": settings.IG_APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": settings.IG_REDIRECT_URI,
        "code": code,
    }
    logger.info("Exchanging code for IG access token: %s", data)

    response = requests.post(token_url, data=data, timeout=20)
    token_data = response.json()
    logger.info("Received IG token data: %s", token_data)

    if "access_token" not in token_data:
        # send the error back to FE instead of trying to render a template
        redirect_url = (
            f"{settings.FRONTEND_BASE_URL}/instagram-connection-sucess"
            f"?error=token_exchange_failed&from={flow}"
        )
        return HttpResponseRedirect(redirect_url)

    access_token = token_data["access_token"]
    ig_user_id   = token_data.get("user_id")
    expires_in   = token_data.get("expires_in")

    save_token_session(request, {
        "access_token": access_token,
        "expires_in": expires_in,
    })

    # --- 2b) fetch profile from Graph API to get username -----------------
    me_resp = requests.get(
        "https://graph.instagram.com/me",
        params={
            "fields": "id,username,account_type",
            "access_token": access_token,
        },
        timeout=15,
    )
    me = me_resp.json()
    logger.info("IG /me response: %s", me)

    username      = me.get("username")
    account_type  = me.get("account_type")
    graph_user_id = me.get("id")

    request.session["ig_profile"] = {
        "id": graph_user_id,
        "username": username,
        "account_type": account_type,
    }
    request.session.modified = True

    # --- 2c) tie IG data to the stored user id ----------------------------
    if user_id is not None:
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            user = None

        if user is not None:
            profile, _ = SocialProfile.objects.get_or_create(user=user)
            profile.ig_user_id      = graph_user_id
            profile.ig_username     = username
            profile.ig_access_token = access_token
            if expires_in:
                profile.ig_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
            profile.save()

            # mirror flag on Profile for the green tick
            try:
                user_profile = user.profile
            except UserProfile.DoesNotExist:
                user_profile = None

            if user_profile and user.user_type == "influencer":
                user_profile.instagram_verified = True
                user_profile.save()

            logger.info(
                "Updated SocialProfile for user_id=%s ig_username=%s",
                user.id,
                username,
            )

    # --- 2d) success redirect to FE --------------------------------------
    # remove ig_flow after we’ve used it
    request.session.pop("ig_flow", None)
    redirect_url = (
        f"{settings.FRONTEND_BASE_URL}/instagram-connection-sucess"
        f"?ig_username={username or ''}"
        f"&from={flow}"
    )
    return HttpResponseRedirect(redirect_url)