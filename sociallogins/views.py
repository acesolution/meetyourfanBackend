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
from rest_framework.permissions import IsAuthenticated, AllowAny
from api.models import Profile as UserProfile
from rest_framework.response import Response
from django.core import signing
from django.core.signing import BadSignature, SignatureExpired
from api.views import Profile
from django.db import transaction
from django.db.models import Q

IG_STATE_SALT = "ig-oauth-state"

User = get_user_model()

logger = logging.getLogger("sociallogins")       # use the named logger we wired in settings

IG_APP_ID       = os.environ["IG_APP_ID"]
IG_APP_SECRET   = os.environ["IG_APP_SECRET"]
IG_REDIRECT_URI = os.environ["IG_REDIRECT_URI"]

# ---- SESSION-BASED STORAGE (NO MYF AUTH) ------------------------------------
    
def is_ios(request) -> bool:
    """
    Best-effort detection of iOS Safari / iOS browsers via User-Agent.
    We use this to decide whether to use a JS-based redirect instead of a
    plain HTTP 302, which tends to trigger the Instagram app on iOS.
    """
    ua = (request.META.get("HTTP_USER_AGENT") or "").lower()
    return "iphone" in ua or "ipad" in ua or "ipod" in ua


def disconnect_instagram(user) -> None:
    """
    Hard disconnect Instagram from this MYF user.

    Clears:
      - SocialProfile IG fields + token
      - Profile.instagram_verified badge
      - SocialMediaLink rows for IG (optional but recommended)
    """
    # update(): Django ORM built-in -> single SQL UPDATE (fast, no model save() signals)
    SocialProfile.objects.filter(user=user).update(
        ig_user_id=None,
        ig_username=None,
        ig_access_token=None,
        ig_token_expires_at=None,
    )

    # Use all_objects because your default Profile manager hides inactive users.
    # update(): built-in ORM update
    Profile.all_objects.filter(user=user).update(instagram_verified=False)

    

# ---- OAUTH VIEWS ------------------------------------------------------------
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def ig_login_start(request):
    """
    Start IG OAuth using JWT-authenticated user.
    We DO NOT use Django sessions at all here.
    Instead, we encode user_id + flow into a signed `state` token.
    """
    user = request.user
    flow = request.GET.get("flow") or "settings"

    # Put what we need into the state token
    payload = {
        "user_id": user.id,
        "flow": flow,
    }
    state = signing.dumps(payload, salt=IG_STATE_SALT)

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

    return Response({"auth_url": auth_url})

# sociallogins/views.py

