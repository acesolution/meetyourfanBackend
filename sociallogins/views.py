# sociallogins/views.py
import os
import secrets                                 # built-in: cryptographically strong tokens
import requests                                # 3rd-party HTTP client for API calls
from urllib.parse import urlencode             # built-in: dict -> querystring
from django.http import HttpResponseBadRequest, HttpResponseRedirect
# HttpResponseRedirect is a built-in 302 response class
from django.shortcuts import redirect          # built-in shortcut to return 302
from django.urls import reverse                # built-in: resolve view name -> path
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth import get_user_model
from django.conf import settings
from rest_framework.decorators import api_view
from rest_framework.response import Response
from rest_framework import status
from datetime import datetime, timedelta       # built-in: token expiry helpers
from django.utils import timezone              # built-in: timezone-aware now()

User = get_user_model()

IG_AUTH_URL = "https://api.instagram.com/oauth/authorize"
IG_TOKEN_URL = "https://api.instagram.com/oauth/access_token"  # short-lived exchange
# Long-lived exchange + refresh are on graph.instagram.com
IG_LONG_LIVED_URL = "https://graph.instagram.com/access_token"
IG_REFRESH_URL = "https://graph.instagram.com/refresh_access_token"
IG_ME_URL = "https://graph.instagram.com/me"  # identity/profile

def _abs_redirect_uri(request):
    """
    reverse() + build_absolute_uri() produces an absolute callback URL.
    - reverse(name) -> '/social/instagram/callback/' (Django URL resolver, built-in)
    - request.build_absolute_uri(path) -> 'https://api.example.com/social/...'
    """
    return request.build_absolute_uri(reverse("ig-login-callback"))

def instagram_start(request):
    # Generate anti-CSRF state (built-in secrets.token_urlsafe)
    state = secrets.token_urlsafe(32)
    # Store state in the session (built-in request.session behaves like a dict)
    request.session["ig_oauth_state"] = state

    params = {
        "app_id": settings.INSTAGRAM_APP_ID,
        "redirect_uri": settings.INSTAGRAM_REDIRECT_URI or _abs_redirect_uri(request),
        "scope": "instagram_basic",  # request more only as needed
        "response_type": "code",
        "state": state,
    }
    # urlencode() turns dict -> properly escaped query string (?a=1&b=2)
    url = f"{IG_AUTH_URL}?{urlencode(params)}"
    return redirect(url)  # built-in shortcut to send 302 to Instagram

@api_view(["GET"])
def instagram_callback(request):
    # Read query params (request.GET is a built-in dict-like QueryDict)
    code = request.GET.get("code")
    state = request.GET.get("state")
    saved_state = request.session.get("ig_oauth_state")

    if not code or not state or state != saved_state:
        return Response({"detail": "Invalid OAuth state/code."}, status=status.HTTP_400_BAD_REQUEST)

    # 1) Exchange code -> short-lived token (expires ~1 hour)
    # Docs: https://developers.facebook.com/docs/instagram-platform/reference/access_token/
    data = {
        "app_id": settings.INSTAGRAM_APP_ID,
        "app_secret": settings.INSTAGRAM_APP_SECRET,
        "grant_type": "authorization_code",
        "redirect_uri": settings.INSTAGRAM_REDIRECT_URI or _abs_redirect_uri(request),
        "code": code,
    }
    token_resp = requests.post(IG_TOKEN_URL, data=data)
    tok = token_resp.json()
    if "access_token" not in tok:
        return Response({"detail": "Failed to get short-lived token", "raw": tok}, status=400)

    short_token = tok["access_token"]

    # 2) Exchange short-lived -> long-lived (valid ~60 days)
    # GET graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=...&access_token=...
    # Docs: long-lived & refresh endpoints
    ll_params = {
        "grant_type": "ig_exchange_token",
        "client_secret": settings.INSTAGRAM_APP_SECRET,
        "access_token": short_token,
    }
    ll_resp = requests.get(IG_LONG_LIVED_URL, params=ll_params)
    ll = ll_resp.json()
    if "access_token" not in ll:
        return Response({"detail": "Failed to get long-lived token", "raw": ll}, status=400)

    long_token = ll["access_token"]
    # Optional: tokens sometimes include 'expires_in' seconds
    expires_at = timezone.now() + timedelta(days=59)

    # 3) Get user profile (id, username)
    me_params = {
        "fields": "id,username,account_type",  # account_type helps enforce 'professional'
        "access_token": long_token,
    }
    me_resp = requests.get(IG_ME_URL, params=me_params)
    me = me_resp.json()
    if "id" not in me:
        return Response({"detail": "Failed to fetch IG profile", "raw": me}, status=400)

    ig_id = str(me["id"])
    username = me.get("username", f"ig_{ig_id}")
    account_type = me.get("account_type", "")

    # Enforce Professional accounts if your use-case requires it
    if account_type not in {"BUSINESS", "CREATOR"}:
        return Response({"detail": "Instagram Professional account required."}, status=403)

    # 4) Get-or-create local user
    user, _ = User.objects.get_or_create(
        username=f"ig_{username}",
        defaults={"email": "",},  # fill as needed
    )
    # Store tokens on a related model (pseudo code)
    # SocialProfile.objects.update_or_create(
    #     user=user, provider="instagram",
    #     defaults={"provider_uid": ig_id, "access_token": long_token, "token_expires_at": expires_at},
    # )

    # 5) Issue your app token (DRF SimpleJWT example)
    from rest_framework_simplejwt.tokens import RefreshToken  # third-party: JWT util
    refresh = RefreshToken.for_user(user)  # creates a signed JWT pair for this user

    # 6) Redirect back to FE with HttpOnly cookie (safer than query param)
    resp = HttpResponseRedirect(f"{settings.FRONTEND_ORIGIN}/auth/callback")
    # set_cookie is a built-in HttpResponse method
    resp.set_cookie("auth_token", str(refresh.access_token), httponly=True, secure=True, samesite="Lax")
    return resp