def ig_login_callback(request):
    """
    Instagram OAuth callback.
    We NO LONGER rely on Django sessions.
    Instead we:
      - read `code` and `state` from the querystring
      - verify and decode `state` using django.core.signing
      - get user_id + flow from there
      - exchange the code for a token
      - store IG data in SocialProfile and mark instagram_verified
      - redirect back to the frontend
    """
    code  = request.GET.get("code")
    state = request.GET.get("state")

    if not code or not state:
        logger.warning(
            "IG callback missing code or state: code_present=%s state_present=%s",
            bool(code),
            bool(state),
        )
        redirect_url = (
            f"{settings.FRONTEND_BASE_URL}/instagram-connection-sucess"
            f"?error=missing_params"
        )
        return HttpResponseRedirect(redirect_url)

    # --- decode state instead of reading it from session ------------------
    try:
        data = signing.loads(state, salt=IG_STATE_SALT, max_age=600)  # 10 minutes
        user_id = data.get("user_id")
        flow    = data.get("flow") or "settings"
    except SignatureExpired:
        logger.warning("IG OAuth state expired for state=%s", state)
        redirect_url = (
            f"{settings.FRONTEND_BASE_URL}/instagram-connection-sucess"
            f"?error=state_expired"
        )
        return HttpResponseRedirect(redirect_url)
    except BadSignature:
        logger.warning("IG OAuth state invalid for state=%s", state)
        redirect_url = (
            f"{settings.FRONTEND_BASE_URL}/instagram-connection-sucess"
            f"?error=invalid_state"
        )
        return HttpResponseRedirect(redirect_url)

    if not user_id:
        logger.warning("IG OAuth state missing user_id: %s", data)
        redirect_url = (
            f"{settings.FRONTEND_BASE_URL}/instagram-connection-sucess"
            f"?error=invalid_state"
        )
        return HttpResponseRedirect(redirect_url)

    # --- 2a) code -> short-lived access token -----------------------------
    token_url = "https://api.instagram.com/oauth/access_token"
    payload = {
        "client_id": settings.IG_APP_ID,
        "client_secret": settings.IG_APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": settings.IG_REDIRECT_URI,
        "code": code,
    }
    logger.info("Exchanging code for IG access token: %s", payload)

    response = requests.post(token_url, data=payload, timeout=20)
    token_data = response.json()
    logger.info("Received IG token data: %s", token_data)

    if "access_token" not in token_data:
        redirect_url = (
            f"{settings.FRONTEND_BASE_URL}/instagram-connection-sucess"
            f"?error=token_exchange_failed&from={flow}"
        )
        return HttpResponseRedirect(redirect_url)

    access_token = token_data["access_token"]
    ig_user_id   = token_data.get("user_id")
    expires_in   = token_data.get("expires_in")

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
    graph_user_id = me.get("id") or ig_user_id

    # --- 2c) tie IG data to the stored user id ----------------------------
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        user = None

    if user is not None:
        with transaction.atomic():
            # atomic(): built-in Django transaction context manager (commit/rollback as a unit)

            # Lock current user's social profile row (or create it) to avoid race conditions.
            my_sp, _ = SocialProfile.objects.select_for_update().get_or_create(user=user)
            # select_for_update(): DB row lock until transaction commits

            # 1) Find any other MYF users who currently have this IG account linked
            # Prefer ig_user_id (stable). Also guard by username (helps if ig_user_id missing).
            conflicts = (
                SocialProfile.objects
                .select_for_update()
                .select_related("user")
                .filter(
                    Q(ig_user_id=graph_user_id) |
                    Q(ig_username__iexact=username)
                )
                .exclude(user=user)
            )

            # 2) Disconnect IG from conflicting users
            for sp in conflicts:
                disconnect_instagram(sp.user)

            # 3) Attach IG to this user
            my_sp.ig_user_id = graph_user_id
            my_sp.ig_username = username
            my_sp.ig_access_token = access_token
            if expires_in:
                # timedelta(seconds=...): built-in datetime helper for durations
                my_sp.ig_token_expires_at = timezone.now() + timedelta(seconds=expires_in)
            else:
                my_sp.ig_token_expires_at = None
            my_sp.save()

            # 4) Mirror badge to Profile (only influencers, as you already do)
            # Use all_objects to include inactive users if needed
            if user.user_type == "influencer":
                UserProfile.all_objects.filter(user=user).update(instagram_verified=bool(my_sp.is_instagram_verified))
            else:
                # if fans should never show verified, force False
                UserProfile.all_objects.filter(user=user).update(instagram_verified=False)

    # --- 2d) success redirect to FE --------------------------------------
    redirect_url = (
        f"{settings.FRONTEND_BASE_URL}/instagram-connection-sucess"
        f"?ig_username={username or ''}"
        f"&from={flow}"
    )
    return HttpResponseRedirect(redirect_url)


@api_view(["GET"])
@permission_classes([AllowAny])
def ig_status(request):
    """
    Public endpoint: return Instagram connection status for a user.

    Priority:
      1) ?user_id=123
      2) ?username=foo
      3) else, if authenticated, use request.user
      4) else: anonymous with no identifier → no connection
    """
    user = None
    user_id = request.GET.get("user_id")
    username = request.GET.get("username")

    if user_id:
        try:
            user = User.objects.get(pk=user_id)
        except User.DoesNotExist:
            return Response(
                {
                    "connected": False,
                    "username": None,
                    "url": None,
                    "verified": False,
                },
                status=404,
            )
    elif username:
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            return Response(
                {
                    "connected": False,
                    "username": None,
                    "url": None,
                    "verified": False,
                },
                status=404,
            )
    elif request.user.is_authenticated:
        user = request.user

    # anonymous call with no user identifier
    if user is None:
        return Response(
            {
                "connected": False,
                "username": None,
                "url": None,
                "verified": False,
            }
        )

    try:
        sp = user.social_profile  # OneToOne
    except SocialProfile.DoesNotExist:
        return Response(
            {
                "connected": False,
                "username": None,
                "url": None,
                "verified": False,
            }
        )

    username = sp.ig_username
    url = f"https://www.instagram.com/{username}/" if username else None

    return Response(
        {
            "connected": bool(sp.is_instagram_verified),
            "username": username,
            "url": url,
            "verified": bool(sp.is_instagram_verified),
        }
    )